"""B005: independent clock-boundary oracles, real CP-SAT, API and frozen history."""
from dataclasses import replace
from datetime import datetime, time, timedelta
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from ortools.sat.python import cp_model
from sqlalchemy import select

from backend.database import create_db_engine, create_session_factory
from backend.main import create_app
from backend import models as dbm
from backend.seed import seed_database
from backend.adapter import load_term_dataset
from backend.schedule_integrity import publication_eligibility, store_snapshot, SnapshotIntegrityError, decode_snapshot
from engine.constraints import H09LabBlockContiguity
from engine.models import load_dataset_from_json, TimeSlot, TimetableEntry
from engine.timetable_solver import solve_timetable
from engine.validator import TimetableValidator

ROOT = Path(__file__).resolve().parents[1]


def lab_dataset(k=2):
    ds = load_dataset_from_json(ROOT/"data/seed_timetable.json")
    offering = ds.course_offerings[0]
    ds.course_offerings = [offering]
    ds.courses = [replace(ds.courses_by_id[offering.course_id], lecture_hours=0, lab_hours=k)]
    ds.time_slots = [TimeSlot(i+1,1,1,i+1,f"{8+i:02d}:00",f"{9+i:02d}:00") for i in range(k)]
    ds.instructor_availability = []
    ds.timetable_entries = [TimetableEntry(i+1,1,offering.offering_id,offering.instructor_id,offering.batch_id,5,i+1,"Lab") for i in range(k)]
    return ds


def assert_lab_oracle(ds, entries, required):
    """Use datetime and literal expected counts, not H09/solver interval helpers."""
    labs = [entry for entry in entries if entry.session_type == "Lab"]
    assert len(labs) == required
    assert len({e.slot_id for e in labs}) == required
    assert len({e.room_id for e in labs}) == 1
    slots = sorted((ds.slots_by_id[e.slot_id] for e in labs), key=lambda s:s.slot_index)
    assert {s.term_id for s in slots} == {1}
    assert len({s.day_of_week for s in slots}) == 1
    assert [s.slot_index for s in slots] == list(range(slots[0].slot_index,slots[0].slot_index+required))
    for left,right in zip(slots,slots[1:]):
        assert datetime.strptime(left.end_time,"%H:%M") == datetime.strptime(right.start_time,"%H:%M")


def break_block(ds, case):
    if case == "gap": ds.time_slots[1] = replace(ds.time_slots[1],start_time="11:00",end_time="12:00")
    elif case == "overlap": ds.time_slots[1] = replace(ds.time_slots[1],start_time="08:30",end_time="09:30")
    elif case == "weekday": ds.time_slots[1].day_of_week = 2
    elif case == "room": ds.timetable_entries[1].room_id = 4
    elif case == "index_gap": ds.time_slots[1].slot_index = 3
    elif case == "duplicate": ds.timetable_entries[1].slot_id = 1
    elif case == "missing_reference": ds.timetable_entries[1].slot_id = 999
    elif case == "wrong_term": ds.time_slots[1].term_id = 2
    elif case == "missing_session": ds.timetable_entries.pop()
    elif case == "missing_block": ds.timetable_entries = []
    elif case == "extra_session":
        ds.time_slots.append(TimeSlot(3,1,1,3,"10:00","11:00"))
        ds.timetable_entries.append(replace(ds.timetable_entries[-1],entry_id=3,slot_id=3))
    elif case == "malformed": ds.time_slots[1].start_time = "bad-time"
    elif case == "third_gap": ds.time_slots[2] = replace(ds.time_slots[2],start_time="13:00",end_time="14:00")


@pytest.mark.parametrize("k", [1,2,3])
def test_adjacent_lab_has_exact_size_and_physical_boundaries(k):
    ds = lab_dataset(k)
    assert_lab_oracle(ds,ds.timetable_entries,k)
    assert H09LabBlockContiguity().validate(ds) == []
    assert TimetableValidator().validate(ds) == []


@pytest.mark.parametrize("case", ["gap","overlap","weekday","room","index_gap","duplicate","missing_reference","wrong_term","missing_session","missing_block","extra_session","malformed","third_gap"])
def test_independent_h09_rejects_broken_block(case):
    ds = lab_dataset(3 if case == "third_gap" else 2)
    break_block(ds,case)
    violations = H09LabBlockContiguity().validate(ds)
    assert len(violations) == 1
    assert violations[0].rule_code == "H09" and violations[0].severity == "Hard"
    assert "H09" in violations[0].description
    assert TimetableValidator().validate(ds)


@pytest.mark.parametrize("case", ["adjacent","gap","overlap","weekday","room","index_gap","wrong_term","third_gap"])
def test_cp_sat_h09_excludes_physical_gaps(case):
    ds = lab_dataset(3 if case == "third_gap" else 2)
    if case != "adjacent": break_block(ds,case)
    model = cp_model.CpModel()
    sessions = [SimpleNamespace(session_idx=i,occurrence_index=i,session_type="Lab") for i in range(len(ds.timetable_entries))]
    rooms = [SimpleNamespace(room_id=i) for i in (4,5)]
    x = {(u.session_idx,s.slot_id,r.room_id):model.NewBoolVar(f"x{u.session_idx}_{s.slot_id}_{r.room_id}") for u in sessions for s in ds.time_slots for r in rooms}
    context = SimpleNamespace(term_id=1,slots=ds.time_slots,rooms=rooms,x=x,sessions_by_offering={1:sessions},slot_by_day_and_index={(s.day_of_week,s.slot_index):s for s in ds.time_slots})
    for u,entry in zip(sessions,ds.timetable_entries):
        model.AddExactlyOne(var for (index,_,_),var in x.items() if index == u.session_idx)
        model.Add(x[(u.session_idx,entry.slot_id,entry.room_id)] == 1)
    H09LabBlockContiguity().add_to_model(model,context)
    status = cp_model.CpSolver().Solve(model)
    assert (status in (cp_model.OPTIMAL,cp_model.FEASIBLE)) == (case == "adjacent")


@pytest.mark.parametrize("k", [2,3])
@pytest.mark.parametrize("gap", [False,True])
def test_solver_and_independent_clock_oracle_agree(k,gap):
    ds = lab_dataset(k)
    ds.timetable_entries = []
    if gap:
        ds.time_slots[-1] = replace(ds.time_slots[-1],start_time="15:00",end_time="16:00")
    result = solve_timetable(ds,config_id=1,term_id=1,time_limit_s=10)
    assert result.is_feasible == (not gap)
    if gap:
        assert any("H09" in reason for reason in result.reasons)
    else:
        assert_lab_oracle(ds,result.schedule,k)
        assert TimetableValidator().validate(ds,result.schedule,config_id=1) == []


def test_blocked_slot_and_insufficient_supply_are_rejected():
    ds = lab_dataset()
    ds.time_slots[1].is_blocked,ds.time_slots[1].block_reason = True,"Break"
    assert "H07" in {v.rule_code for v in TimetableValidator().validate(ds)}
    ds.timetable_entries = []
    assert not solve_timetable(ds,time_limit_s=10).is_feasible
    ds = lab_dataset(3)
    ds.time_slots.pop(); ds.timetable_entries = []
    assert not solve_timetable(ds,time_limit_s=10).is_feasible


def test_adjacent_lab_can_share_time_with_unrelated_lecture():
    ds = lab_dataset()
    seed = load_dataset_from_json(ROOT/"data/seed_timetable.json")
    ds.course_offerings.append(replace(ds.course_offerings[0],offering_id=99,course_id=3,instructor_id=2,batch_id=2,enrolled_count=30))
    ds.courses.append(replace(seed.courses_by_id[3],lecture_hours=1,lab_hours=0))
    ds.timetable_entries.append(TimetableEntry(99,1,99,2,2,2,1,"Lecture"))
    assert TimetableValidator().validate(ds) == []
    assert_lab_oracle(ds,ds.timetable_entries,2)
    ds.timetable_entries = []
    result = solve_timetable(ds,time_limit_s=10)
    assert result.is_feasible
    assert len(result.schedule) == 3
    assert_lab_oracle(ds,result.schedule,2)


@pytest.mark.parametrize("change", [dict(start_time="08:00",end_time="09:00"),dict(start_time="08:30",end_time="09:30"),dict(end_time="10:30"),dict(day_of_week=8),dict(slot_index=0),dict(start_time="malformed"),dict(start_time="23:00",end_time="01:00")])
def test_solver_still_rejects_malformed_external_grids(change):
    ds = lab_dataset()
    ds.time_slots[1] = replace(ds.time_slots[1],**change)
    ds.timetable_entries = []
    result = solve_timetable(ds,time_limit_s=10)
    assert not result.is_feasible
    assert any("Weekly grid" in reason for reason in result.reasons)


def test_h09_remains_configurable_and_h08_remains_mandatory():
    ds = lab_dataset()
    break_block(ds,"gap")
    for rule in ds.constraint_rules:
        if rule.rule_code == "H09": rule.is_enabled = False
        if rule.rule_code == "H08": rule.is_enabled = False
    assert TimetableValidator().validate(ds) == []
    ds.timetable_entries.pop()
    assert "H08" in {v.rule_code for v in TimetableValidator().validate(ds)}


@pytest.fixture(scope="session")
def lab_db_template(tmp_path_factory):
    path = tmp_path_factory.mktemp("b005_seed")/"template.sqlite"
    engine = create_db_engine(f"sqlite:///{path.as_posix()}")
    seed_database(create_session_factory(engine)); engine.dispose()
    return path


@pytest.fixture
def api(tmp_path,lab_db_template,test_auth_settings,login_as):
    path = tmp_path/"lab.sqlite"
    shutil.copyfile(lab_db_template,path)
    engine = create_db_engine(f"sqlite:///{path.as_posix()}")
    factory = create_session_factory(engine)
    with TestClient(create_app(engine=engine,session_factory=factory,auth_settings=test_auth_settings)) as client:
        client.headers.update(login_as(client,factory))
        yield client,factory
    engine.dispose()


def test_manual_move_rejects_index_adjacent_but_clock_gapped_lab(api):
    client,factory = api
    # Tuesday indexes 2..6 shift together, keeping a valid equal-length grid and
    # the original labs at indexes 2,3 adjacent. Only indexes 1->2 have a gap.
    with factory.begin() as session:
        for slot in session.scalars(select(dbm.TimeSlot).where(dbm.TimeSlot.day_of_week==2,dbm.TimeSlot.slot_index>=2)):
            slot.start_time = (datetime.combine(datetime(2026,1,1),slot.start_time)+timedelta(hours=1)).time()
            slot.end_time = (datetime.combine(datetime(2026,1,1),slot.end_time)+timedelta(hours=1)).time()
    with factory.begin() as session: publication_eligibility(session,1)
    with factory() as session: old_slot = session.get(dbm.TimetableEntry,5).slot_id
    response = client.put("/schedules/1/entries/5",json={"slot_id":7})
    assert response.status_code == 409, response.text
    assert "H09" in response.json()["violated_constraints"]
    assert any("clock-time" in v["description"] for v in response.json()["violations"] if v["conflict_type"] == "LabBlock")
    with factory() as session: assert session.get(dbm.TimetableEntry,5).slot_id == old_slot


def old_context():
    fixture = json.loads((ROOT/"tests/fixtures/b004_timetable_context.json").read_text())
    computed = hashlib.sha256(json.dumps(fixture["context"],sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
    assert computed == fixture["input_hash"]
    return fixture


@pytest.mark.parametrize("archived", [False,True])
def test_real_b004_snapshot_uses_original_clock_definitions(api,archived):
    client,factory = api
    fixture = old_context()
    with factory.begin() as session:
        sch = session.get(dbm.Schedule,1)
        store_snapshot(session,sch,fixture["context"])
        publication_eligibility(session,1)
        sch.status,sch.approved_by,sch.published_at = "Published",3,datetime(2026,11,21)
    if archived:
        with factory.begin() as session: session.get(dbm.Schedule,1).status = "Archived"
    with factory.begin() as session:
        slot = session.get(dbm.TimeSlot,9)
        slot.start_time,slot.end_time = time(18),time(19)
    with factory() as session:
        ds = load_term_dataset(session,1,config_id=1,schedule_id=1)
        assert ds.slots_by_id[9].start_time == "10:00"
        assert H09LabBlockContiguity().validate(ds) == []
        row = session.get(dbm.ScheduleSnapshot,1)
        assert row.input_hash == fixture["input_hash"]
        assert json.loads(row.inputs_json) == fixture["context"]
        assert session.get(dbm.ScheduleValidationReceipt,1).input_hash == fixture["input_hash"]
    assert client.get("/schedules/1/entries").status_code == 200


def test_old_snapshot_with_gapped_lab_is_rejected_without_rewriting(api):
    _,factory = api
    context = old_context()["context"]
    # This valid weekly grid shape passed the prior index-only H09 rule.
    for slot in context["dataset"]["time_slots"]:
        if slot["day_of_week"] == 2 and slot["slot_index"] >= 3:
            for field in ("start_time","end_time"):
                slot[field] = (datetime.strptime(slot[field],"%H:%M")+timedelta(hours=1)).strftime("%H:%M")
    with factory.begin() as session: store_snapshot(session,session.get(dbm.Schedule,1),context)
    with factory() as session:
        original = session.get(dbm.ScheduleSnapshot,1).inputs_json
        with pytest.raises(SnapshotIntegrityError,match="H09"):
            publication_eligibility(session,1)
        assert session.get(dbm.ScheduleSnapshot,1).inputs_json == original
        assert session.get(dbm.Schedule,1).status == "Generated"


def test_snapshot_compatibility_does_not_allow_unknown_engine_fingerprints(api):
    _,factory = api
    fixture = old_context()
    context = fixture["context"]
    context["implementation"]["engine"]["constraints.py"] = "0"*64
    with factory.begin() as session: store_snapshot(session,session.get(dbm.Schedule,1),context)
    with factory() as session:
        with pytest.raises(SnapshotIntegrityError): load_term_dataset(session,1,schedule_id=1)


def test_old_snapshot_is_not_accepted_by_an_unreviewed_future_engine(api,monkeypatch):
    import backend.schedule_integrity as integrity
    _,factory = api
    with factory.begin() as session: store_snapshot(session,session.get(dbm.Schedule,1),old_context()["context"])
    unknown = integrity.implementation_identity()
    unknown["engine"]["constraints.py"] = "f"*64
    monkeypatch.setattr(integrity,"implementation_identity",lambda:unknown)
    with factory() as session:
        with pytest.raises(SnapshotIntegrityError): load_term_dataset(session,1,schedule_id=1)


def test_missing_compatibility_manifest_fails_closed(api,monkeypatch):
    _,factory = api
    fixture = old_context()
    with factory.begin() as session: store_snapshot(session,session.get(dbm.Schedule,1),fixture["context"])
    original_read = Path.read_text
    def read(path,*args,**kwargs):
        if path.name == "b004_to_b005.json": raise FileNotFoundError("Missing compatibility manifest")
        return original_read(path,*args,**kwargs)
    monkeypatch.setattr(Path,"read_text",read)
    with factory() as session:
        with pytest.raises(SnapshotIntegrityError): load_term_dataset(session,1,schedule_id=1)
        assert session.get(dbm.ScheduleSnapshot,1).input_hash == fixture["input_hash"]
