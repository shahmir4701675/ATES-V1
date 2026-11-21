"""ATES Backend Database & Persistence Package (Milestone 5a).

Provides:
- SQLAlchemy 2.x ORM models for all 21 ATES 3NF tables (`backend.models`)
- Database engine & transactional session management connected via `DATABASE_URL` (`backend.database`)
- Term dataset loader & atomic single-transaction solver result persistence (`backend.adapter`)
- Database seeding script including student users and enrollments (`backend.seed`)
"""

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
from backend.main import app, create_app, get_cors_allowed_origins, recover_interrupted_generations
from backend.seed import seed_database

__all__ = [
    "ALL_MODELS",
    "AcademicTerm",
    "AuditLog",
    "Base",
    "Batch",
    "ConflictLog",
    "ConstraintRule",
    "Course",
    "CourseOffering",
    "Department",
    "Enrollment",
    "ExamEntry",
    "ExamRoomAllocation",
    "ExamSlot",
    "ImportLog",
    "Instructor",
    "InstructorAvailability",
    "Room",
    "Schedule",
    "SchedulingConfig",
    "TermScheduleAdapter",
    "TimeSlot",
    "TimetableEntry",
    "User",
    "app",
    "create_app",
    "create_db_engine",
    "create_session_factory",
    "get_cors_allowed_origins",
    "get_database_url",
    "init_db",
    "load_term_dataset",
    "normalize_database_url",
    "recover_interrupted_generations",
    "save_engine_result",
    "save_exam_result",
    "save_timetable_result",
    "seed_database",
    "session_scope",
]
