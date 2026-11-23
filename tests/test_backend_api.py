"""Integration tests for Milestone 5b FastAPI routes (`backend/main.py`).

Covers:
- SRS Table 9 master-data CRUD routes (`/departments`, `/courses`, `/instructors`,
  `/instructors/{id}/availability`, `/rooms`, `/batches`, `/terms`, `/terms/{id}/slots`,
  `/terms/{id}/slots/generate`, `/terms/{id}/exam-slots`, `/offerings`, `/enrollments`,
  `/configs`, `/configs/{id}/rules`).
- `POST /schedules/generate` (creates schedule row with `status = 'Generating'`, runs
  the timetable or exam engine in a background worker, and saves all results in one
  database transaction per `DB-6` and `SAF-2`).
- `GET /schedules/{id}/status`, `GET /schedules/{id}/entries`, and `GET /schedules/{id}/conflicts`.
- `PUT /schedules/{id}/entries/{entry_id}` (and `PUT /schedules/{id}/entries`) which
  re-validates candidate moves against enabled hard constraints (`H01`–`H10`, `E01`–`E05`)
  and returns HTTP `409 Conflict` naming the violated constraint when invalid, or updates
  the entry with `is_manual_override = True` when valid.
- Role-check readiness (`require_roles`) and React dev server CORS policy.
- Strictly uses local SQLite (`tmp_path`), never the Supabase database.
"""

from __future__ import annotations

from pathlib import Path
from typing import Tuple
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app import create_app, recover_interrupted_generations
from backend.database import create_db_engine, create_session_factory, init_db
from backend.models import (
    ConflictLog,
    CourseOffering,
    InstructorAvailability,
    Schedule,
    TimeSlot,
)
from backend.seed import seed_database


@pytest.fixture()
def sqlite_app_env(tmp_path: Path, test_auth_settings, login_as) -> Tuple[TestClient, Engine, sessionmaker[Session]]:
    """Create a fresh SQLite-backed FastAPI `TestClient` seeded with the ATES dataset."""
    db_file = tmp_path / "test_ates_api.sqlite"
    db_url = f"sqlite:///{db_file.as_posix()}"
    engine = create_db_engine(db_url)
    init_db(engine)
    session_factory = create_session_factory(engine)
    seed_database(session_factory)

    app = create_app(engine=engine, session_factory=session_factory, auth_settings=test_auth_settings)
    client = TestClient(app)
    client.headers.update(login_as(client, session_factory))
    return client, engine, session_factory


# =====================================================================
# 1. Health, CORS & Role-Readiness Tests
# =====================================================================


def test_cors_allows_react_dev_server_only(
    sqlite_app_env: Tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    """Verify CORS allows the React dev server and rejects unknown external origins."""
    client, _, _ = sqlite_app_env

    # Allowed React dev server origin (Vite default port 5173)
    res_allowed = client.options(
        "/courses",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res_allowed.status_code == 200
    assert res_allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"

    # Allowed React dev server origin (CRA default port 3000)
    res_allowed_3000 = client.options(
        "/courses",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert res_allowed_3000.status_code == 200
    assert res_allowed_3000.headers.get("access-control-allow-origin") == "http://localhost:3000"

    # Disallowed external origin
    res_disallowed = client.options(
        "/courses",
        headers={
            "Origin": "https://malicious.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in res_disallowed.headers


def test_role_check_readiness_enforces_roles_when_header_present(
    sqlite_app_env: Tuple[TestClient, Engine, sessionmaker[Session]],
    login_as,
) -> None:
    """Real credentials grant access; anonymous/forged headers never grant a role."""
    client, _, factory = sqlite_app_env

    assert client.get("/departments", headers={"Authorization": ""}).status_code == 401
    # The default fixture is authenticated by the real login endpoint.
    get_res = client.get("/departments")
    assert get_res.status_code == 200

    # Student role is forbidden from creating courses or generating schedules
    forbidden_course = client.post(
        "/courses",
        headers={**login_as(client, factory, "cs24a_9002"), "X-User-Role": "Coordinator"},
        json={
            "department_id": 1,
            "course_code": "CS999",
            "title": "Unauthorized Course",
            "credit_hours": 3,
            "lecture_hours": 3,
            "lab_hours": 0,
        },
    )
    assert forbidden_course.status_code == 403

    forbidden_gen = client.post(
        "/schedules/generate",
        headers={**login_as(client, factory, "fakhra"), "X-User-Role": "Coordinator"},
        json={"term_id": 1, "schedule_type": "Timetable"},
    )
    assert forbidden_gen.status_code == 403


# =====================================================================
# 2. Master Data CRUD Tests (SRS Table 9)
# =====================================================================


def test_master_data_crud_courses_instructors_rooms_batches(
    sqlite_app_env: Tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    """Verify CRUD operations and domain validations on courses, instructors, rooms, and batches."""
    client, _, _ = sqlite_app_env

    # --- Courses ---
    courses_res = client.get("/courses")
    assert courses_res.status_code == 200
    initial_courses = courses_res.json()
    assert len(initial_courses) == 5

    # Invalid course where lecture_hours + lab_hours == 0 -> 422 (FR-2.2)
    bad_course = client.post(
        "/courses",
        json={
            "department_id": 1,
            "course_code": "CS499",
            "title": "Zero Contact Hours",
            "credit_hours": 3,
            "lecture_hours": 0,
            "lab_hours": 0,
        },
    )
    assert bad_course.status_code == 422

    # Valid course creation
    create_course = client.post(
        "/courses",
        json={
            "department_id": 1,
            "course_code": "CS450",
            "title": "Compiler Construction",
            "credit_hours": 4,
            "lecture_hours": 3,
            "lab_hours": 2,
        },
    )
    assert create_course.status_code == 201
    course_data = create_course.json()
    new_course_id = course_data["course_id"]
    assert course_data["course_code"] == "CS450"
    assert course_data["lab_hours"] == 2

    # Duplicate course code -> 409
    dup_course = client.post(
        "/courses",
        json={
            "department_id": 1,
            "course_code": "CS450",
            "title": "Duplicate Compiler",
            "credit_hours": 3,
            "lecture_hours": 3,
            "lab_hours": 0,
        },
    )
    assert dup_course.status_code == 409

    # Update course
    upd_course = client.put(
        f"/courses/{new_course_id}",
        json={"title": "Advanced Compiler Construction"},
    )
    assert upd_course.status_code == 200
    assert upd_course.json()["title"] == "Advanced Compiler Construction"

    # Soft-deactivate course (FR-2.11)
    del_course = client.delete(f"/courses/{new_course_id}")
    assert del_course.status_code == 200
    assert del_course.json()["is_active"] is False

    # --- Instructors & Availability ---
    inst_res = client.post(
        "/instructors",
        json={
            "department_id": 1,
            "full_name": "Dr. Ada Lovelace",
            "email": "ada.lovelace@ates.edu",
            "max_daily_hours": 4,
            "max_weekly_hours": 12,
        },
    )
    assert inst_res.status_code == 201
    new_inst_id = inst_res.json()["instructor_id"]

    # Put instructor availability
    avail_put = client.put(
        f"/instructors/{new_inst_id}/availability",
        json={
            "slots": [
                {"slot_id": 1, "is_available": False},
                {"slot_id": 2, "is_available": False},
            ]
        },
    )
    assert avail_put.status_code == 200
    assert len(avail_put.json()) == 2

    avail_get = client.get(f"/instructors/{new_inst_id}/availability")
    assert avail_get.status_code == 200
    assert len(avail_get.json()) == 2

    # --- Rooms ---
    room_res = client.post(
        "/rooms",
        json={
            "room_code": "R-301",
            "building": "Block C",
            "capacity": 70,
            "room_type": "Lecture",
        },
    )
    assert room_res.status_code == 201
    new_room_id = room_res.json()["room_id"]

    room_upd = client.put(f"/rooms/{new_room_id}", json={"capacity": 80})
    assert room_upd.status_code == 200
    assert room_upd.json()["capacity"] == 80

    room_del = client.delete(f"/rooms/{new_room_id}")
    assert room_del.status_code == 200
    assert room_del.json()["is_active"] is False

    # --- Batches ---
    batch_res = client.post(
        "/batches",
        json={
            "department_id": 1,
            "program_code": "BSCS",
            "batch_year": 2026,
            "section": "A",
            "strength": 48,
        },
    )
    assert batch_res.status_code == 201
    new_batch_id = batch_res.json()["batch_id"]

    batch_upd = client.put(f"/batches/{new_batch_id}", json={"strength": 50})
    assert batch_upd.status_code == 200
    assert batch_upd.json()["strength"] == 50


def test_master_data_terms_slots_exam_slots_offerings_and_configs(
    sqlite_app_env: Tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    """Verify CRUD for terms, time slots, exam slots (with overlap validation), offerings, and configs."""
    client, _, _ = sqlite_app_env

    # Create a new academic term
    term_res = client.post(
        "/terms",
        json={
            "name": "Spring 2027",
            "start_date": "2027-01-15",
            "end_date": "2027-05-30",
            "status": "Planned",
        },
    )
    assert term_res.status_code == 201
    new_term_id = term_res.json()["term_id"]

    # Generate working days & slots grid (FR-2.7)
    gen_slots_res = client.post(
        f"/terms/{new_term_id}/slots/generate",
        json={
            "working_days": [1, 2, 3],
            "first_start_time": "09:00",
            "slot_length_min": 60,
            "slots_per_day": 3,
            "blocked_slot_indices": [2],
            "block_reason": "Morning Break",
        },
    )
    assert gen_slots_res.status_code == 201
    generated_slots = gen_slots_res.json()
    assert len(generated_slots) == 9
    blocked_slots = [s for s in generated_slots if s["is_blocked"]]
    assert len(blocked_slots) == 3

    # Create an exam slot on 2027-05-17
    exam_slot_1 = client.post(
        f"/terms/{new_term_id}/exam-slots",
        json={
            "exam_date": "2027-05-17",
            "start_time": "09:00",
            "end_time": "12:00",
            "label": "MORNING",
        },
    )
    assert exam_slot_1.status_code == 201

    # Overlapping exam slot on the same date must be rejected with 409 (FR-5.7)
    exam_slot_overlap = client.post(
        f"/terms/{new_term_id}/exam-slots",
        json={
            "exam_date": "2027-05-17",
            "start_time": "11:00",
            "end_time": "14:00",
            "label": "MIDDAY_OVERLAP",
        },
    )
    assert exam_slot_overlap.status_code == 409

    # Offerings CRUD on term 1
    offerings_get = client.get("/offerings?term_id=1")
    assert offerings_get.status_code == 200
    assert len(offerings_get.json()) == 6

    # Configs & mandatory rule protection (FR-5.2)
    configs_get = client.get("/configs")
    assert configs_get.status_code == 200
    assert len(configs_get.json()) >= 2

    # Attempt to disable mandatory rule H01 -> 422 Unprocessable Entity (FR-5.2)
    disable_h01 = client.put(
        "/configs/1/rules",
        json={
            "rules": [
                {"rule_code": "H01", "is_enabled": False, "weight": 0},
            ]
        },
    )
    assert disable_h01.status_code == 422
    assert "H01" in disable_h01.json()["detail"]

    # Non-mandatory rule H06 can be toggled
    toggle_h06 = client.put(
        "/configs/1/rules",
        json={
            "rules": [
                {"rule_code": "H06", "is_enabled": False, "weight": 0},
            ]
        },
    )
    assert toggle_h06.status_code == 200
    h06_rule = next(r for r in toggle_h06.json() if r["rule_code"] == "H06")
    assert h06_rule["is_enabled"] is False

    # Restore H06 to enabled
    restore_h06 = client.put(
        "/configs/1/rules",
        json={
            "rules": [
                {"rule_code": "H06", "is_enabled": True, "weight": 0},
            ]
        },
    )
    assert restore_h06.status_code == 200
    h06_restored = next(r for r in restore_h06.json() if r["rule_code"] == "H06")
    assert h06_restored["is_enabled"] is True


# =====================================================================
# 3. Schedule Generation, Status, Entries & Conflicts Tests
# =====================================================================


def test_post_schedules_generate_creates_generating_row_and_runs_worker(
    sqlite_app_env: Tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    """Verify `POST /schedules/generate` creates the schedule as `'Generating'` and the worker saves results."""
    client, _, _ = sqlite_app_env

    # First verify that the route creates the row with status == 'Generating' before the worker runs
    with patch("backend.routers.schedules.run_schedule_generation_worker") as mock_worker:
        res_queued = client.post(
            "/schedules/generate",
            json={
                "term_id": 1,
                "config_id": 1,
                "schedule_type": "Timetable",
                "solver_time_limit_s": 30,
                "random_seed": 42,
            },
        )
        assert res_queued.status_code == 202
        queued_payload = res_queued.json()
        assert queued_payload["status"] == "Generating"
        queued_id = queued_payload["schedule_id"]
        mock_worker.assert_called_once()

        # Status endpoint while still 'Generating'
        status_queued = client.get(f"/schedules/{queued_id}/status")
        assert status_queued.status_code == 200
        assert status_queued.json()["status"] == "Generating"

    # Now run the full end-to-end Timetable generation with the real background worker
    res_tt = client.post(
        "/schedules/generate",
        json={
            "term_id": 1,
            "config_id": 1,
            "schedule_type": "Timetable",
            "solver_time_limit_s": 30,
            "random_seed": 42,
        },
    )
    assert res_tt.status_code == 202
    tt_schedule_id = res_tt.json()["schedule_id"]

    # After TestClient completes the request + BackgroundTasks, check status
    status_tt = client.get(f"/schedules/{tt_schedule_id}/status")
    assert status_tt.status_code == 200
    status_data = status_tt.json()
    assert status_data["status"] == "Generated"
    assert status_data["solver_status"] in {"optimal", "feasible", "OPTIMAL", "FEASIBLE"}
    assert status_data["entry_count"] == 26
    assert status_data["conflict_count"] == 0

    # Check GET /schedules/{id}/entries
    entries_res = client.get(f"/schedules/{tt_schedule_id}/entries")
    assert entries_res.status_code == 200
    entries_payload = entries_res.json()
    entries = entries_payload["timetable_entries"]
    assert len(entries) == 26
    assert entries[0]["course_code"] != ""
    assert entries[0]["room_code"] != ""
    assert entries[0]["day_of_week"] >= 1

    # Check filtering on GET /schedules/{id}/entries?batch_id=1
    batch1_res = client.get(f"/schedules/{tt_schedule_id}/entries?batch_id=1")
    assert batch1_res.status_code == 200
    batch1_entries = batch1_res.json()["timetable_entries"]
    assert all(e["batch_id"] == 1 for e in batch1_entries)
    assert len(batch1_entries) > 0

    # Check GET /schedules/{id}/conflicts (0 conflicts for feasible seed dataset)
    conflicts_res = client.get(f"/schedules/{tt_schedule_id}/conflicts")
    assert conflicts_res.status_code == 200
    assert conflicts_res.json() == []


def test_post_schedules_generate_exam_schedule_end_to_end(
    sqlite_app_env: Tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    """Verify `POST /schedules/generate` for `schedule_type='Exam'` runs the exam engine and persists allocations."""
    client, _, _ = sqlite_app_env

    res_exam = client.post(
        "/schedules/generate",
        json={
            "term_id": 1,
            "config_id": 2,
            "schedule_type": "Exam",
            "solver_time_limit_s": 30,
            "random_seed": 42,
        },
    )
    assert res_exam.status_code == 202
    exam_schedule_id = res_exam.json()["schedule_id"]

    status_exam = client.get(f"/schedules/{exam_schedule_id}/status")
    assert status_exam.status_code == 200
    status_data = status_exam.json()
    assert status_data["status"] == "Generated"
    assert status_data["entry_count"] == 5
    assert status_data["conflict_count"] == 0

    entries_exam = client.get(f"/schedules/{exam_schedule_id}/entries")
    assert entries_exam.status_code == 200
    exam_entries = entries_exam.json()["exam_entries"]
    assert len(exam_entries) == 5
    for entry in exam_entries:
        assert entry["exam_slot_id"] is not None
        assert len(entry["room_allocations"]) >= 1


def test_post_schedules_generate_infeasible_persists_conflicts(
    sqlite_app_env: Tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    """Verify infeasible generation transitions schedule to `'Infeasible'` and returns conflicts."""
    client, _, session_factory = sqlite_app_env

    # Block all time slots so timetable becomes infeasible
    with session_factory() as session:
        with session.begin():
            slots = session.scalars(select(TimeSlot).where(TimeSlot.term_id == 1)).all()
            for slot in slots:
                slot.is_blocked = True
                slot.block_reason = "Blocked for infeasibility test"

    res_infeasible = client.post(
        "/schedules/generate",
        json={
            "term_id": 1,
            "config_id": 1,
            "schedule_type": "Timetable",
            "solver_time_limit_s": 10,
            "random_seed": 42,
        },
    )
    assert res_infeasible.status_code == 202
    sched_id = res_infeasible.json()["schedule_id"]

    status_res = client.get(f"/schedules/{sched_id}/status")
    assert status_res.status_code == 200
    assert status_res.json()["status"] == "Infeasible"
    assert status_res.json()["conflict_count"] >= 1

    conflicts_res = client.get(f"/schedules/{sched_id}/conflicts")
    assert conflicts_res.status_code == 200
    conflicts = conflicts_res.json()
    assert len(conflicts) >= 1
    assert conflicts[0]["conflict_type"] != ""
    assert conflicts[0]["description"] != ""


# =====================================================================
# 4. Manual Move & Constraint Re-Validation (`PUT /schedules/{id}/entries/{entry_id}`)
# =====================================================================


def test_put_schedule_entry_valid_move_and_409_on_violated_timetable_constraints(
    sqlite_app_env: Tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    """Verify `PUT /schedules/{id}/entries/{entry_id}` updates valid moves and returns 409 naming violated H-codes."""
    client, _, session_factory = sqlite_app_env

    # Include the capacity-test room in the immutable generation context (B004).
    tiny_room_res = client.post(
        "/rooms",
        json={"room_code": "TINY-10", "building": "Block A", "capacity": 10, "room_type": "Lecture"},
    )
    assert tiny_room_res.status_code == 201
    tiny_room_id = tiny_room_res.json()["room_id"]
    spacious_room_res = client.post(
        "/rooms",
        json={"room_code": "R-SPACIOUS-100", "building": "Block A", "capacity": 100, "room_type": "Lecture"},
    )
    assert spacious_room_res.status_code == 201
    spacious_room_id = spacious_room_res.json()["room_id"]

    # Generate a valid timetable first
    gen_res = client.post(
        "/schedules/generate",
        json={
            "term_id": 1,
            "config_id": 1,
            "schedule_type": "Timetable",
            "solver_time_limit_s": 30,
            "random_seed": 42,
        },
    )
    assert gen_res.status_code == 202
    schedule_id = gen_res.json()["schedule_id"]

    entries = client.get(f"/schedules/{schedule_id}/entries").json()["timetable_entries"]
    assert len(entries) == 26

    # Pick a lecture entry (`session_type == 'Lecture'`)
    lecture_entries = [e for e in entries if e["session_type"] == "Lecture"]
    target_entry = lecture_entries[0]
    target_entry_id = target_entry["entry_id"]

    # --- Case 1: H01 / H02 / H03 Clash (move target_entry into the exact same slot & room as another entry) ---
    other_entry = next(
        e
        for e in lecture_entries
        if e["entry_id"] != target_entry_id and e["slot_id"] != target_entry["slot_id"]
    )
    clash_res = client.put(
        f"/schedules/{schedule_id}/entries/{target_entry_id}",
        json={
            "slot_id": other_entry["slot_id"],
            "room_id": other_entry["room_id"],
        },
    )
    assert clash_res.status_code == 409
    clash_body = clash_res.json()
    assert "H02" in clash_body["violated_constraints"] or clash_body["rule_code"] in {
        "H01",
        "H02",
        "H03",
    }
    assert any(code in clash_body["detail"] for code in ("H01", "H02", "H03"))

    # --- Case 2: H05 Room Type Mismatch (move a Lab entry into a Lecture room) ---
    lab_entry = next(e for e in entries if e["session_type"] == "Lab")
    lecture_room_id = target_entry["room_id"]  # A Lecture room
    h05_res = client.put(
        f"/schedules/{schedule_id}/entries/{lab_entry['entry_id']}",
        json={
            "slot_id": lab_entry["slot_id"],
            "room_id": lecture_room_id,
        },
    )
    assert h05_res.status_code == 409
    h05_body = h05_res.json()
    assert "H05" in h05_body["violated_constraints"]
    assert "H05" in h05_body["detail"]

    # --- Case 3: H07 Blocked Slot (move an entry into a recess/blocked slot) ---
    with session_factory() as session:
        blocked_slot = session.scalars(
            select(TimeSlot).where(TimeSlot.term_id == 1, TimeSlot.is_blocked.is_(True))
        ).first()
        assert blocked_slot is not None
        blocked_slot_id = blocked_slot.slot_id

    h07_res = client.put(
        f"/schedules/{schedule_id}/entries/{target_entry_id}",
        json={
            "slot_id": blocked_slot_id,
            "room_id": target_entry["room_id"],
        },
    )
    assert h07_res.status_code == 409
    h07_body = h07_res.json()
    assert "H07" in h07_body["violated_constraints"]
    assert "H07" in h07_body["detail"]

    # --- Case 4: H06 Instructor Availability (move an entry into an UNAVAILABLE slot for its instructor) ---
    with session_factory() as session:
        unavail = session.scalars(
            select(InstructorAvailability).where(
                InstructorAvailability.is_available.is_(False)
            )
        ).first()
        assert unavail is not None
        unavail_inst_id = unavail.instructor_id
        unavail_slot_id = unavail.slot_id

    inst_entry = next(e for e in entries if e["instructor_id"] == unavail_inst_id)
    h06_res = client.put(
        f"/schedules/{schedule_id}/entries/{inst_entry['entry_id']}",
        json={
            "slot_id": unavail_slot_id,
            "room_id": inst_entry["room_id"],
        },
    )
    assert h06_res.status_code == 409
    h06_body = h06_res.json()
    assert "H06" in h06_body["violated_constraints"]
    assert "H06" in h06_body["detail"]

    # --- Case 5: H04 Room Capacity (move target_entry into the captured capacity-10 room) ---

    h04_res = client.put(
        f"/schedules/{schedule_id}/entries/{target_entry_id}",
        json={
            "slot_id": target_entry["slot_id"],
            "room_id": tiny_room_id,
        },
    )
    assert h04_res.status_code == 409
    h04_body = h04_res.json()
    assert "H04" in h04_body["violated_constraints"]
    assert "H04" in h04_body["detail"]

    # Verify failed moves did NOT alter target_entry in the database
    entries_after_failures = client.get(
        f"/schedules/{schedule_id}/entries"
    ).json()["timetable_entries"]
    unchanged_target = next(e for e in entries_after_failures if e["entry_id"] == target_entry_id)
    assert unchanged_target["slot_id"] == target_entry["slot_id"]
    assert unchanged_target["room_id"] == target_entry["room_id"]
    assert unchanged_target["is_manual_override"] is False

    # --- Case 6: Valid Move & Lock (`200 OK`, marks `is_manual_override = True` and `is_locked = True`) ---
    # The spacious room was captured before generation, so the version can use it.

    valid_move_res = client.put(
        f"/schedules/{schedule_id}/entries/{target_entry_id}",
        json={
            "slot_id": target_entry["slot_id"],
            "room_id": spacious_room_id,
            "is_locked": True,
        },
    )
    assert valid_move_res.status_code == 200
    updated_entry = valid_move_res.json()
    assert updated_entry["room_id"] == spacious_room_id
    assert updated_entry["is_manual_override"] is True
    assert updated_entry["is_locked"] is True


def test_put_schedule_entry_exam_validation_409_and_valid_move(
    sqlite_app_env: Tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    """Verify `PUT /schedules/{id}/entries/{entry_id}` for Exam schedules enforces E01–E05."""
    client, _, _ = sqlite_app_env

    # Generate a valid exam schedule
    gen_res = client.post(
        "/schedules/generate",
        json={
            "term_id": 1,
            "config_id": 2,
            "schedule_type": "Exam",
            "solver_time_limit_s": 30,
            "random_seed": 42,
        },
    )
    assert gen_res.status_code == 202
    schedule_id = gen_res.json()["schedule_id"]

    exam_entries = client.get(f"/schedules/{schedule_id}/entries").json()["exam_entries"]
    assert len(exam_entries) == 5

    # Find two exam entries in different exam slots
    first_entry = exam_entries[0]
    second_entry = next(
        e for e in exam_entries if e["exam_slot_id"] != first_entry["exam_slot_id"]
    )

    # Moving first_entry into second_entry's exam_slot_id and same room triggers E01 and/or E04 -> 409
    shared_room_id = second_entry["room_allocations"][0]["room_id"]
    allocated_seats = sum(r["seats_allocated"] for r in first_entry["room_allocations"])
    conflict_exam_res = client.put(
        f"/schedules/{schedule_id}/entries/{first_entry['exam_entry_id']}",
        json={
            "exam_slot_id": second_entry["exam_slot_id"],
            "room_allocations": [
                {"room_id": shared_room_id, "seats_allocated": allocated_seats},
            ],
        },
    )
    assert conflict_exam_res.status_code == 409
    conflict_body = conflict_exam_res.json()
    assert any(code in conflict_body["violated_constraints"] for code in ("E01", "E02", "E03", "E04"))

    # Valid lock toggle on first_entry without violating E01–E05 -> 200 OK
    valid_exam_res = client.put(
        f"/schedules/{schedule_id}/entries/{first_entry['exam_entry_id']}",
        json={"is_locked": True},
    )
    assert valid_exam_res.status_code == 200
    assert valid_exam_res.json()["is_locked"] is True


def test_startup_recovery_marks_interrupted_generations_as_infeasible(
    sqlite_app_env: Tuple[TestClient, Engine, sessionmaker[Session]],
) -> None:
    """Verify `recover_interrupted_generations` marks left-over `'Generating'` rows as `'Infeasible'` (SRS 4.3.2)."""
    _, _, session_factory = sqlite_app_env

    with session_factory() as session:
        with session.begin():
            interrupted = Schedule(
                term_id=1,
                config_id=1,
                schedule_type="Timetable",
                version_no=99,
                status="Generating",
                generated_by=1,
            )
            session.add(interrupted)
            session.flush()
            interrupted_id = interrupted.schedule_id

    recovered_count = recover_interrupted_generations(session_factory)
    assert recovered_count == 1

    with session_factory() as session:
        recovered = session.get(Schedule, interrupted_id)
        assert recovered is not None
        assert recovered.status == "Infeasible"
        assert recovered.solver_status == "interrupted"

        conflict_logs = session.scalars(
            select(ConflictLog).where(
                ConflictLog.schedule_id == interrupted_id,
                ConflictLog.conflict_type == "ServerRestart",
            )
        ).all()
        assert len(conflict_logs) == 1
