"""B004: isolated file-backed SQLite version, migration and concurrency regressions."""
from datetime import datetime, time
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from threading import Event, Thread

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func, text, event
from sqlalchemy.exc import IntegrityError

from backend.database import create_db_engine, create_session_factory, init_db
from backend.seed import seed_database
from backend.main import create_app
from backend import models as m
from backend.adapter import load_term_dataset, save_timetable_result, TermScheduleAdapter
from backend.schedule_integrity import (capture_inputs, publication_eligibility, SnapshotIntegrityError,
    canonical, digest, decode_snapshot, lock_inputs)
from backend.routers.schedules import run_schedule_generation_worker
from engine.timetable_solver import solve_timetable
from engine.validator import TimetableValidator, ExamValidator

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def integrity_template(tmp_path_factory):
    path = tmp_path_factory.mktemp("b004_seed") / "template.sqlite"
    engine = create_db_engine(f"sqlite:///{path.as_posix()}")
    seed_database(create_session_factory(engine))
    engine.dispose()
    return path


@pytest.fixture
def env(tmp_path, test_auth_settings, login_as, integrity_template):
    shutil.copyfile(integrity_template, tmp_path / "b004.sqlite")
    url = f"sqlite:///{(tmp_path / 'b004.sqlite').as_posix()}"
    engine = create_db_engine(url)
    factory = create_session_factory(engine)
    with TestClient(create_app(engine=engine, session_factory=factory, auth_settings=test_auth_settings)) as client:
        client.headers.update(login_as(client, factory))
        yield client, factory, engine, url
    engine.dispose()


def freeze(factory, schedule_id, published=False):
    with factory.begin() as session:
        publication_eligibility(session, schedule_id)
        if published:
            sch = session.get(m.Schedule, schedule_id)
            sch.status, sch.approved_by, sch.published_at = "Published", 3, datetime(2026, 11, 21)


def load(factory, schedule_id):
    with factory() as session:
        sch = session.get(m.Schedule, schedule_id)
        return load_term_dataset(session, sch.term_id, config_id=sch.config_id, schedule_id=schedule_id)


def mutate(session, kind):
    if kind == "room_capacity": session.get(m.Room, 1).capacity = 1
    elif kind == "room_type": session.get(m.Room, 1).room_type = "Lab"
    elif kind == "room_inactive": session.get(m.Room, 1).is_active = False
    elif kind == "room_label": session.get(m.Room, 1).room_code = "B004-new-name"
    elif kind == "availability":
        row = session.scalar(select(m.InstructorAvailability).limit(1)); row.is_available = not row.is_available
    elif kind == "offering_batch": session.get(m.CourseOffering, 2).batch_id = 2
    elif kind == "offering_instructor": session.get(m.CourseOffering, 2).instructor_id = 1
    elif kind == "enrollment_count": session.get(m.CourseOffering, 2).enrolled_count = 99
    elif kind == "course_inactive": session.get(m.Course, 1).is_active = False
    elif kind == "course_requirements": session.get(m.Course, 1).lecture_hours = 5
    elif kind == "course_title": session.get(m.Course, 1).title = "B004 edited title"
    elif kind == "slot_clock":
        row = session.get(m.TimeSlot, 1); row.start_time, row.end_time = time(18), time(19)
    elif kind == "blocked_slot":
        row = session.get(m.TimeSlot, 1); row.is_blocked, row.block_reason = True, "New break"
    elif kind == "configuration":
        row = session.scalar(select(m.ConstraintRule).where(m.ConstraintRule.rule_code == "H04")); row.is_enabled = False
    elif kind == "instructor_load": session.get(m.Instructor, 1).max_daily_hours = 1
    elif kind == "batch_strength": session.get(m.Batch, 1).strength = 99
    elif kind == "exam_enrollments":
        session.delete(session.scalar(select(m.Enrollment).limit(1)))
    elif kind == "exam_clock":
        row = session.get(m.ExamSlot, 1); row.start_time, row.end_time = time(18), time(19)
    elif kind == "exam_configuration":
        row = session.scalar(select(m.ConstraintRule).where(m.ConstraintRule.rule_code == "E02")); row.param_value = 1


TIMETABLE_MUTATIONS = ["room_capacity", "room_type", "room_inactive", "room_label", "availability",
    "offering_batch", "offering_instructor", "enrollment_count", "course_inactive", "course_requirements",
    "course_title", "slot_clock", "blocked_slot", "configuration", "instructor_load", "batch_strength"]
EXAM_MUTATIONS = ["room_capacity", "room_type", "room_inactive", "room_label", "offering_batch", "offering_instructor",
    "enrollment_count", "course_inactive", "course_title", "exam_enrollments", "exam_clock", "exam_configuration"]


@pytest.mark.parametrize("published", [False, True], ids=["generated", "published"])
@pytest.mark.parametrize("schedule_id,kind", [(1, k) for k in TIMETABLE_MUTATIONS] + [(2, k) for k in EXAM_MUTATIONS])
def test_master_mutations_preserve_authoritative_context(env, published, schedule_id, kind):
    client, factory, _, _ = env
    freeze(factory, schedule_id, published)
    before = load(factory, schedule_id)
    response_before = client.get(f"/schedules/{schedule_id}/entries").json()
    with factory() as session:
        snapshot_before = session.get(m.ScheduleSnapshot, schedule_id).inputs_json
    # Composite FK identity changes may be rejected, preserving the original link.
    try:
        with factory.begin() as session: mutate(session, kind)
    except IntegrityError:
        assert kind in {"offering_batch", "offering_instructor"}
    after = load(factory, schedule_id)
    assert after.rooms_by_id[1].capacity == before.rooms_by_id[1].capacity == 50
    assert after.to_dict() == before.to_dict()
    validator = TimetableValidator() if schedule_id == 1 else ExamValidator()
    assert validator.validate(after, config_id=schedule_id) == []
    response = client.get(f"/schedules/{schedule_id}/entries")
    assert response.status_code == 200, response.text
    assert response.json() == response_before
    with factory() as session:
        assert session.get(m.ScheduleSnapshot, schedule_id).inputs_json == snapshot_before


@pytest.mark.parametrize("schedule_id", [1, 2])
def test_snapshot_survives_restart_and_unrelated_edits(env, schedule_id, test_auth_settings, login_as):
    _, factory, _, url = env
    freeze(factory, schedule_id, True)
    original = load(factory, schedule_id)
    with factory.begin() as session:
        session.add(m.Department(code="B004", name="Unrelated department"))
    fresh_engine = create_db_engine(url)
    fresh_factory = create_session_factory(fresh_engine)
    with TestClient(create_app(engine=fresh_engine, session_factory=fresh_factory, auth_settings=test_auth_settings)) as client:
        client.headers.update(login_as(client, fresh_factory))
        assert client.get(f"/schedules/{schedule_id}/entries").status_code == 200
    assert load(fresh_factory, schedule_id).to_dict() == original.to_dict()
    fresh_engine.dispose()


@pytest.mark.parametrize("schedule_id,config_id,kind", [(1,1,"Timetable"),(2,2,"Exam")])
def test_new_generation_uses_current_inputs_and_preserves_versions(env, schedule_id, config_id, kind):
    client, factory, _, _ = env
    freeze(factory, schedule_id, True)
    with factory.begin() as session:
        session.get(m.Course, 1).title = "Current course title"
    response = client.post("/schedules/generate", json=dict(term_id=1, config_id=config_id, schedule_type=kind, solver_time_limit_s=10))
    assert response.status_code == 202, response.text
    new_id = response.json()["schedule_id"]
    assert client.get(f"/schedules/{new_id}/status").json()["status"] == "Generated"
    assert load(factory, new_id).courses_by_id[1].title == "Current course title"
    assert load(factory, schedule_id).courses_by_id[1].title != "Current course title"
    with factory.begin() as session:
        old = session.get(m.Schedule, schedule_id); old.status = "Archived"
        new = session.get(m.Schedule, new_id)
        new.status, new.approved_by, new.published_at = "Published", 3, datetime(2026,11,22)
    assert load(factory, schedule_id).courses_by_id[1].title != load(factory, new_id).courses_by_id[1].title


@pytest.mark.parametrize("statement", [
    "UPDATE timetable_entries SET is_locked=1 WHERE schedule_id=1",
    "DELETE FROM timetable_entries WHERE schedule_id=1",
    "UPDATE exam_entries SET is_locked=1 WHERE schedule_id=2",
    "DELETE FROM exam_room_allocations WHERE exam_entry_id=1",
    "UPDATE schedule_snapshots SET input_hash='" + "0"*64 + "' WHERE schedule_id=1",
    "DELETE FROM schedule_snapshots WHERE schedule_id=2",
    "DELETE FROM schedule_validation_receipts WHERE schedule_id=1",
    "UPDATE schedule_validation_receipts SET input_hash='invalid' WHERE schedule_id=2",
    "UPDATE schedules SET status='Generated' WHERE schedule_id=1",
    "UPDATE schedules SET approved_by=NULL WHERE schedule_id=1",
    "DELETE FROM schedules WHERE schedule_id=2",
])
def test_database_guards_prevent_official_rewrites(env, statement):
    _, factory, _, _ = env
    freeze(factory, 1, True); freeze(factory, 2, True)
    with pytest.raises(IntegrityError):
        with factory.begin() as session: session.execute(text(statement))
    assert len(load(factory, 1).timetable_entries) == 26
    assert len(load(factory, 2).exam_entries) == 5


@pytest.mark.parametrize("schedule_id", [1,2])
def test_unauthorized_snapshot_and_official_entry_changes_are_rejected(env, schedule_id, login_as):
    client, factory, _, _ = env
    freeze(factory, schedule_id, True)
    with factory() as session: original = session.get(m.ScheduleSnapshot, schedule_id).inputs_json
    client.headers.clear()
    assert client.put(f"/schedules/{schedule_id}/entries/1", json={"is_locked":True}, headers={"X-User-Role":"Coordinator"}).status_code == 401
    student = login_as(client, factory, "cs24a_9002")
    assert client.put(f"/schedules/{schedule_id}/entries/1", json={"is_locked":True}, headers=student).status_code == 403
    assert client.put(f"/schedules/{schedule_id}/snapshot", json={"inputs_json":"{}"}, headers=student).status_code in {403,404,405}
    with factory() as session: assert session.get(m.ScheduleSnapshot, schedule_id).inputs_json == original


@pytest.mark.parametrize("change", ["bad_json", "bad_hash", "wrong_scope", "wrong_policy", "missing_dataset", "bad_config", "bad_scalar"])
def test_invalid_snapshot_data_is_rejected(env, change):
    _, factory, _, _ = env
    freeze(factory, 1)
    with factory() as session:
        row = session.get(m.ScheduleSnapshot, 1)
        data = json.loads(row.inputs_json)
        fake = SimpleNamespace(**{key:getattr(row,key) for key in ("format_version","term_id","schedule_type","inputs_json","input_hash")})
        if change == "bad_json": fake.inputs_json = "[broken"
        elif change == "bad_hash": fake.input_hash = "0"*64
        else:
            if change == "wrong_scope": data["term_id"] = 99
            elif change == "wrong_policy": data["policy"] = "unknown"
            elif change == "missing_dataset": del data["dataset"]["time_slots"]
            elif change == "bad_config": data["dataset"]["scheduling_configs"][0]["schedule_type"] = "Exam"
            elif change == "bad_scalar": data["dataset"]["rooms"][0]["is_active"] = "false"
            fake.inputs_json, fake.input_hash = canonical(data), digest(data)
        with pytest.raises(SnapshotIntegrityError): decode_snapshot(fake, session.get(m.Schedule, 1))


def test_invalid_publication_rolls_back_context_and_status(env):
    _, factory, _, _ = env
    with factory.begin() as session: session.get(m.Room, 1).capacity = 1
    with pytest.raises(SnapshotIntegrityError):
        freeze(factory, 1, True)
    with factory() as session:
        assert session.get(m.Schedule, 1).status == "Generated"
        assert session.get(m.ScheduleSnapshot, 1) is None


def test_relevant_change_during_solving_is_rejected_and_rolled_back(env):
    _, factory, _, _ = env
    adapter = TermScheduleAdapter(factory)
    dataset = adapter.load_term(1, include_existing_schedules=False)
    result = solve_timetable(dataset, term_id=1, config_id=1, time_limit_s=10)
    assert result.is_feasible
    with factory() as session: counts = [session.scalar(select(func.count()).select_from(t)) for t in (m.Schedule,m.TimetableEntry,m.ScheduleSnapshot,m.AuditLog)]
    with factory.begin() as session: session.get(m.Room,1).capacity = 44
    with pytest.raises(SnapshotIntegrityError, match="changed during generation"):
        adapter.save_result(result, term_id=1, config_id=1, generated_by=1)
    with factory() as session:
        assert [session.scalar(select(func.count()).select_from(t)) for t in (m.Schedule,m.TimetableEntry,m.ScheduleSnapshot,m.AuditLog)] == counts


def test_source_write_is_serialized_with_input_capture(env):
    _, factory, _, _ = env
    started, committed = Event(), Event()
    errors = []
    def writer():
        try:
            with factory.begin() as session:
                started.set()
                session.get(m.Room,1).capacity = 44
            committed.set()
        except Exception as exc: errors.append(exc)
    with factory.begin() as session:
        context = capture_inputs(session, 1, "Timetable", 1)
        thread = Thread(target=writer); thread.start()
        assert started.wait(2)
        assert not committed.wait(.1)
        assert next(r for r in context["dataset"]["rooms"] if r["room_id"] == 1)["capacity"] == 50
    thread.join(5)
    assert not errors and committed.is_set()


def test_database_failure_during_snapshot_save_rolls_back_all_rows(env):
    _, factory, engine, _ = env
    adapter = TermScheduleAdapter(factory)
    dataset = adapter.load_term(1, include_existing_schedules=False)
    result = solve_timetable(dataset, term_id=1, config_id=1, time_limit_s=10)
    assert result.is_feasible
    def fail(conn,cursor,statement,params,context,many):
        if statement.startswith("INSERT INTO schedule_snapshots"):
            raise RuntimeError("Injected disposable-database failure")
    event.listen(engine,"before_cursor_execute",fail)
    try:
        with pytest.raises(RuntimeError, match="Injected"):
            adapter.save_result(result,term_id=1,config_id=1,generated_by=1)
    finally: event.remove(engine,"before_cursor_execute",fail)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.Schedule)) == 2
        assert session.scalar(select(func.count()).select_from(m.TimetableEntry)) == 26
        assert session.scalar(select(func.count()).select_from(m.ScheduleSnapshot)) == 0


def test_sqlite_additive_migration_and_legacy_fail_closed(tmp_path):
    engine = create_db_engine(f"sqlite:///{(tmp_path/'upgrade.sqlite').as_posix()}")
    baseline = [table for table in m.Base.metadata.sorted_tables if table.name not in {"schedule_snapshots","schedule_input_state","schedule_validation_receipts","generation_runs", "import_stages", "schedule_edit_revisions"}]
    m.Base.metadata.create_all(engine, tables=baseline)
    factory = create_session_factory(engine)
    seed_database(factory)
    # seed_database initializes modern DDL. Remove only B004 objects in this
    # disposable database to reconstruct the actual pre-migration 22-table schema.
    with engine.begin() as conn:
        names = conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'b004_%'").scalars().all()
        for name in names: conn.exec_driver_sql(f'DROP TRIGGER "{name}"')
        for name in ("generation_runs", "import_stages", "schedule_edit_revisions", "schedule_validation_receipts", "schedule_snapshots", "schedule_input_state"):
            conn.exec_driver_sql(f'DROP TABLE "{name}"')
    # Simulate an already-official deployment before B004. No original inputs exist.
    with engine.begin() as conn:
        conn.exec_driver_sql("UPDATE schedules SET status='Published',approved_by=3,published_at=CURRENT_TIMESTAMP WHERE schedule_id=1")
    migration = (ROOT/"db/migrations/002_schedule_snapshots.sqlite.sql").read_text()
    raw = engine.raw_connection()
    try:
        raw.driver_connection.executescript(migration)
        raw.driver_connection.executescript(migration)  # Reviewed DDL is repeatable.
    finally: raw.close()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.Schedule)) == 2
        assert session.scalar(select(func.count()).select_from(m.ScheduleSnapshot)) == 0
        with pytest.raises(SnapshotIntegrityError, match="no authoritative snapshot"):
            load_term_dataset(session,1,schedule_id=1)
    with pytest.raises(IntegrityError, match="Legacy official"):
        with factory.begin() as session: session.get(m.Room,1).capacity = 1
    engine.dispose()


def test_review_does_not_publish_or_grant_publication_permission(env):
    client, factory, _, _ = env
    # B008 replaces the former endpoint-absence placeholder. Independent review
    # must still leave the version Generated and must never authorize its caller.
    freeze(factory,1)
    with factory() as session:
        original=session.get(m.ScheduleSnapshot,1).inputs_json
        assert session.get(m.Schedule,1).status=='Generated'
    assert client.post("/schedules/1/publish").status_code == 403  # Coordinator, not Approver.
    with factory() as session:
        sch=session.get(m.Schedule,1)
        assert sch.status=='Generated' and sch.approved_by is None and sch.published_at is None
        assert session.get(m.ScheduleSnapshot,1).inputs_json==original


@pytest.mark.parametrize("schedule_id,table,pk", [(1,"timetable_entries","entry_id"),(2,"exam_entries","exam_entry_id")])
def test_entry_changes_invalidate_publication_review(env, schedule_id, table, pk):
    _, factory, _, _ = env
    freeze(factory, schedule_id)
    with factory.begin() as session:
        session.execute(text(f"UPDATE {table} SET is_locked=1 WHERE {pk}=1"))
        assert session.get(m.ScheduleValidationReceipt, schedule_id) is None
    with pytest.raises(IntegrityError, match="fresh review"):
        with factory.begin() as session:
            session.execute(text("UPDATE schedules SET status='Published', approved_by=3,published_at=CURRENT_TIMESTAMP WHERE schedule_id=:id"), {"id":schedule_id})
    # A fresh independent review permits the legitimate transition.
    with factory.begin() as session:
        sch = session.get(m.Schedule,schedule_id)
        sch.status,sch.approved_by,sch.published_at = "Published",3,datetime(2026,11,21)
    assert load(factory,schedule_id).schedules[0].status == "Published"


@pytest.mark.parametrize("mode", ["invalid_json", "checksum", "semantic", "semantic_generated"])
def test_corrupt_persisted_snapshot_fails_closed_in_api(env, mode):
    client, factory, engine, _ = env
    freeze(factory,1,mode != "semantic_generated")
    with factory() as session:
        row = session.get(m.ScheduleSnapshot,1)
        data = json.loads(row.inputs_json)
        next(room for room in data["dataset"]["rooms"] if room["room_id"] == 1)["capacity"] = 1
        payload = "broken" if mode == "invalid_json" else canonical(data)
        checksum = digest(data) if mode.startswith("semantic") else row.input_hash
    # Fault injection is limited to this disposable database, not a mock validator.
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TRIGGER b004_snapshot_update")
        conn.execute(text("UPDATE schedule_snapshots SET inputs_json=:data,input_hash=:hash WHERE schedule_id=1"), {"data":payload,"hash":checksum})
    response = client.get("/schedules/1/entries")
    assert response.status_code == 409, response.text


def test_exam_enrollment_changes_between_solve_and_save_are_stale(env):
    from engine.exam_scheduler import schedule_exams
    _, factory, _, _ = env
    adapter = TermScheduleAdapter(factory)
    dataset = adapter.load_term(1,include_existing_schedules=False)
    result = schedule_exams(dataset,config_id=2,term_id=1,time_limit_s=10)
    assert result.status in {"optimal","feasible"}
    with factory.begin() as session: mutate(session,"exam_enrollments")
    with pytest.raises(SnapshotIntegrityError,match="changed during generation"):
        adapter.save_result(result,term_id=1,config_id=2,generated_by=1)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.Schedule)) == 2
        assert session.scalar(select(func.count()).select_from(m.ScheduleSnapshot)) == 0


def test_worker_rejects_actual_result_when_source_changes_during_solve(env):
    client, factory, engine, _ = env
    # A real database mutation after input capture crosses the new process boundary.
    # No solver is mocked; the child computes with the captured capacity of 50.
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TRIGGER test_mutate_during_generation AFTER UPDATE OF phase ON generation_runs WHEN NEW.phase='Solving' AND OLD.phase<>'Solving' BEGIN UPDATE rooms SET capacity=49 WHERE room_id=1; END")
    response = client.post("/schedules/generate",json=dict(term_id=1,config_id=1,solver_time_limit_s=10))
    assert response.status_code == 202
    sid = response.json()["schedule_id"]
    with factory() as session:
        assert session.get(m.Schedule,sid).status == "Infeasible"
        assert session.get(m.ScheduleSnapshot,sid) is None
        assert session.scalar(select(func.count()).select_from(m.TimetableEntry).where(m.TimetableEntry.schedule_id==sid)) == 0
        assert "changed during generation" in session.scalar(select(m.ConflictLog.description).where(m.ConflictLog.schedule_id==sid))


def test_failed_migration_is_atomic_in_disposable_sqlite(tmp_path):
    engine = create_db_engine(f"sqlite:///{(tmp_path/'atomic_migration.sqlite').as_posix()}")
    tables = [t for t in m.Base.metadata.sorted_tables if t.name not in {"schedule_snapshots","schedule_input_state","schedule_validation_receipts","generation_runs", "import_stages", "schedule_edit_revisions"}]
    m.Base.metadata.create_all(engine,tables=tables)
    script = (ROOT/"db/migrations/002_schedule_snapshots.sqlite.sql").read_text().replace("COMMIT;","THIS IS AN INJECTED SYNTAX ERROR;\nCOMMIT;")
    raw = engine.raw_connection()
    try:
        import sqlite3
        with pytest.raises(sqlite3.Error): raw.driver_connection.executescript(script)
        raw.driver_connection.rollback()
    finally: raw.close()
    with engine.connect() as conn:
        names = set(conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").scalars())
        assert "schedules" in names
        assert not names & {"schedule_snapshots","schedule_input_state","schedule_validation_receipts"}
    engine.dispose()


def test_subminute_clock_change_cannot_evade_input_hash(env):
    _, factory, _, _ = env
    adapter = TermScheduleAdapter(factory)
    dataset = adapter.load_term(1,include_existing_schedules=False)
    result = solve_timetable(dataset,term_id=1,config_id=1,time_limit_s=10)
    assert result.is_feasible
    with factory.begin() as session: session.get(m.TimeSlot,1).start_time = time(8,0,30)
    with pytest.raises(SnapshotIntegrityError,match="changed during generation"):
        adapter.save_result(result,term_id=1,config_id=1,generated_by=1)
    with factory() as session:
        current = load_term_dataset(session,1,config_id=1,include_existing_schedules=False)
    assert any(v.rule_code == "C-6" for v in TimetableValidator().validate(current,config_id=1))


@pytest.mark.parametrize("schedule_id", [1,2])
def test_manual_move_cannot_add_resources_to_frozen_context(env,schedule_id):
    client,factory,_,_ = env
    freeze(factory,schedule_id)
    new_room = client.post("/rooms",json=dict(room_code="NEW-B004",building="A",capacity=100,room_type="Lecture"))
    assert new_room.status_code == 201
    room_id = new_room.json()["room_id"]
    response = client.put(f"/schedules/{schedule_id}/entries/1",json=dict(room_id=room_id))
    assert response.status_code == 409
    dataset = load(factory,schedule_id)
    assert room_id not in dataset.rooms_by_id


def test_publication_review_refreshes_cached_entries_after_another_writer(env):
    _,factory,_,_ = env
    freeze(factory,1)
    with factory() as session:
        cached = session.get(m.TimetableEntry,1)
        assert cached.room_id == 1
        with factory.begin() as writer:
            writer.get(m.TimetableEntry,1).room_id = 3
        # Snapshot room 3 has 30 seats; this offering requires 45. The old cached
        # room 1 must not allow a fresh receipt to bless the other writer's move.
        frozen = json.loads(session.get(m.ScheduleSnapshot,1).inputs_json)["dataset"]
        assert next(room for room in frozen["rooms"] if room["room_id"] == 3)["capacity"] == 30
        assert next(off for off in frozen["course_offerings"] if off["offering_id"] == 1)["enrolled_count"] == 45
        with pytest.raises(SnapshotIntegrityError,match="H04"):
            publication_eligibility(session,1)
        assert cached.room_id == 3
