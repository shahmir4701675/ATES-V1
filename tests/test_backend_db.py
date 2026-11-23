"""Unit and integration tests for Milestone 5a (`backend/` package).

Uses local SQLite (`sqlite:///:memory:` and temporary SQLite files) exclusively;
never connects to the remote Supabase PostgreSQL database.

Verifies:
- All 21 SQLAlchemy ORM models in `backend/models.py` match `db/schema.sql` (`DB-1`–`DB-9`).
- Database connection configuration (`DATABASE_URL` from `.env`, `.env.example`, `.gitignore`,
  `SEC-8`, and no Supabase client library or API keys).
- `backend/seed.py` loads the seed dataset including student users and enrollments.
- `backend/adapter.py` loads a term from SQLite into `engine.models.TimetableDataset`, runs
  `solve_timetable` and `schedule_exams`, and saves results back in a single atomic transaction
  (`DB-6`, `SAF-2`).
"""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
import re

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.adapter import (
    TermScheduleAdapter,
    load_term_dataset,
    save_engine_result,
    save_exam_result,
    save_timetable_result,
)
from backend.database import (
    create_db_engine,
    create_session_factory,
    get_database_url,
    init_db,
    normalize_database_url,
    session_scope,
)
from backend.models import (
    ALL_MODELS,
    AcademicTerm,
    AuditLog,
    Base,
    Batch,
    ConflictLog,
    ConstraintRule,
    Course,
    CourseOffering,
    Department,
    Enrollment,
    ExamEntry,
    ExamRoomAllocation,
    ExamSlot,
    ImportLog,
    Instructor,
    InstructorAvailability,
    Room,
    Schedule,
    SchedulingConfig,
    TimeSlot,
    TimetableEntry,
    User,
)
from backend.seed import main as seed_cli_main, seed_database
from engine.exam_scheduler import ExamScheduleResult, schedule_exams
from engine.models import TimetableEntry as EngineTimetableEntry, Violation
from engine.timetable_solver import TimetableSolveResult, solve_timetable
from engine.validator import ExamValidator, TimetableValidator

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def sqlite_engine():
    """Create an isolated in-memory SQLite engine with all 21 ATES tables and foreign keys enabled."""
    engine = create_db_engine("sqlite:///:memory:")
    init_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def seeded_engine(sqlite_engine):
    """Return an in-memory SQLite engine seeded via `backend.seed.seed_database`."""
    seed_database(sqlite_engine)
    return sqlite_engine


# ============================================================================
# 1. Configuration, .env.example, .gitignore, and Schema Parity Tests
# ============================================================================
def test_env_example_and_gitignore_security_compliance():
    """Verify `.env.example` and `.gitignore` satisfy `SEC-8` without Supabase API keys."""
    gitignore_path = PROJECT_ROOT / ".gitignore"
    env_example_path = PROJECT_ROOT / ".env.example"

    assert gitignore_path.is_file(), ".gitignore must exist"
    assert env_example_path.is_file(), ".env.example must exist"

    gitignore_lines = [
        line.strip()
        for line in gitignore_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert ".env" in gitignore_lines

    env_example_text = env_example_path.read_text(encoding="utf-8")
    assert "DATABASE_URL=" in env_example_text
    assert "SUPABASE_ANON_KEY=" not in env_example_text
    assert "SUPABASE_SERVICE_ROLE_KEY=" not in env_example_text


def test_database_url_loading_and_normalization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify `get_database_url` reads `DATABASE_URL` from `.env` and normalizes schemes."""
    assert (
        normalize_database_url("postgres://user:pass@db.example.supabase.co:5432/postgres")
        == "postgresql+psycopg2://user:pass@db.example.supabase.co:5432/postgres"
    )
    assert (
        normalize_database_url("postgresql://user:pass@db.example.supabase.co:5432/postgres")
        == "postgresql+psycopg2://user:pass@db.example.supabase.co:5432/postgres"
    )

    sqlite_file = tmp_path / "env_test.db"
    env_file = tmp_path / ".env"
    env_file.write_text(f"DATABASE_URL=sqlite:///{sqlite_file.as_posix()}\n", encoding="utf-8")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    resolved = get_database_url(env_file=env_file, override_env=True)
    assert resolved == f"sqlite:///{sqlite_file.as_posix()}"


def test_all_21_models_match_schema_sql():
    """Verify all 21 tables and columns in `backend/models.py` match `db/schema.sql` exactly."""
    schema_sql = (PROJECT_ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    sql_table_names = set(
        re.findall(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+(\w+)\s*\(", schema_sql)
    )
    orm_table_names = set(Base.metadata.tables.keys())

    assert len(sql_table_names) == 21  # Original SRS business schema is preserved.
    migration_sql = (PROJECT_ROOT / "db/migrations/001_auth_sessions.postgresql.sql").read_text(encoding="utf-8")
    sql_table_names.update(re.findall(r"CREATE TABLE\s+(\w+)\s*\(", migration_sql))
    snapshot_sql = (PROJECT_ROOT / "db/migrations/002_schedule_snapshots.postgresql.sql").read_text(encoding="utf-8")
    sql_table_names.update(re.findall(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+(\w+)\s*\(", snapshot_sql))
    run_sql = (PROJECT_ROOT / "db/migrations/003_generation_runs.postgresql.sql").read_text(encoding="utf-8")
    sql_table_names.update(re.findall(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+(\w+)\s*\(", run_sql))
    stage_sql = (PROJECT_ROOT / "db/migrations/004_import_staging.postgresql.sql").read_text(encoding="utf-8")
    sql_table_names.update(re.findall(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+(\w+)\s*\(", stage_sql))
    edit_sql = (PROJECT_ROOT / "db/migrations/005_adjustment_integrity.postgresql.sql").read_text(encoding="utf-8")
    sql_table_names.update(re.findall(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+(\w+)\s*\(", edit_sql))
    assert len(sql_table_names) == 28
    assert len(ALL_MODELS) == 28
    assert orm_table_names == sql_table_names

    expected_columns: dict[str, set[str]] = {
        "departments": {"department_id", "code", "name"},
        "academic_terms": {"term_id", "name", "start_date", "end_date", "status"},
        "time_slots": {
            "slot_id",
            "term_id",
            "day_of_week",
            "slot_index",
            "start_time",
            "end_time",
            "is_blocked",
            "block_reason",
        },
        "batches": {
            "batch_id",
            "department_id",
            "program_code",
            "batch_year",
            "section",
            "strength",
            "is_active",
        },
        "courses": {
            "course_id",
            "course_code",
            "title",
            "department_id",
            "credit_hours",
            "lecture_hours",
            "lab_hours",
            "is_active",
        },
        "instructors": {
            "instructor_id",
            "department_id",
            "full_name",
            "email",
            "max_daily_hours",
            "max_weekly_hours",
            "is_active",
        },
        "instructor_availability": {
            "availability_id",
            "instructor_id",
            "slot_id",
            "is_available",
        },
        "rooms": {"room_id", "room_code", "building", "capacity", "room_type", "is_active"},
        "users": {
            "user_id",
            "username",
            "password_hash",
            "full_name",
            "email",
            "role",
            "instructor_id",
            "batch_id",
            "account_status",
            "failed_attempts",
            "locked_until",
            "created_at",
        },
        "course_offerings": {
            "offering_id",
            "term_id",
            "course_id",
            "batch_id",
            "instructor_id",
            "enrolled_count",
        },
        "enrollments": {"enrollment_id", "offering_id", "student_id"},
        "scheduling_configs": {
            "config_id",
            "term_id",
            "schedule_type",
            "name",
            "solver_time_limit_s",
            "random_seed",
            "created_by",
            "created_at",
        },
        "constraint_rules": {
            "rule_id",
            "config_id",
            "rule_code",
            "rule_type",
            "is_enabled",
            "weight",
            "param_value",
        },
        "schedules": {
            "schedule_id",
            "term_id",
            "config_id",
            "schedule_type",
            "version_no",
            "status",
            "solver_status",
            "objective_score",
            "run_seconds",
            "generated_by",
            "generated_at",
            "approved_by",
            "published_at",
        },
        "timetable_entries": {
            "entry_id",
            "schedule_id",
            "offering_id",
            "instructor_id",
            "batch_id",
            "room_id",
            "slot_id",
            "session_type",
            "is_locked",
            "is_manual_override",
        },
        "exam_slots": {
            "exam_slot_id",
            "term_id",
            "exam_date",
            "start_time",
            "end_time",
            "label",
        },
        "exam_entries": {
            "exam_entry_id",
            "schedule_id",
            "course_id",
            "exam_slot_id",
            "student_count",
            "is_locked",
            "is_manual_override",
        },
        "exam_room_allocations": {
            "allocation_id",
            "exam_entry_id",
            "room_id",
            "seats_allocated",
        },
        "conflict_log": {
            "conflict_id",
            "schedule_id",
            "conflict_type",
            "severity",
            "description",
            "entity_ref",
            "detected_at",
            "is_resolved",
        },
        "import_logs": {
            "import_id",
            "user_id",
            "entity_type",
            "file_name",
            "rows_total",
            "rows_imported",
            "rows_rejected",
            "imported_at",
        },
        "audit_logs": {
            "log_id",
            "user_id",
            "action",
            "entity_type",
            "entity_id",
            "details",
            "created_at",
        },
    }

    for table_name, cols in expected_columns.items():
        actual_cols = {c.name for c in Base.metadata.tables[table_name].columns}
        assert actual_cols == cols, f"Column mismatch on table {table_name}"
    assert set(Base.metadata.tables["auth_sessions"].columns.keys()) == {
        "auth_session_id", "token_id", "user_id", "credential_fingerprint",
        "created_at", "last_seen_at", "expires_at",
    }


# ============================================================================
# 2. Seed Script Tests (including Student Users and Enrollments)
# ============================================================================
def test_seed_database_loads_master_data_students_and_enrollments(seeded_engine):
    """Verify `seed_database` populates all tables including student users and enrollments."""
    with session_scope(seeded_engine) as session:
        students = session.scalars(
            select(User).where(User.role == "Student").order_by(User.user_id)
        ).all()
        assert len(students) >= 4
        student_ids = {s.user_id for s in students}
        assert 9001 in student_ids
        assert all(s.batch_id is not None for s in students)

        faculty_users = session.scalars(
            select(User).where(User.role == "Faculty").order_by(User.user_id)
        ).all()
        assert len(faculty_users) == 3
        assert {f.instructor_id for f in faculty_users} == {1, 2, 3}

        enrollments = session.scalars(
            select(Enrollment).order_by(Enrollment.enrollment_id)
        ).all()
        assert len(enrollments) >= 11
        repeater_offerings = {
            e.offering_id for e in enrollments if e.student_id == 9001
        }
        assert repeater_offerings == {2, 5}

    # Verify idempotency when running seed_database a second time
    counts_second_run = seed_database(seeded_engine)
    assert counts_second_run["departments"] == 1
    assert counts_second_run["academic_terms"] == 1
    assert counts_second_run["courses"] == 5
    assert counts_second_run["rooms"] == 6
    assert counts_second_run["course_offerings"] == 6
    assert counts_second_run["users"] == 10
    assert counts_second_run["enrollments"] == 11


def test_seed_cli_entrypoint_with_local_sqlite(tmp_path: Path):
    """Verify `python -m backend.seed --database-url sqlite:///...` works end-to-end."""
    db_file = tmp_path / "cli_seed.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    exit_code = seed_cli_main(["--database-url", db_url])
    assert exit_code == 0
    assert db_file.is_file()


# ============================================================================
# 3. Database Integrity & Schema Constraint Enforcement Tests (DB-2, DB-3, DB-4)
# ============================================================================
def test_db2_composite_foreign_key_and_db4_clash_constraints(seeded_engine):
    """Verify `DB-2` composite FK `(offering_id, instructor_id, batch_id)` and `DB-4` unique indexes."""
    # DB-2: Offering 1 belongs to instructor_id=1 and batch_id=1; passing instructor_id=2 must fail
    with pytest.raises(IntegrityError):
        with session_scope(seeded_engine) as session:
            session.add(
                TimetableEntry(
                    schedule_id=1,
                    offering_id=1,
                    instructor_id=2,  # Mismatched instructor for offering_id=1
                    batch_id=1,
                    room_id=3,
                    slot_id=30,
                    session_type="Lecture",
                )
            )

    # DB-4: Duplicate (schedule_id=1, room_id=1, slot_id=1) must fail at DB level
    with pytest.raises(IntegrityError):
        with session_scope(seeded_engine) as session:
            session.add(
                TimetableEntry(
                    schedule_id=1,
                    offering_id=2,
                    instructor_id=2,
                    batch_id=1,
                    room_id=1,  # Already occupied at slot_id=1 in schedule_id=1
                    slot_id=1,
                    session_type="Lecture",
                )
            )


def test_db3_restrict_master_delete_and_cascade_schedule_delete(seeded_engine):
    """Verify `DB-3` `ON DELETE RESTRICT` on master records and `ON DELETE CASCADE` on schedules."""
    # Deleting a referenced department or room must be restricted
    with pytest.raises(IntegrityError):
        with session_scope(seeded_engine) as session:
            dept = session.get(Department, 1)
            session.delete(dept)

    with pytest.raises(IntegrityError):
        with session_scope(seeded_engine) as session:
            room = session.get(Room, 1)
            session.delete(room)

    # Deleting a schedule must cascade-delete its child timetable_entries and conflict_log rows
    with session_scope(seeded_engine) as session:
        session.add(
            ConflictLog(
                schedule_id=1,
                conflict_type="SoftWarning",
                severity="Warning",
                description="Test warning attached to schedule 1",
                entity_ref="schedule_id=1",
            )
        )

    with session_scope(seeded_engine) as session:
        sch = session.get(Schedule, 1)
        assert sch is not None
        session.delete(sch)

    with session_scope(seeded_engine) as session:
        remaining_entries = session.scalars(
            select(TimetableEntry).where(TimetableEntry.schedule_id == 1)
        ).all()
        remaining_conflicts = session.scalars(
            select(ConflictLog).where(ConflictLog.schedule_id == 1)
        ).all()
        assert remaining_entries == []
        assert remaining_conflicts == []


def test_partial_unique_indexes_and_check_constraints(seeded_engine):
    """Verify partial unique indexes (single Active term, single Published schedule) and check rules."""
    # Only one Active term allowed at a time (`uq_academic_terms_single_active`)
    with pytest.raises(IntegrityError):
        with session_scope(seeded_engine) as session:
            session.add(
                AcademicTerm(
                    name="Spring 2027",
                    start_date=date(2027, 1, 15),
                    end_date=date(2027, 5, 30),
                    status="Active",
                )
            )

    # Multiple 'Planned' terms are allowed
    with session_scope(seeded_engine) as session:
        session.add(
            AcademicTerm(
                name="Spring 2027",
                start_date=date(2027, 1, 15),
                end_date=date(2027, 5, 30),
                status="Planned",
            )
        )
        session.add(
            AcademicTerm(
                name="Fall 2027",
                start_date=date(2027, 9, 1),
                end_date=date(2027, 12, 31),
                status="Planned",
            )
        )

    # Mandatory constraint rule H01 cannot be disabled (`ck_constraint_rules_mandatory_enabled`)
    with pytest.raises(IntegrityError):
        with session_scope(seeded_engine) as session:
            rule_h01 = session.scalar(
                select(ConstraintRule).where(
                    ConstraintRule.config_id == 1,
                    ConstraintRule.rule_code == "H01",
                )
            )
            assert rule_h01 is not None
            rule_h01.is_enabled = False

    # ImportLog check constraint (`rows_imported + rows_rejected <= rows_total`)
    with pytest.raises(IntegrityError):
        with session_scope(seeded_engine) as session:
            session.add(
                ImportLog(
                    user_id=1,
                    entity_type="courses",
                    file_name="courses.csv",
                    rows_total=5,
                    rows_imported=4,
                    rows_rejected=2,
                )
            )


# ============================================================================
# 4. Adapter Round-Trip Tests (Load Term -> Solve -> Save in One Transaction)
# ============================================================================
def test_adapter_loads_term_and_validates_seeded_schedules(seeded_engine):
    """Verify `load_term_dataset` loads `term_id=1` into `TimetableDataset` with zero violations."""
    adapter = TermScheduleAdapter(seeded_engine)
    dataset = adapter.load_term(term_id=1)

    assert len(dataset.departments) == 1
    assert len(dataset.academic_terms) == 1
    assert len(dataset.time_slots) == 30
    assert len(dataset.batches) == 2
    assert len(dataset.courses) == 5
    assert len(dataset.instructors) == 3
    assert len(dataset.rooms) == 6
    assert len(dataset.course_offerings) == 6
    assert len(dataset.enrollments) == 11
    assert len(dataset.exam_slots) == 6

    tt_validator = TimetableValidator()
    tt_violations = tt_validator.validate(dataset, config_id=1)
    assert tt_violations == []

    exam_validator = ExamValidator()
    exam_violations = exam_validator.validate(dataset, config_id=2)
    assert exam_violations == []


def test_adapter_solves_and_saves_timetable_and_exam_results_in_one_transaction(seeded_engine):
    """Verify `TermScheduleAdapter` loads a term, runs both solvers, and persists new versions."""
    adapter = TermScheduleAdapter(seeded_engine)
    dataset = adapter.load_term(term_id=1, include_existing_schedules=False)

    # 1. Solve weekly timetable and save result in one transaction
    tt_result = solve_timetable(dataset, term_id=1, config_id=1, time_limit_s=30.0, random_seed=1)
    assert tt_result.solver_status in ("optimal", "feasible")
    assert tt_result.violations == []

    saved_tt_schedule = adapter.save_result(
        tt_result,
        term_id=1,
        config_id=1,
        generated_by=1,
    )
    assert saved_tt_schedule.schedule_type == "Timetable"
    assert saved_tt_schedule.version_no == 2
    assert saved_tt_schedule.status == "Generated"
    assert saved_tt_schedule.solver_status == tt_result.solver_status

    # 2. Solve examination schedule and save result in one transaction
    exam_result = schedule_exams(dataset, term_id=1, config_id=2, time_limit_s=30.0, random_seed=1)
    assert exam_result.status in ("optimal", "feasible")
    assert exam_result.violations == []

    saved_exam_schedule = adapter.save_result(
        exam_result,
        term_id=1,
        config_id=2,
        generated_by=1,
    )
    assert saved_exam_schedule.schedule_type == "Exam"
    assert saved_exam_schedule.version_no == 2
    assert saved_exam_schedule.status == "Generated"
    assert saved_exam_schedule.solver_status == exam_result.status

    # 3. Reload from DB and verify both newly saved schedules validate cleanly
    reloaded_tt = adapter.load_term(
        term_id=1,
        config_id=1,
        schedule_id=saved_tt_schedule.schedule_id,
    )
    assert len(reloaded_tt.timetable_entries) == 26
    assert (
        TimetableValidator().validate(
            reloaded_tt,
            config_id=1,
        )
        == []
    )

    reloaded_exam = adapter.load_term(
        term_id=1,
        config_id=2,
        schedule_id=saved_exam_schedule.schedule_id,
    )
    assert len(reloaded_exam.exam_entries) == 5
    assert (
        ExamValidator().validate(
            reloaded_exam,
            config_id=2,
        )
        == []
    )


def test_adapter_saves_infeasible_results_and_logs_conflicts_without_harming_existing_schedules(
    seeded_engine,
):
    """Verify infeasible runs write `status='Infeasible'` and `conflict_log` rows while preserving v1."""
    infeasible_tt = TimetableSolveResult(
        schedule=[],
        solver_status="infeasible",
        run_time=0.42,
        reasons=["H04: Offering CS-326 (enrolled=85) exceeds maximum room capacity (50)."],
        violations=[
            Violation(
                rule_code="H04",
                conflict_type="RoomCapacity",
                severity="Hard",
                description="Offering CS-326 exceeds room capacity.",
                entity_ref="offering_id=1",
            )
        ],
    )
    saved_inf = save_timetable_result(
        seeded_engine,
        infeasible_tt,
        term_id=1,
        config_id=1,
        generated_by=1,
    )
    assert saved_inf.status == "Infeasible"
    assert saved_inf.solver_status == "infeasible"
    assert saved_inf.version_no == 2

    with session_scope(seeded_engine) as session:
        # Existing v1 schedule and its 26 entries remain completely intact (SAF-2)
        v1 = session.get(Schedule, 1)
        assert v1 is not None and v1.status == "Generated"
        v1_entry_count = session.scalar(
            select(func.count(TimetableEntry.entry_id)).where(
                TimetableEntry.schedule_id == 1
            )
        )
        assert v1_entry_count == 26

        # Infeasible v2 has 0 timetable entries and 2 conflict_log rows
        v2_conflicts = session.scalars(
            select(ConflictLog).where(ConflictLog.schedule_id == saved_inf.schedule_id)
        ).all()
        assert len(v2_conflicts) == 2


def test_saf2_and_db6_atomic_rollback_on_save_failure(seeded_engine):
    """Verify `DB-6` and `SAF-2`: any error during `save_timetable_result` rolls back the entire run."""
    session_factory = create_session_factory(seeded_engine)

    with session_scope(session_factory) as session:
        initial_schedules = session.scalar(select(func.count(Schedule.schedule_id)))
        initial_entries = session.scalar(select(func.count(TimetableEntry.entry_id)))
        initial_audits = session.scalar(select(func.count(AuditLog.log_id)))

    # Construct a result where the second entry violates DB-2 composite FK (offering 1 with instructor 999)
    corrupted_result = TimetableSolveResult(
        schedule=[
            EngineTimetableEntry(
                entry_id=1,
                schedule_id=99,
                offering_id=1,
                instructor_id=1,
                batch_id=1,
                room_id=1,
                slot_id=1,
                session_type="Lecture",
            ),
            EngineTimetableEntry(
                entry_id=2,
                schedule_id=99,
                offering_id=1,
                instructor_id=2,  # Violates fk_timetable_entries_offering_triplet (DB-2)
                batch_id=1,
                room_id=2,
                slot_id=2,
                session_type="Lecture",
            ),
        ],
        solver_status="optimal",
        run_time=0.5,
    )

    with pytest.raises(IntegrityError):
        save_timetable_result(
            session_factory,
            corrupted_result,
            term_id=1,
            config_id=1,
            generated_by=1,
        )

    # Verify complete atomic rollback: no new Schedule, no new TimetableEntry, no new AuditLog
    with session_scope(session_factory) as session:
        assert session.scalar(select(func.count(Schedule.schedule_id))) == initial_schedules
        assert session.scalar(select(func.count(TimetableEntry.entry_id))) == initial_entries
        assert session.scalar(select(func.count(AuditLog.log_id))) == initial_audits
