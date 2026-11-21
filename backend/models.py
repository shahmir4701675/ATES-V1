"""SQLAlchemy 2.x ORM models matching `db/schema.sql` and `docs/SRS.pdf` Section 5.1.

Defines all 21 relational tables in 3NF with exact column names, data types, defaults,
primary keys, foreign keys (`ON DELETE RESTRICT` / `ON DELETE CASCADE` per `DB-3`),
unique constraints (`DB-4`), composite foreign keys (`DB-2`), check constraints, and
partial unique indexes (`uq_academic_terms_single_active`, `uq_schedules_one_published_per_term_type`).
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utc_now_naive() -> datetime:
    """Return current UTC timestamp as a timezone-naive `datetime` matching SQL `TIMESTAMP`."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    """Declarative base for all 21 ATES database tables."""


# ============================================================================
# 5.1.3.1  departments
# ============================================================================
class Department(Base):
    """Academic department that owns courses, instructors, and batches (SRS 5.1.3.1)."""

    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("code", name="uq_departments_code"),
    )

    department_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    batches: Mapped[list["Batch"]] = relationship("Batch", back_populates="department")
    courses: Mapped[list["Course"]] = relationship("Course", back_populates="department")
    instructors: Mapped[list["Instructor"]] = relationship("Instructor", back_populates="department")


# ============================================================================
# 5.1.3.2  academic_terms
# ============================================================================
class AcademicTerm(Base):
    """Semester for which schedules are produced (SRS 5.1.3.2)."""

    __tablename__ = "academic_terms"
    __table_args__ = (
        UniqueConstraint("name", name="uq_academic_terms_name"),
        CheckConstraint("end_date > start_date", name="ck_academic_terms_dates"),
        CheckConstraint(
            "status IN ('Planned', 'Active', 'Closed')",
            name="ck_academic_terms_status",
        ),
        Index(
            "uq_academic_terms_single_active",
            "status",
            unique=True,
            postgresql_where=text("status = 'Active'"),
            sqlite_where=text("status = 'Active'"),
        ),
    )

    term_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="Planned",
        server_default=text("'Planned'"),
    )

    time_slots: Mapped[list["TimeSlot"]] = relationship("TimeSlot", back_populates="term")
    course_offerings: Mapped[list["CourseOffering"]] = relationship(
        "CourseOffering", back_populates="term"
    )
    scheduling_configs: Mapped[list["SchedulingConfig"]] = relationship(
        "SchedulingConfig", back_populates="term"
    )
    schedules: Mapped[list["Schedule"]] = relationship("Schedule", back_populates="term")
    exam_slots: Mapped[list["ExamSlot"]] = relationship("ExamSlot", back_populates="term")


# ============================================================================
# 5.1.3.3  time_slots
# ============================================================================
class TimeSlot(Base):
    """Weekly slot grid of a term (SRS 5.1.3.3)."""

    __tablename__ = "time_slots"
    __table_args__ = (
        UniqueConstraint(
            "term_id",
            "day_of_week",
            "slot_index",
            name="uq_time_slots_term_day_index",
        ),
        CheckConstraint("day_of_week BETWEEN 1 AND 7", name="ck_time_slots_day_of_week"),
        CheckConstraint("slot_index > 0", name="ck_time_slots_slot_index"),
        CheckConstraint("end_time > start_time", name="ck_time_slots_time_order"),
        CheckConstraint(
            "(is_blocked = FALSE) OR (block_reason IS NOT NULL AND LENGTH(TRIM(block_reason)) > 0)",
            name="ck_time_slots_block_reason",
        ),
        Index("idx_time_slots_term_id", "term_id"),
    )

    slot_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    term_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("academic_terms.term_id", ondelete="RESTRICT", name="fk_time_slots_term"),
        nullable=False,
    )
    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    slot_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("FALSE"),
    )
    block_reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    term: Mapped["AcademicTerm"] = relationship("AcademicTerm", back_populates="time_slots")
    instructor_availabilities: Mapped[list["InstructorAvailability"]] = relationship(
        "InstructorAvailability",
        back_populates="slot",
        passive_deletes=True,
    )


# ============================================================================
# 5.1.3.4  batches
# ============================================================================
class Batch(Base):
    """Student cohort / section (SRS 5.1.3.4)."""

    __tablename__ = "batches"
    __table_args__ = (
        UniqueConstraint(
            "program_code",
            "batch_year",
            "section",
            name="uq_batches_program_year_section",
        ),
        CheckConstraint("batch_year BETWEEN 2000 AND 2100", name="ck_batches_batch_year"),
        CheckConstraint("strength > 0", name="ck_batches_strength"),
        Index("idx_batches_department_id", "department_id"),
    )

    batch_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    department_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("departments.department_id", ondelete="RESTRICT", name="fk_batches_department"),
        nullable=False,
    )
    program_code: Mapped[str] = mapped_column(String(10), nullable=False)
    batch_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    section: Mapped[str] = mapped_column(String(5), nullable=False)
    strength: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("TRUE"),
    )

    department: Mapped["Department"] = relationship("Department", back_populates="batches")


# ============================================================================
# 5.1.3.5  courses
# ============================================================================
class Course(Base):
    """Course catalogue entry (SRS 5.1.3.5)."""

    __tablename__ = "courses"
    __table_args__ = (
        UniqueConstraint("course_code", name="uq_courses_course_code"),
        CheckConstraint("credit_hours >= 0", name="ck_courses_credit_hours"),
        CheckConstraint("lecture_hours >= 0", name="ck_courses_lecture_hours"),
        CheckConstraint("lab_hours >= 0", name="ck_courses_lab_hours"),
        CheckConstraint(
            "lecture_hours + lab_hours > 0",
            name="ck_courses_contact_hours_positive",
        ),
        Index("idx_courses_department_id", "department_id"),
    )

    course_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_code: Mapped[str] = mapped_column(String(15), nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    department_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("departments.department_id", ondelete="RESTRICT", name="fk_courses_department"),
        nullable=False,
    )
    credit_hours: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    lecture_hours: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    lab_hours: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("TRUE"),
    )

    department: Mapped["Department"] = relationship("Department", back_populates="courses")


# ============================================================================
# 5.1.3.6  instructors
# ============================================================================
class Instructor(Base):
    """Teaching staff member (SRS 5.1.3.6)."""

    __tablename__ = "instructors"
    __table_args__ = (
        UniqueConstraint("email", name="uq_instructors_email"),
        CheckConstraint("max_daily_hours > 0", name="ck_instructors_max_daily_hours"),
        CheckConstraint(
            "max_weekly_hours >= max_daily_hours",
            name="ck_instructors_max_weekly_hours",
        ),
        Index("idx_instructors_department_id", "department_id"),
    )

    instructor_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    department_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "departments.department_id",
            ondelete="RESTRICT",
            name="fk_instructors_department",
        ),
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(120), nullable=False)
    max_daily_hours: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=4,
        server_default=text("4"),
    )
    max_weekly_hours: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=18,
        server_default=text("18"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("TRUE"),
    )

    department: Mapped["Department"] = relationship("Department", back_populates="instructors")
    availabilities: Mapped[list["InstructorAvailability"]] = relationship(
        "InstructorAvailability", back_populates="instructor"
    )


# ============================================================================
# 5.1.3.7  instructor_availability
# ============================================================================
class InstructorAvailability(Base):
    """Weekly slot availability record for an instructor (SRS 5.1.3.7)."""

    __tablename__ = "instructor_availability"
    __table_args__ = (
        UniqueConstraint(
            "instructor_id",
            "slot_id",
            name="uq_instructor_availability_instructor_slot",
        ),
        Index("idx_instructor_availability_instructor_id", "instructor_id"),
        Index("idx_instructor_availability_slot_id", "slot_id"),
    )

    availability_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instructor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "instructors.instructor_id",
            ondelete="RESTRICT",
            name="fk_instructor_availability_instructor",
        ),
        nullable=False,
    )
    slot_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "time_slots.slot_id",
            ondelete="CASCADE",
            name="fk_instructor_availability_slot",
        ),
        nullable=False,
    )
    is_available: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("TRUE"),
    )

    instructor: Mapped["Instructor"] = relationship("Instructor", back_populates="availabilities")
    slot: Mapped["TimeSlot"] = relationship("TimeSlot", back_populates="instructor_availabilities")


# ============================================================================
# 5.1.3.8  rooms
# ============================================================================
class Room(Base):
    """Lecture room, laboratory, or exam hall (SRS 5.1.3.8)."""

    __tablename__ = "rooms"
    __table_args__ = (
        UniqueConstraint("room_code", name="uq_rooms_room_code"),
        CheckConstraint("capacity > 0", name="ck_rooms_capacity"),
        CheckConstraint(
            "room_type IN ('Lecture', 'Lab', 'Exam Hall')",
            name="ck_rooms_room_type",
        ),
    )

    room_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_code: Mapped[str] = mapped_column(String(20), nullable=False)
    building: Mapped[str] = mapped_column(String(50), nullable=False)
    capacity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    room_type: Mapped[str] = mapped_column(String(12), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("TRUE"),
    )


# ============================================================================
# 5.1.3.9  users
# ============================================================================
class User(Base):
    """Authenticated system user account (SRS 5.1.3.9)."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        UniqueConstraint("email", name="uq_users_email"),
        UniqueConstraint("instructor_id", name="uq_users_instructor_id"),
        CheckConstraint(
            "role IN ('Administrator', 'Coordinator', 'Approver', 'Faculty', 'Student')",
            name="ck_users_role",
        ),
        CheckConstraint(
            "account_status IN ('Active', 'Locked', 'Deactivated')",
            name="ck_users_account_status",
        ),
        CheckConstraint("failed_attempts >= 0", name="ck_users_failed_attempts"),
        CheckConstraint(
            "(role <> 'Faculty') OR (instructor_id IS NOT NULL)",
            name="ck_users_faculty_instructor_link",
        ),
        CheckConstraint(
            "(role <> 'Student') OR (batch_id IS NOT NULL)",
            name="ck_users_student_batch_link",
        ),
        Index("idx_users_batch_id", "batch_id"),
    )

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(40), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(15), nullable=False)
    instructor_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("instructors.instructor_id", ondelete="RESTRICT", name="fk_users_instructor"),
        nullable=True,
    )
    batch_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("batches.batch_id", ondelete="RESTRICT", name="fk_users_batch"),
        nullable=True,
    )
    account_status: Mapped[str] = mapped_column(
        String(12),
        nullable=False,
        default="Active",
        server_default=text("'Active'"),
    )
    failed_attempts: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utc_now_naive,
        server_default=text("CURRENT_TIMESTAMP"),
    )


# ============================================================================
# 5.1.3.10  course_offerings
# ============================================================================
class CourseOffering(Base):
    """A course taught to one batch by one instructor in one term (SRS 5.1.3.10)."""

    __tablename__ = "course_offerings"
    __table_args__ = (
        UniqueConstraint(
            "term_id",
            "course_id",
            "batch_id",
            name="uq_course_offerings_term_course_batch",
        ),
        # Composite unique key supporting the composite FK from `timetable_entries` (DB-2)
        UniqueConstraint(
            "offering_id",
            "instructor_id",
            "batch_id",
            name="uq_course_offerings_offering_instructor_batch",
        ),
        CheckConstraint("enrolled_count > 0", name="ck_course_offerings_enrolled_count"),
        Index("idx_course_offerings_term_id", "term_id"),
        Index("idx_course_offerings_course_id", "course_id"),
        Index("idx_course_offerings_batch_id", "batch_id"),
        Index("idx_course_offerings_instructor_id", "instructor_id"),
    )

    offering_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    term_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "academic_terms.term_id",
            ondelete="RESTRICT",
            name="fk_course_offerings_term",
        ),
        nullable=False,
    )
    course_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("courses.course_id", ondelete="RESTRICT", name="fk_course_offerings_course"),
        nullable=False,
    )
    batch_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("batches.batch_id", ondelete="RESTRICT", name="fk_course_offerings_batch"),
        nullable=False,
    )
    instructor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "instructors.instructor_id",
            ondelete="RESTRICT",
            name="fk_course_offerings_instructor",
        ),
        nullable=False,
    )
    enrolled_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    term: Mapped["AcademicTerm"] = relationship("AcademicTerm", back_populates="course_offerings")
    enrollments: Mapped[list["Enrollment"]] = relationship(
        "Enrollment",
        back_populates="offering",
        passive_deletes=True,
    )


# ============================================================================
# 5.1.3.11  enrollments
# ============================================================================
class Enrollment(Base):
    """Individual student-to-offering link for electives/repeaters (SRS 5.1.3.11)."""

    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint(
            "offering_id",
            "student_id",
            name="uq_enrollments_offering_student",
        ),
        Index("idx_enrollments_offering_id", "offering_id"),
        Index("idx_enrollments_student_id", "student_id"),
    )

    enrollment_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    offering_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "course_offerings.offering_id",
            ondelete="CASCADE",
            name="fk_enrollments_offering",
        ),
        nullable=False,
    )
    student_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.user_id", ondelete="RESTRICT", name="fk_enrollments_student"),
        nullable=False,
    )

    offering: Mapped["CourseOffering"] = relationship(
        "CourseOffering", back_populates="enrollments"
    )


# ============================================================================
# 5.1.3.12  scheduling_configs
# ============================================================================
class SchedulingConfig(Base):
    """Named configuration profile for a term and schedule type (SRS 5.1.3.12)."""

    __tablename__ = "scheduling_configs"
    __table_args__ = (
        UniqueConstraint(
            "term_id",
            "schedule_type",
            "name",
            name="uq_scheduling_configs_term_type_name",
        ),
        CheckConstraint(
            "schedule_type IN ('Timetable', 'Exam')",
            name="ck_scheduling_configs_schedule_type",
        ),
        CheckConstraint(
            "solver_time_limit_s BETWEEN 10 AND 600",
            name="ck_scheduling_configs_time_limit",
        ),
        Index("idx_scheduling_configs_term_id", "term_id"),
        Index("idx_scheduling_configs_created_by", "created_by"),
    )

    config_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    term_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "academic_terms.term_id",
            ondelete="RESTRICT",
            name="fk_scheduling_configs_term",
        ),
        nullable=False,
    )
    schedule_type: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    solver_time_limit_s: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=120,
        server_default=text("120"),
    )
    random_seed: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    created_by: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.user_id", ondelete="RESTRICT", name="fk_scheduling_configs_created_by"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utc_now_naive,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    term: Mapped["AcademicTerm"] = relationship(
        "AcademicTerm", back_populates="scheduling_configs"
    )
    constraint_rules: Mapped[list["ConstraintRule"]] = relationship(
        "ConstraintRule",
        back_populates="config",
        passive_deletes=True,
    )


# ============================================================================
# 5.1.3.13  constraint_rules
# ============================================================================
class ConstraintRule(Base):
    """Constraint toggle, weight, and parameter belonging to a config (SRS 5.1.3.13)."""

    __tablename__ = "constraint_rules"
    __table_args__ = (
        UniqueConstraint("config_id", "rule_code", name="uq_constraint_rules_config_code"),
        CheckConstraint("rule_type IN ('Hard', 'Soft')", name="ck_constraint_rules_rule_type"),
        CheckConstraint("weight BETWEEN 0 AND 10", name="ck_constraint_rules_weight"),
        CheckConstraint(
            "(rule_code NOT IN ('H01', 'H02', 'H03', 'H08', 'E01', 'E04', 'E05')) OR (is_enabled = TRUE)",
            name="ck_constraint_rules_mandatory_enabled",
        ),
        Index("idx_constraint_rules_config_id", "config_id"),
    )

    rule_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "scheduling_configs.config_id",
            ondelete="CASCADE",
            name="fk_constraint_rules_config",
        ),
        nullable=False,
    )
    rule_code: Mapped[str] = mapped_column(String(6), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(4), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("TRUE"),
    )
    weight: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    param_value: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    config: Mapped["SchedulingConfig"] = relationship(
        "SchedulingConfig", back_populates="constraint_rules"
    )


# ============================================================================
# 5.1.3.14  schedules
# ============================================================================
class Schedule(Base):
    """Header record for a generated schedule version (SRS 5.1.3.14)."""

    __tablename__ = "schedules"
    __table_args__ = (
        UniqueConstraint(
            "term_id",
            "schedule_type",
            "version_no",
            name="uq_schedules_term_type_version",
        ),
        CheckConstraint(
            "schedule_type IN ('Timetable', 'Exam')",
            name="ck_schedules_schedule_type",
        ),
        CheckConstraint("version_no > 0", name="ck_schedules_version_no"),
        CheckConstraint(
            "status IN ('Draft', 'Generating', 'Infeasible', 'Generated', 'Published', 'Archived')",
            name="ck_schedules_status",
        ),
        CheckConstraint(
            "solver_status IS NULL OR solver_status IN ('optimal', 'feasible', 'infeasible', 'unknown', 'interrupted')",
            name="ck_schedules_solver_status",
        ),
        CheckConstraint(
            "run_seconds IS NULL OR run_seconds >= 0",
            name="ck_schedules_run_seconds",
        ),
        CheckConstraint(
            "(status <> 'Published') OR (approved_by IS NOT NULL AND published_at IS NOT NULL)",
            name="ck_schedules_published_approval",
        ),
        Index(
            "uq_schedules_one_published_per_term_type",
            "term_id",
            "schedule_type",
            unique=True,
            postgresql_where=text("status = 'Published'"),
            sqlite_where=text("status = 'Published'"),
        ),
        Index("idx_schedules_term_type_status", "term_id", "schedule_type", "status"),
        Index("idx_schedules_config_id", "config_id"),
    )

    schedule_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    term_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("academic_terms.term_id", ondelete="RESTRICT", name="fk_schedules_term"),
        nullable=False,
    )
    config_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("scheduling_configs.config_id", ondelete="RESTRICT", name="fk_schedules_config"),
        nullable=False,
    )
    schedule_type: Mapped[str] = mapped_column(String(10), nullable=False)
    version_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(12),
        nullable=False,
        default="Draft",
        server_default=text("'Draft'"),
    )
    solver_status: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    objective_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    run_seconds: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    generated_by: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.user_id", ondelete="RESTRICT", name="fk_schedules_generated_by"),
        nullable=False,
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utc_now_naive,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    approved_by: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.user_id", ondelete="RESTRICT", name="fk_schedules_approved_by"),
        nullable=True,
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    term: Mapped["AcademicTerm"] = relationship("AcademicTerm", back_populates="schedules")
    timetable_entries: Mapped[list["TimetableEntry"]] = relationship(
        "TimetableEntry",
        back_populates="schedule",
        passive_deletes=True,
    )
    exam_entries: Mapped[list["ExamEntry"]] = relationship(
        "ExamEntry",
        back_populates="schedule",
        passive_deletes=True,
    )
    conflict_logs: Mapped[list["ConflictLog"]] = relationship(
        "ConflictLog",
        back_populates="schedule",
        passive_deletes=True,
    )


# ============================================================================
# 5.1.3.15  timetable_entries
# ============================================================================
class TimetableEntry(Base):
    """One scheduled slot of a class session (SRS 5.1.3.15, `DB-2`, `DB-4`)."""

    __tablename__ = "timetable_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["offering_id", "instructor_id", "batch_id"],
            [
                "course_offerings.offering_id",
                "course_offerings.instructor_id",
                "course_offerings.batch_id",
            ],
            ondelete="RESTRICT",
            name="fk_timetable_entries_offering_triplet",
        ),
        UniqueConstraint(
            "schedule_id",
            "room_id",
            "slot_id",
            name="uq_timetable_entries_schedule_room_slot",
        ),
        UniqueConstraint(
            "schedule_id",
            "instructor_id",
            "slot_id",
            name="uq_timetable_entries_schedule_instructor_slot",
        ),
        UniqueConstraint(
            "schedule_id",
            "batch_id",
            "slot_id",
            name="uq_timetable_entries_schedule_batch_slot",
        ),
        CheckConstraint(
            "session_type IN ('Lecture', 'Lab')",
            name="ck_timetable_entries_session_type",
        ),
        Index("idx_timetable_entries_schedule_id", "schedule_id"),
        Index("idx_timetable_entries_offering_id", "offering_id"),
        Index("idx_timetable_entries_slot_id", "slot_id"),
    )

    entry_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schedule_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "schedules.schedule_id",
            ondelete="CASCADE",
            name="fk_timetable_entries_schedule",
        ),
        nullable=False,
    )
    offering_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "course_offerings.offering_id",
            ondelete="RESTRICT",
            name="fk_timetable_entries_offering",
        ),
        nullable=False,
    )
    instructor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "instructors.instructor_id",
            ondelete="RESTRICT",
            name="fk_timetable_entries_instructor",
        ),
        nullable=False,
    )
    batch_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("batches.batch_id", ondelete="RESTRICT", name="fk_timetable_entries_batch"),
        nullable=False,
    )
    room_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("rooms.room_id", ondelete="RESTRICT", name="fk_timetable_entries_room"),
        nullable=False,
    )
    slot_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("time_slots.slot_id", ondelete="RESTRICT", name="fk_timetable_entries_slot"),
        nullable=False,
    )
    session_type: Mapped[str] = mapped_column(String(7), nullable=False)
    is_locked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("FALSE"),
    )
    is_manual_override: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("FALSE"),
    )

    schedule: Mapped["Schedule"] = relationship("Schedule", back_populates="timetable_entries")


# ============================================================================
# 5.1.3.16  exam_slots
# ============================================================================
class ExamSlot(Base):
    """Exam session date and time window (SRS 5.1.3.16)."""

    __tablename__ = "exam_slots"
    __table_args__ = (
        UniqueConstraint(
            "term_id",
            "exam_date",
            "start_time",
            name="uq_exam_slots_term_date_start",
        ),
        CheckConstraint("end_time > start_time", name="ck_exam_slots_time_order"),
        Index("idx_exam_slots_term_id", "term_id"),
    )

    exam_slot_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    term_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("academic_terms.term_id", ondelete="RESTRICT", name="fk_exam_slots_term"),
        nullable=False,
    )
    exam_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    term: Mapped["AcademicTerm"] = relationship("AcademicTerm", back_populates="exam_slots")


# ============================================================================
# 5.1.3.17  exam_entries
# ============================================================================
class ExamEntry(Base):
    """Scheduled course exam in an exam slot (SRS 5.1.3.17)."""

    __tablename__ = "exam_entries"
    __table_args__ = (
        UniqueConstraint("schedule_id", "course_id", name="uq_exam_entries_schedule_course"),
        CheckConstraint("student_count > 0", name="ck_exam_entries_student_count"),
        Index("idx_exam_entries_schedule_id", "schedule_id"),
        Index("idx_exam_entries_exam_slot_id", "exam_slot_id"),
    )

    exam_entry_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schedule_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "schedules.schedule_id",
            ondelete="CASCADE",
            name="fk_exam_entries_schedule",
        ),
        nullable=False,
    )
    course_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("courses.course_id", ondelete="RESTRICT", name="fk_exam_entries_course"),
        nullable=False,
    )
    exam_slot_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "exam_slots.exam_slot_id",
            ondelete="RESTRICT",
            name="fk_exam_entries_exam_slot",
        ),
        nullable=False,
    )
    student_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_locked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("FALSE"),
    )

    schedule: Mapped["Schedule"] = relationship("Schedule", back_populates="exam_entries")
    room_allocations: Mapped[list["ExamRoomAllocation"]] = relationship(
        "ExamRoomAllocation",
        back_populates="exam_entry",
        passive_deletes=True,
    )


# ============================================================================
# 5.1.3.18  exam_room_allocations
# ============================================================================
class ExamRoomAllocation(Base):
    """Rooms and seat counts allocated to an exam entry (SRS 5.1.3.18)."""

    __tablename__ = "exam_room_allocations"
    __table_args__ = (
        UniqueConstraint(
            "exam_entry_id",
            "room_id",
            name="uq_exam_room_allocations_entry_room",
        ),
        CheckConstraint("seats_allocated > 0", name="ck_exam_room_allocations_seats"),
        Index("idx_exam_room_allocations_exam_entry_id", "exam_entry_id"),
        Index("idx_exam_room_allocations_room_id", "room_id"),
    )

    allocation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exam_entry_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "exam_entries.exam_entry_id",
            ondelete="CASCADE",
            name="fk_exam_room_allocations_exam_entry",
        ),
        nullable=False,
    )
    room_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "rooms.room_id",
            ondelete="RESTRICT",
            name="fk_exam_room_allocations_room",
        ),
        nullable=False,
    )
    seats_allocated: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    exam_entry: Mapped["ExamEntry"] = relationship(
        "ExamEntry", back_populates="room_allocations"
    )


# ============================================================================
# 5.1.3.19  conflict_log
# ============================================================================
class ConflictLog(Base):
    """Recorded constraint violations or infeasibility diagnostics (SRS 5.1.3.19)."""

    __tablename__ = "conflict_log"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('Hard', 'Warning')",
            name="ck_conflict_log_severity",
        ),
        Index("idx_conflict_log_schedule_id", "schedule_id"),
    )

    conflict_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schedule_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("schedules.schedule_id", ondelete="CASCADE", name="fk_conflict_log_schedule"),
        nullable=False,
    )
    conflict_type: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    entity_ref: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utc_now_naive,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    is_resolved: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("FALSE"),
    )

    schedule: Mapped["Schedule"] = relationship("Schedule", back_populates="conflict_logs")


# ============================================================================
# 5.1.3.20  import_logs
# ============================================================================
class ImportLog(Base):
    """Summary of each CSV bulk import operation (SRS 5.1.3.20)."""

    __tablename__ = "import_logs"
    __table_args__ = (
        CheckConstraint("rows_total >= 0", name="ck_import_logs_rows_total"),
        CheckConstraint("rows_imported >= 0", name="ck_import_logs_rows_imported"),
        CheckConstraint("rows_rejected >= 0", name="ck_import_logs_rows_rejected"),
        CheckConstraint(
            "rows_imported + rows_rejected <= rows_total",
            name="ck_import_logs_rows_sum",
        ),
        Index("idx_import_logs_user_id", "user_id"),
    )

    import_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.user_id", ondelete="RESTRICT", name="fk_import_logs_user"),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    file_name: Mapped[str] = mapped_column(String(120), nullable=False)
    rows_total: Mapped[int] = mapped_column(Integer, nullable=False)
    rows_imported: Mapped[int] = mapped_column(Integer, nullable=False)
    rows_rejected: Mapped[int] = mapped_column(Integer, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utc_now_naive,
        server_default=text("CURRENT_TIMESTAMP"),
    )


# ============================================================================
# 5.1.3.21  audit_logs
# ============================================================================
class AuditLog(Base):
    """Append-only security and governance log (SRS 5.1.3.21, `DB-8`)."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_logs_user_id", "user_id"),
        Index("idx_audit_logs_created_at", "created_at"),
    )

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.user_id", ondelete="RESTRICT", name="fk_audit_logs_user"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utc_now_naive,
        server_default=text("CURRENT_TIMESTAMP"),
    )


# Explicit ORM aliases for disambiguation when imported alongside `engine.models`
DepartmentORM = Department
AcademicTermORM = AcademicTerm
TimeSlotORM = TimeSlot
BatchORM = Batch
CourseORM = Course
InstructorORM = Instructor
InstructorAvailabilityORM = InstructorAvailability
RoomORM = Room
UserORM = User
CourseOfferingORM = CourseOffering
EnrollmentORM = Enrollment
SchedulingConfigORM = SchedulingConfig
ConstraintRuleORM = ConstraintRule
ScheduleORM = Schedule
TimetableEntryORM = TimetableEntry
ExamSlotORM = ExamSlot
ExamEntryORM = ExamEntry
ExamRoomAllocationORM = ExamRoomAllocation
ConflictLogORM = ConflictLog
ImportLogORM = ImportLog
AuditLogORM = AuditLog

ALL_MODELS: tuple[type[Base], ...] = (
    Department,
    AcademicTerm,
    TimeSlot,
    Batch,
    Course,
    Instructor,
    InstructorAvailability,
    Room,
    User,
    CourseOffering,
    Enrollment,
    SchedulingConfig,
    ConstraintRule,
    Schedule,
    TimetableEntry,
    ExamSlot,
    ExamEntry,
    ExamRoomAllocation,
    ConflictLog,
    ImportLog,
    AuditLog,
)
