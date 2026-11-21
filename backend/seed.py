"""Database seeding script for ATES (Milestone 5a: Section 3.1.4, `DB-3`, `DB-6`, `DB-7`).

Loads the seed dataset (`data/seed_timetable.json` and `data/seed_exam.json`),
including authenticated users across all 5 RBAC roles (`Administrator`, `Coordinator`,
`Approver`, `Faculty`, and `Student`), student enrollments, master data, offerings,
scheduling configurations, constraint rules, and baseline timetable/exam schedules
into the database inside a single transaction.

Can be invoked programmatically via `seed_database(session_or_engine)` or from the CLI:
    python -m backend.seed
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timezone
from decimal import Decimal
import json
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.database import create_db_engine, init_db, session_scope
from backend.models import (
    AcademicTerm,
    AuditLog,
    Batch,
    ConstraintRule,
    Course,
    CourseOffering,
    Department,
    Enrollment,
    ExamEntry,
    ExamRoomAllocation,
    ExamSlot,
    Instructor,
    InstructorAvailability,
    Room,
    Schedule,
    SchedulingConfig,
    TimeSlot,
    TimetableEntry,
    User,
)

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DEFAULT_TIMETABLE_SEED_PATH: Path = PROJECT_ROOT / "data" / "seed_timetable.json"
DEFAULT_EXAM_SEED_PATH: Path = PROJECT_ROOT / "data" / "seed_exam.json"

# Precomputed bcrypt hash (cost factor 12 per SEC-2 / DB-7) for seed accounts
SEED_PASSWORD_HASH: str = "$2b$12$KIX9r3T1qW8vZ0xL5pM2uO7yH4jN6bV8cX1zA3sD5fG7hJ9kL1mN2"

DEFAULT_SEED_USERS: tuple[dict[str, Any], ...] = (
    {
        "user_id": 1,
        "username": "coordinator",
        "password_hash": SEED_PASSWORD_HASH,
        "full_name": "Timetable Coordinator",
        "email": "coordinator@neduet.edu.pk",
        "role": "Coordinator",
        "instructor_id": None,
        "batch_id": None,
        "account_status": "Active",
    },
    {
        "user_id": 2,
        "username": "admin",
        "password_hash": SEED_PASSWORD_HASH,
        "full_name": "System Administrator",
        "email": "admin@neduet.edu.pk",
        "role": "Administrator",
        "instructor_id": None,
        "batch_id": None,
        "account_status": "Active",
    },
    {
        "user_id": 3,
        "username": "approver",
        "password_hash": SEED_PASSWORD_HASH,
        "full_name": "Department Chair",
        "email": "chair@neduet.edu.pk",
        "role": "Approver",
        "instructor_id": None,
        "batch_id": None,
        "account_status": "Active",
    },
    {
        "user_id": 101,
        "username": "fakhra",
        "password_hash": SEED_PASSWORD_HASH,
        "full_name": "Dr. Fakhra Aftab",
        "email": "fakhra@neduet.edu.pk",
        "role": "Faculty",
        "instructor_id": 1,
        "batch_id": None,
        "account_status": "Active",
    },
    {
        "user_id": 102,
        "username": "aliraza",
        "password_hash": SEED_PASSWORD_HASH,
        "full_name": "Dr. Ali Raza",
        "email": "aliraza@neduet.edu.pk",
        "role": "Faculty",
        "instructor_id": 2,
        "batch_id": None,
        "account_status": "Active",
    },
    {
        "user_id": 103,
        "username": "sarakhan",
        "password_hash": SEED_PASSWORD_HASH,
        "full_name": "Prof. Sara Khan",
        "email": "sarakhan@neduet.edu.pk",
        "role": "Faculty",
        "instructor_id": 3,
        "batch_id": None,
        "account_status": "Active",
    },
    {
        "user_id": 9001,
        "username": "cs24b_9001",
        "password_hash": SEED_PASSWORD_HASH,
        "full_name": "Hamza Siddiqui",
        "email": "cs24b_9001@cloud.neduet.edu.pk",
        "role": "Student",
        "instructor_id": None,
        "batch_id": 2,
        "account_status": "Active",
    },
    {
        "user_id": 9002,
        "username": "cs24a_9002",
        "password_hash": SEED_PASSWORD_HASH,
        "full_name": "Ayesha Tariq",
        "email": "cs24a_9002@cloud.neduet.edu.pk",
        "role": "Student",
        "instructor_id": None,
        "batch_id": 1,
        "account_status": "Active",
    },
    {
        "user_id": 9003,
        "username": "cs24a_9003",
        "password_hash": SEED_PASSWORD_HASH,
        "full_name": "Bilal Ahmed",
        "email": "cs24a_9003@cloud.neduet.edu.pk",
        "role": "Student",
        "instructor_id": None,
        "batch_id": 1,
        "account_status": "Active",
    },
    {
        "user_id": 9004,
        "username": "cs24b_9004",
        "password_hash": SEED_PASSWORD_HASH,
        "full_name": "Zainab Fatima",
        "email": "cs24b_9004@cloud.neduet.edu.pk",
        "role": "Student",
        "instructor_id": None,
        "batch_id": 2,
        "account_status": "Active",
    },
)

DEFAULT_ADDITIONAL_ENROLLMENTS: tuple[dict[str, int], ...] = (
    {"enrollment_id": 3, "offering_id": 1, "student_id": 9002},
    {"enrollment_id": 4, "offering_id": 2, "student_id": 9002},
    {"enrollment_id": 5, "offering_id": 3, "student_id": 9002},
    {"enrollment_id": 6, "offering_id": 1, "student_id": 9003},
    {"enrollment_id": 7, "offering_id": 2, "student_id": 9003},
    {"enrollment_id": 8, "offering_id": 3, "student_id": 9003},
    {"enrollment_id": 9, "offering_id": 4, "student_id": 9004},
    {"enrollment_id": 10, "offering_id": 5, "student_id": 9004},
    {"enrollment_id": 11, "offering_id": 6, "student_id": 9004},
)

# Conflict-free timetable entries for offerings 5 and 6 when both timetable and exam seeds are merged
EXTRA_MERGED_TIMETABLE_ENTRIES: tuple[dict[str, Any], ...] = (
    {
        "entry_id": 19,
        "schedule_id": 1,
        "offering_id": 5,
        "instructor_id": 2,
        "batch_id": 2,
        "room_id": 2,
        "slot_id": 1,
        "session_type": "Lecture",
        "is_locked": False,
        "is_manual_override": False,
    },
    {
        "entry_id": 20,
        "schedule_id": 1,
        "offering_id": 5,
        "instructor_id": 2,
        "batch_id": 2,
        "room_id": 1,
        "slot_id": 7,
        "session_type": "Lecture",
        "is_locked": False,
        "is_manual_override": False,
    },
    {
        "entry_id": 21,
        "schedule_id": 1,
        "offering_id": 5,
        "instructor_id": 2,
        "batch_id": 2,
        "room_id": 2,
        "slot_id": 13,
        "session_type": "Lecture",
        "is_locked": False,
        "is_manual_override": False,
    },
    {
        "entry_id": 22,
        "schedule_id": 1,
        "offering_id": 5,
        "instructor_id": 2,
        "batch_id": 2,
        "room_id": 4,
        "slot_id": 8,
        "session_type": "Lab",
        "is_locked": False,
        "is_manual_override": False,
    },
    {
        "entry_id": 23,
        "schedule_id": 1,
        "offering_id": 5,
        "instructor_id": 2,
        "batch_id": 2,
        "room_id": 4,
        "slot_id": 9,
        "session_type": "Lab",
        "is_locked": False,
        "is_manual_override": False,
    },
    {
        "entry_id": 24,
        "schedule_id": 1,
        "offering_id": 6,
        "instructor_id": 3,
        "batch_id": 2,
        "room_id": 2,
        "slot_id": 4,
        "session_type": "Lecture",
        "is_locked": False,
        "is_manual_override": False,
    },
    {
        "entry_id": 25,
        "schedule_id": 1,
        "offering_id": 6,
        "instructor_id": 3,
        "batch_id": 2,
        "room_id": 2,
        "slot_id": 10,
        "session_type": "Lecture",
        "is_locked": False,
        "is_manual_override": False,
    },
    {
        "entry_id": 26,
        "schedule_id": 1,
        "offering_id": 6,
        "instructor_id": 3,
        "batch_id": 2,
        "room_id": 2,
        "slot_id": 15,
        "session_type": "Lecture",
        "is_locked": False,
        "is_manual_override": False,
    },
)


def _parse_date(val: str | date) -> date:
    if isinstance(val, date):
        return val
    return date.fromisoformat(str(val).strip())


def _parse_time(val: str | time) -> time:
    if isinstance(val, time):
        return val
    parts = [int(p) for p in str(val).strip().split(":")]
    if len(parts) == 2:
        return time(parts[0], parts[1])
    return time(parts[0], parts[1], parts[2])


def _parse_datetime(val: str | datetime | None) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.astimezone(timezone.utc).replace(tzinfo=None) if val.tzinfo else val
    cleaned = str(val).strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _merge_by_key(
    primary: list[dict[str, Any]],
    secondary: list[dict[str, Any]],
    key: str,
) -> list[dict[str, Any]]:
    """Merge two lists of dictionaries by primary key, preserving order."""
    merged: dict[Any, dict[str, Any]] = {}
    for item in primary:
        merged[item[key]] = dict(item)
    for item in secondary:
        if item[key] not in merged:
            merged[item[key]] = dict(item)
    return list(merged.values())


def build_combined_seed_payload(
    timetable_seed_path: str | Path = DEFAULT_TIMETABLE_SEED_PATH,
    exam_seed_path: str | Path | None = DEFAULT_EXAM_SEED_PATH,
) -> dict[str, list[dict[str, Any]]]:
    """Load and merge `seed_timetable.json` and `seed_exam.json` with seed users & enrollments."""
    with Path(timetable_seed_path).open("r", encoding="utf-8") as f:
        tt_data: dict[str, Any] = json.load(f)

    ex_data: dict[str, Any] = {}
    if exam_seed_path is not None and Path(exam_seed_path).is_file():
        with Path(exam_seed_path).open("r", encoding="utf-8") as f:
            ex_data = json.load(f)

    offerings = _merge_by_key(
        tt_data.get("course_offerings", []),
        ex_data.get("course_offerings", []),
        "offering_id",
    )
    offering_ids = {o["offering_id"] for o in offerings}

    timetable_entries = list(tt_data.get("timetable_entries", []))
    if {5, 6}.issubset(offering_ids):
        timetable_entries = _merge_by_key(
            timetable_entries,
            list(EXTRA_MERGED_TIMETABLE_ENTRIES),
            "entry_id",
        )

    raw_enrollments = _merge_by_key(
        tt_data.get("enrollments", []),
        ex_data.get("enrollments", []),
        "enrollment_id",
    )
    all_enrollments = _merge_by_key(
        raw_enrollments,
        [e for e in DEFAULT_ADDITIONAL_ENROLLMENTS if e["offering_id"] in offering_ids],
        "enrollment_id",
    )

    return {
        "departments": _merge_by_key(
            tt_data.get("departments", []),
            ex_data.get("departments", []),
            "department_id",
        ),
        "academic_terms": _merge_by_key(
            tt_data.get("academic_terms", []),
            ex_data.get("academic_terms", []),
            "term_id",
        ),
        "time_slots": _merge_by_key(
            tt_data.get("time_slots", []),
            ex_data.get("time_slots", []),
            "slot_id",
        ),
        "batches": _merge_by_key(
            tt_data.get("batches", []),
            ex_data.get("batches", []),
            "batch_id",
        ),
        "courses": _merge_by_key(
            tt_data.get("courses", []),
            ex_data.get("courses", []),
            "course_id",
        ),
        "instructors": _merge_by_key(
            tt_data.get("instructors", []),
            ex_data.get("instructors", []),
            "instructor_id",
        ),
        "instructor_availability": _merge_by_key(
            tt_data.get("instructor_availability", []),
            ex_data.get("instructor_availability", []),
            "availability_id",
        ),
        "rooms": _merge_by_key(
            tt_data.get("rooms", []),
            ex_data.get("rooms", []),
            "room_id",
        ),
        "users": list(DEFAULT_SEED_USERS),
        "course_offerings": offerings,
        "enrollments": all_enrollments,
        "scheduling_configs": _merge_by_key(
            tt_data.get("scheduling_configs", []),
            ex_data.get("scheduling_configs", []),
            "config_id",
        ),
        "constraint_rules": _merge_by_key(
            tt_data.get("constraint_rules", []),
            ex_data.get("constraint_rules", []),
            "rule_id",
        ),
        "schedules": _merge_by_key(
            tt_data.get("schedules", []),
            ex_data.get("schedules", []),
            "schedule_id",
        ),
        "timetable_entries": timetable_entries,
        "exam_slots": _merge_by_key(
            tt_data.get("exam_slots", []),
            ex_data.get("exam_slots", []),
            "exam_slot_id",
        ),
        "exam_entries": _merge_by_key(
            tt_data.get("exam_entries", []),
            ex_data.get("exam_entries", []),
            "exam_entry_id",
        ),
        "exam_room_allocations": _merge_by_key(
            tt_data.get("exam_room_allocations", []),
            ex_data.get("exam_room_allocations", []),
            "allocation_id",
        ),
    }


def seed_database(
    session_or_factory: Session | sessionmaker[Session] | Engine,
    *,
    timetable_seed_path: str | Path = DEFAULT_TIMETABLE_SEED_PATH,
    exam_seed_path: str | Path | None = DEFAULT_EXAM_SEED_PATH,
    create_tables: bool = True,
) -> dict[str, int]:
    """Seed the database with master data, users (including students), enrollments, and schedules.

    Executes idempotently inside a single database transaction (`DB-6`, `SAF-2`).

    Returns:
        Dictionary mapping table names to the number of rows present after seeding.
    """
    if isinstance(session_or_factory, Engine) and create_tables:
        init_db(session_or_factory)
    elif isinstance(session_or_factory, sessionmaker) and create_tables:
        bound = session_or_factory.kw.get("bind")
        if isinstance(bound, Engine):
            init_db(bound)
    elif isinstance(session_or_factory, Session) and create_tables:
        bind = session_or_factory.get_bind()
        if isinstance(bind, Engine):
            init_db(bind)

    payload = build_combined_seed_payload(
        timetable_seed_path=timetable_seed_path,
        exam_seed_path=exam_seed_path,
    )

    with session_scope(session_or_factory) as session:
        for d in payload["departments"]:
            session.merge(
                Department(
                    department_id=d["department_id"],
                    code=d["code"],
                    name=d["name"],
                )
            )
        session.flush()

        for t in payload["academic_terms"]:
            session.merge(
                AcademicTerm(
                    term_id=t["term_id"],
                    name=t["name"],
                    start_date=_parse_date(t["start_date"]),
                    end_date=_parse_date(t["end_date"]),
                    status=t.get("status", "Active"),
                )
            )
        session.flush()

        for s in payload["time_slots"]:
            session.merge(
                TimeSlot(
                    slot_id=s["slot_id"],
                    term_id=s["term_id"],
                    day_of_week=s["day_of_week"],
                    slot_index=s["slot_index"],
                    start_time=_parse_time(s["start_time"]),
                    end_time=_parse_time(s["end_time"]),
                    is_blocked=bool(s.get("is_blocked", False)),
                    block_reason=s.get("block_reason"),
                )
            )
        session.flush()

        for b in payload["batches"]:
            session.merge(
                Batch(
                    batch_id=b["batch_id"],
                    department_id=b["department_id"],
                    program_code=b["program_code"],
                    batch_year=b["batch_year"],
                    section=b["section"],
                    strength=b["strength"],
                    is_active=bool(b.get("is_active", True)),
                )
            )
        session.flush()

        for c in payload["courses"]:
            session.merge(
                Course(
                    course_id=c["course_id"],
                    course_code=c["course_code"],
                    title=c["title"],
                    department_id=c["department_id"],
                    credit_hours=c["credit_hours"],
                    lecture_hours=c.get("lecture_hours", 0),
                    lab_hours=c.get("lab_hours", 0),
                    is_active=bool(c.get("is_active", True)),
                )
            )
        session.flush()

        for i in payload["instructors"]:
            session.merge(
                Instructor(
                    instructor_id=i["instructor_id"],
                    department_id=i["department_id"],
                    full_name=i["full_name"],
                    email=i["email"],
                    max_daily_hours=i.get("max_daily_hours", 4),
                    max_weekly_hours=i.get("max_weekly_hours", 18),
                    is_active=bool(i.get("is_active", True)),
                )
            )
        session.flush()

        for a in payload["instructor_availability"]:
            session.merge(
                InstructorAvailability(
                    availability_id=a["availability_id"],
                    instructor_id=a["instructor_id"],
                    slot_id=a["slot_id"],
                    is_available=bool(a.get("is_available", True)),
                )
            )
        session.flush()

        for r in payload["rooms"]:
            session.merge(
                Room(
                    room_id=r["room_id"],
                    room_code=r["room_code"],
                    building=r["building"],
                    capacity=r["capacity"],
                    room_type=r["room_type"],
                    is_active=bool(r.get("is_active", True)),
                )
            )
        session.flush()

        for u in payload["users"]:
            session.merge(
                User(
                    user_id=u["user_id"],
                    username=u["username"],
                    password_hash=u["password_hash"],
                    full_name=u["full_name"],
                    email=u["email"],
                    role=u["role"],
                    instructor_id=u.get("instructor_id"),
                    batch_id=u.get("batch_id"),
                    account_status=u.get("account_status", "Active"),
                    failed_attempts=u.get("failed_attempts", 0),
                    locked_until=_parse_datetime(u.get("locked_until")),
                )
            )
        session.flush()

        for o in payload["course_offerings"]:
            session.merge(
                CourseOffering(
                    offering_id=o["offering_id"],
                    term_id=o["term_id"],
                    course_id=o["course_id"],
                    batch_id=o["batch_id"],
                    instructor_id=o["instructor_id"],
                    enrolled_count=o["enrolled_count"],
                )
            )
        session.flush()

        for enr in payload["enrollments"]:
            session.merge(
                Enrollment(
                    enrollment_id=enr["enrollment_id"],
                    offering_id=enr["offering_id"],
                    student_id=enr["student_id"],
                )
            )
        session.flush()

        for cfg in payload["scheduling_configs"]:
            session.merge(
                SchedulingConfig(
                    config_id=cfg["config_id"],
                    term_id=cfg["term_id"],
                    schedule_type=cfg["schedule_type"],
                    name=cfg["name"],
                    solver_time_limit_s=cfg.get("solver_time_limit_s", 120),
                    random_seed=cfg.get("random_seed", 1),
                    created_by=cfg.get("created_by", 1),
                    created_at=_parse_datetime(cfg.get("created_at"))
                    or datetime(2026, 10, 20, 9, 0, 0),
                )
            )
        session.flush()

        for cr in payload["constraint_rules"]:
            session.merge(
                ConstraintRule(
                    rule_id=cr["rule_id"],
                    config_id=cr["config_id"],
                    rule_code=cr["rule_code"],
                    rule_type=cr["rule_type"],
                    is_enabled=bool(cr.get("is_enabled", True)),
                    weight=cr.get("weight", 0),
                    param_value=cr.get("param_value"),
                )
            )
        session.flush()

        for sch in payload["schedules"]:
            obj_score = sch.get("objective_score")
            run_sec = sch.get("run_seconds")
            session.merge(
                Schedule(
                    schedule_id=sch["schedule_id"],
                    term_id=sch["term_id"],
                    config_id=sch["config_id"],
                    schedule_type=sch["schedule_type"],
                    version_no=sch["version_no"],
                    status=sch.get("status", "Generated"),
                    solver_status=sch.get("solver_status"),
                    objective_score=(
                        Decimal(str(obj_score)).quantize(Decimal("0.01"))
                        if obj_score is not None
                        else None
                    ),
                    run_seconds=(
                        Decimal(str(run_sec)).quantize(Decimal("0.01"))
                        if run_sec is not None
                        else None
                    ),
                    generated_by=sch.get("generated_by", 1),
                    generated_at=_parse_datetime(sch.get("generated_at"))
                    or datetime(2026, 10, 20, 9, 15, 0),
                    approved_by=sch.get("approved_by"),
                    published_at=_parse_datetime(sch.get("published_at")),
                )
            )
        session.flush()

        for te in payload["timetable_entries"]:
            session.merge(
                TimetableEntry(
                    entry_id=te["entry_id"],
                    schedule_id=te["schedule_id"],
                    offering_id=te["offering_id"],
                    instructor_id=te["instructor_id"],
                    batch_id=te["batch_id"],
                    room_id=te["room_id"],
                    slot_id=te["slot_id"],
                    session_type=te["session_type"],
                    is_locked=bool(te.get("is_locked", False)),
                    is_manual_override=bool(te.get("is_manual_override", False)),
                )
            )
        session.flush()

        for es in payload["exam_slots"]:
            label = es.get("label") or es.get("session_label")
            session.merge(
                ExamSlot(
                    exam_slot_id=es["exam_slot_id"],
                    term_id=es["term_id"],
                    exam_date=_parse_date(es["exam_date"]),
                    start_time=_parse_time(es["start_time"]),
                    end_time=_parse_time(es["end_time"]),
                    label=label,
                )
            )
        session.flush()

        for ee in payload["exam_entries"]:
            session.merge(
                ExamEntry(
                    exam_entry_id=ee["exam_entry_id"],
                    schedule_id=ee["schedule_id"],
                    course_id=ee["course_id"],
                    exam_slot_id=ee["exam_slot_id"],
                    student_count=ee["student_count"],
                    is_locked=bool(ee.get("is_locked", False)),
                )
            )
        session.flush()

        for era in payload["exam_room_allocations"]:
            session.merge(
                ExamRoomAllocation(
                    allocation_id=era["allocation_id"],
                    exam_entry_id=era["exam_entry_id"],
                    room_id=era["room_id"],
                    seats_allocated=era["seats_allocated"],
                )
            )
        session.flush()

        existing_seed_audit = session.scalar(
            select(AuditLog).where(AuditLog.action == "SEED_DATABASE")
        )
        if existing_seed_audit is None:
            session.add(
                AuditLog(
                    user_id=2,
                    action="SEED_DATABASE",
                    entity_type="academic_terms",
                    entity_id=1,
                    details="Seeded Fall 2026 master data, users, student enrollments, and schedules.",
                )
            )
        session.flush()

        summary: dict[str, int] = {
            "departments": len(session.scalars(select(Department)).all()),
            "academic_terms": len(session.scalars(select(AcademicTerm)).all()),
            "time_slots": len(session.scalars(select(TimeSlot)).all()),
            "batches": len(session.scalars(select(Batch)).all()),
            "courses": len(session.scalars(select(Course)).all()),
            "instructors": len(session.scalars(select(Instructor)).all()),
            "instructor_availability": len(
                session.scalars(select(InstructorAvailability)).all()
            ),
            "rooms": len(session.scalars(select(Room)).all()),
            "users": len(session.scalars(select(User)).all()),
            "course_offerings": len(session.scalars(select(CourseOffering)).all()),
            "enrollments": len(session.scalars(select(Enrollment)).all()),
            "scheduling_configs": len(session.scalars(select(SchedulingConfig)).all()),
            "constraint_rules": len(session.scalars(select(ConstraintRule)).all()),
            "schedules": len(session.scalars(select(Schedule)).all()),
            "timetable_entries": len(session.scalars(select(TimetableEntry)).all()),
            "exam_slots": len(session.scalars(select(ExamSlot)).all()),
            "exam_entries": len(session.scalars(select(ExamEntry)).all()),
            "exam_room_allocations": len(
                session.scalars(select(ExamRoomAllocation)).all()
            ),
        }
        return summary


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for seeding the configured database (`DATABASE_URL` or `--database-url`)."""
    parser = argparse.ArgumentParser(
        description="Seed the ATES database with Fall 2026 master data, users, and enrollments."
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Optional SQLAlchemy database URL override (defaults to DATABASE_URL from .env).",
    )
    parser.add_argument(
        "--timetable-seed",
        default=str(DEFAULT_TIMETABLE_SEED_PATH),
        help="Path to timetable seed JSON file.",
    )
    parser.add_argument(
        "--exam-seed",
        default=str(DEFAULT_EXAM_SEED_PATH),
        help="Path to exam seed JSON file.",
    )
    args = parser.parse_args(argv)

    engine = create_db_engine(database_url=args.database_url)
    counts = seed_database(
        engine,
        timetable_seed_path=args.timetable_seed,
        exam_seed_path=args.exam_seed,
        create_tables=True,
    )
    print("ATES database seeded successfully:")
    for table_name, count in counts.items():
        print(f"  {table_name}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
