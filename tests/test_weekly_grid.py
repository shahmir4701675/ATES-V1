"""B002: physical time invariants at API, CP-SAT and independent validator boundaries.

Every API test uses real B001 authentication against a fresh isolated SQLite DB.
"""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from ortools.sat.python import cp_model

from backend.database import create_db_engine, create_session_factory, init_db
from backend.main import create_app
from backend.seed import seed_database
from engine.constraints import H01InstructorClash, H02RoomClash, H03BatchClash
from engine.models import load_dataset_from_json, TimetableEntry
from engine.timetable_solver import solve_timetable
from engine.validator import TimetableValidator
from engine.weekly_grid import validate_weekly_grid

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def api(test_auth_settings, login_as):
    engine = create_db_engine("sqlite:///:memory:")
    init_db(engine)
    factory = create_session_factory(engine)
    seed_database(factory)
    with TestClient(create_app(engine=engine, session_factory=factory, auth_settings=test_auth_settings)) as client:
        client.headers.update(login_as(client, factory))
        yield client
    engine.dispose()


@pytest.fixture
def dataset():
    return load_dataset_from_json(ROOT / "data/seed_timetable.json")


@pytest.mark.parametrize("patch", [
    {"start_time": "08:00", "end_time": "09:00"},
    {"start_time": "08:30", "end_time": "09:30"},
    {"start_time": "14:00", "end_time": "14:30"},
    {"start_time": "09:00", "end_time": "08:00"},
    {"start_time": "08:00", "end_time": "08:00"},
    {"start_time": "23:00", "end_time": "00:00"},
    {"start_time": "oops"}, {"start_time": "24:00"},
    {"start_time": "08:00:01"}, {"start_time": "08:60"},
    {"start_time": "08:00Z"}, {"start_time": "8:00"},
    {"day_of_week": 0}, {"day_of_week": 8}, {"day_of_week": True},
    {"day_of_week": "1"}, {"slot_index": 0}, {"slot_index": -1},
    {"slot_index": 32768}, {"slot_index": 1.5},
])
def test_create_rejects_invalid_grid_atomically(api, patch):
    before = api.get("/terms/1/slots").json()
    payload = dict(day_of_week=1, slot_index=99, start_time="14:00", end_time="15:00")
    response = api.post("/terms/1/slots", json=payload | patch)
    assert response.status_code in (422, 409), response.text
    assert api.get("/terms/1/slots").json() == before


@pytest.mark.parametrize("patch", [
    {"start_time": "08:30", "end_time": "09:30"},
    {"end_time": "08:30"}, {"end_time": "07:00"},
    {"start_time": "22:00", "end_time": "01:00"},
    {"start_time": "bad"}, {"day_of_week": 8}, {"slot_index": 0},
    {"start_time": "15:00", "end_time": "16:00"},
    {"slot_index": 2},
])
def test_update_rejects_invalid_candidate_atomically(api, patch):
    before = api.get("/terms/1/slots").json()
    slot_id = next(s["slot_id"] for s in before if s["day_of_week"] == 1 and s["slot_index"] == 1)
    response = api.put(f"/terms/1/slots/{slot_id}", json=patch)
    assert response.status_code in (422, 409), response.text
    assert api.get("/terms/1/slots").json() == before


@pytest.mark.parametrize("patch", [
    {"working_days": [0]}, {"working_days": [8]}, {"working_days": []},
    {"working_days": [1, 1]}, {"working_days": [True]},
    {"first_start_time": "broken"}, {"first_start_time": "23:30"},
    {"slot_length_min": 0}, {"slot_length_min": 30},
    {"slots_per_day": 0}, {"blocked_slot_indices": [0]},
    {"blocked_slot_indices": [3], "slots_per_day": 2},
    {"blocked_slot_indices": [1], "block_reason": " "},
    {},  # Existing indexes/intervals cannot be duplicated by bulk generation.
])
def test_bulk_invalid_grid_is_atomic(api, patch):
    before = api.get("/terms/1/slots").json()
    response = api.post("/terms/1/slots/generate", json=dict(working_days=[1], first_start_time="08:00", slots_per_day=2) | patch)
    assert response.status_code in (422, 409), response.text
    assert api.get("/terms/1/slots").json() == before


def test_adjacent_slots_and_valid_updates(api):
    response = api.post("/terms/1/slots", json=dict(day_of_week=1, slot_index=99, start_time="14:00:00", end_time="15:00:00"))
    assert response.status_code == 201, response.text
    slot_id = response.json()["slot_id"]
    assert api.put(f"/terms/1/slots/{slot_id}", json=dict(start_time="15:00", end_time="16:00", slot_index=100)).status_code == 200


@pytest.mark.parametrize("patch", [
    {"start_time": "08:00", "end_time": "09:00"},
    {"start_time": "08:30", "end_time": "09:30"},
    {"end_time": "09:30"}, {"start_time": "broken"},
    {"start_time": "23:00", "end_time": "00:00"},
    {"start_time": "09:00", "end_time": "09:00"},
    {"day_of_week": 0}, {"day_of_week": 8}, {"slot_index": -1},
    {"slot_index": 32768}, {"slot_index": 1},
    {"slot_id": 1}, {"slot_index": 0},
    {"slot_index": "2"}, {"start_time": "24:00"},
    {"start_time": "08:00:05"},
])
def test_solver_and_validator_reject_external_invalid_grid(dataset, patch):
    dataset.time_slots[1] = replace(dataset.time_slots[1], **patch)
    dataset.timetable_entries = []
    result = solve_timetable(dataset, time_limit_s=10, config_id=1)
    assert not result.is_feasible
    assert any("Weekly grid" in reason for reason in result.reasons)
    assert any(v.rule_code == "C-6" for v in TimetableValidator().validate(dataset))


@pytest.mark.parametrize("start,end", [("08:00", "09:00"), ("08:30", "09:30"), ("09:00", "10:00")])
@pytest.mark.parametrize("constraint,resource", [(H01InstructorClash, "instructor_id"), (H02RoomClash, "room_id"), (H03BatchClash, "batch_id")])
def test_independent_temporal_checks(dataset, constraint, resource, start, end):
    left, right = dataset.time_slots[:2]
    dataset.time_slots = [left, replace(right, start_time=start, end_time=end)]
    offering = dataset.course_offerings[0]
    entries = [TimetableEntry(i + 1, 1, offering.offering_id, 1, 1, 1, slot.slot_id, "Lecture") for i, slot in enumerate(dataset.time_slots)]
    violations = constraint().validate(dataset, entries)
    assert bool(violations) == (start != "09:00")
    if violations:
        assert violations[0].affected_entities["slot_ids"] == [left.slot_id, right.slot_id]
        # The complete validator reports physical conflicts even on an invalid grid.
        assert constraint.rule_code in {v.rule_code for v in TimetableValidator().validate(dataset, entries)}


@pytest.mark.parametrize("constraint", [H01InstructorClash, H02RoomClash, H03BatchClash])
@pytest.mark.parametrize("start,end,feasible", [("08:00", "09:00", False), ("08:30", "09:30", False), ("09:00", "10:00", True)])
def test_cp_sat_physical_occupancy(dataset, constraint, start, end, feasible):
    slots = [dataset.time_slots[0], replace(dataset.time_slots[1], start_time=start, end_time=end)]
    sessions = [SimpleNamespace(session_idx=i) for i in range(2)]
    model = cp_model.CpModel()
    x = {(i, s.slot_id, 1): model.NewBoolVar(f"x{i}") for i, s in enumerate(slots)}
    context = SimpleNamespace(slots=slots, rooms=[SimpleNamespace(room_id=1)], sessions=sessions, x=x, sessions_by_instructor={1: sessions}, sessions_by_batch={1: sessions})
    constraint().add_to_model(model, context)
    for var in x.values():
        model.Add(var == 1)
    assert (cp_model.CpSolver().Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)) == feasible


def test_distinct_resources_can_share_time(dataset):
    slot = dataset.time_slots[0]
    entries = [TimetableEntry(i, 1, i, i, i, i, slot.slot_id, "Lecture") for i in (1, 2)]
    for constraint in (H01InstructorClash, H02RoomClash, H03BatchClash):
        assert constraint().validate(dataset, entries) == []


def test_valid_schedule_counts_still_mandatory(dataset):
    dataset.timetable_entries = []
    result = solve_timetable(dataset, time_limit_s=30, config_id=1)
    assert result.is_feasible
    assert TimetableValidator().validate(dataset, result.schedule, config_id=1) == []
    assert "H08" in {v.rule_code for v in TimetableValidator().validate(dataset, result.schedule[:-1], config_id=1)}


def test_indexes_follow_clock_order(dataset):
    dataset.time_slots[0].slot_index, dataset.time_slots[1].slot_index = 2, 1
    assert "order" in {issue.kind for issue in validate_weekly_grid(dataset.time_slots)}


def test_nondefault_duration_valid_bulk_and_single_slot_update(api):
    term = api.post("/terms", json=dict(name="B002 isolated", start_date="2027-01-01", end_date="2027-06-01", status="Planned"))
    assert term.status_code == 201, term.text
    term_id = term.json()["term_id"]
    response = api.post(f"/terms/{term_id}/slots/generate", json=dict(working_days=[1], first_start_time="10:00", slot_length_min=45, slots_per_day=1))
    assert response.status_code == 201, response.text
    slot_id = response.json()[0]["slot_id"]
    # A one-row update must preserve the configured length too.
    assert api.put(f"/terms/{term_id}/slots/{slot_id}", json=dict(end_time="11:00")).status_code == 422
    assert api.put(f"/terms/{term_id}/slots/{slot_id}", json=dict(start_time="11:00", end_time="11:45")).status_code == 200
    assert api.post(f"/terms/{term_id}/slots", json=dict(day_of_week=2, slot_index=1, start_time="11:00", end_time="11:45")).status_code == 201


@pytest.mark.parametrize("constraint", [H01InstructorClash, H02RoomClash, H03BatchClash])
def test_overlap_chain_does_not_exclude_adjacent_endpoints(dataset, constraint):
    a, b, c = dataset.time_slots[:3]
    slots = [a, replace(b, start_time="08:30", end_time="09:30"), replace(c, start_time="09:00", end_time="10:00")]
    sessions = [SimpleNamespace(session_idx=i) for i in range(3)]
    model = cp_model.CpModel()
    x = {(i, s.slot_id, 1): model.NewBoolVar(f"x{i}") for i, s in enumerate(slots)}
    context = SimpleNamespace(slots=slots, rooms=[SimpleNamespace(room_id=1)], sessions=sessions, x=x, sessions_by_instructor={1: sessions}, sessions_by_batch={1: sessions})
    constraint().add_to_model(model, context)
    for i, s in enumerate(slots):
        model.Add(x[(i, s.slot_id, 1)] == (i != 1))
    assert cp_model.CpSolver().Solve(model) == cp_model.OPTIMAL


def test_cp_sat_allows_distinct_resources_at_identical_time(dataset):
    slots = dataset.time_slots[:1]
    sessions = [SimpleNamespace(session_idx=i) for i in range(2)]
    model = cp_model.CpModel()
    x = {(i, slots[0].slot_id, i + 1): model.NewBoolVar(f"x{i}") for i in range(2)}
    context = SimpleNamespace(slots=slots, rooms=[SimpleNamespace(room_id=i) for i in (1, 2)], sessions=sessions, x=x, sessions_by_instructor={i: [s] for i, s in enumerate(sessions)}, sessions_by_batch={i: [s] for i, s in enumerate(sessions)})
    for constraint in (H01InstructorClash, H02RoomClash, H03BatchClash):
        constraint().add_to_model(model, context)
    for var in x.values():
        model.Add(var == 1)
    assert cp_model.CpSolver().Solve(model) == cp_model.OPTIMAL


def test_missing_required_course_cannot_bypass_session_counts(dataset):
    dataset.courses = []
    assert "H08" in {v.rule_code for v in TimetableValidator().validate(dataset, [])}
