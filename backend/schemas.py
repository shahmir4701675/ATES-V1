"""Pydantic v2 request and response schemas for the ATES REST API (Milestone 5b).

Conforms strictly to `docs/SRS.pdf` (Table 9, Section 3.2, Section 5.1) and `docs/data-contract.md`.
"""

from __future__ import annotations

from datetime import date, time
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator
from engine.weekly_grid import clock_minutes


def _weekly_clock(value: str) -> str:
    minutes = clock_minutes(value)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


WeeklyClock = Annotated[str, AfterValidator(_weekly_clock)]
Weekday = Annotated[int, Field(strict=True, ge=1, le=7)]
SlotIndex = Annotated[int, Field(strict=True, ge=1, le=32767)]


# ============================================================================
# 1. Departments (`departments`)
# ============================================================================
class DepartmentCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=10)
    name: str = Field(..., min_length=1, max_length=100)


class DepartmentUpdate(BaseModel):
    department_id: int | None = None
    code: str | None = Field(default=None, min_length=1, max_length=10)
    name: str | None = Field(default=None, min_length=1, max_length=100)


class DepartmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    department_id: int
    code: str
    name: str


# ============================================================================
# 2. Courses (`courses` — FR-2.1, FR-2.2)
# ============================================================================
class CourseCreate(BaseModel):
    course_code: str = Field(..., min_length=1, max_length=15)
    title: str = Field(..., min_length=1, max_length=150)
    department_id: int = 1
    credit_hours: int = Field(..., ge=0)
    lecture_hours: int = Field(default=0, ge=0)
    lab_hours: int = Field(default=0, ge=0)
    is_active: bool = True

    @model_validator(mode="after")
    def _check_contact_hours_positive(self) -> "CourseCreate":
        if self.lecture_hours + self.lab_hours <= 0:
            raise ValueError(
                "Total weekly contact hours (lecture_hours + lab_hours) must be greater than 0 (FR-2.2)."
            )
        return self


class CourseUpdate(BaseModel):
    course_id: int | None = None
    course_code: str | None = Field(default=None, min_length=1, max_length=15)
    title: str | None = Field(default=None, min_length=1, max_length=150)
    department_id: int | None = None
    credit_hours: int | None = Field(default=None, ge=0)
    lecture_hours: int | None = Field(default=None, ge=0)
    lab_hours: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class CourseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    course_id: int
    course_code: str
    title: str
    department_id: int
    credit_hours: int
    lecture_hours: int
    lab_hours: int
    is_active: bool


# ============================================================================
# 3. Instructors & Availability (`instructors`, `instructor_availability` — FR-2.3, FR-3.1..3.3)
# ============================================================================
class InstructorCreate(BaseModel):
    department_id: int = 1
    full_name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., min_length=3, max_length=120)
    max_daily_hours: int = Field(default=4, gt=0)
    max_weekly_hours: int = Field(default=18, gt=0)
    is_active: bool = True

    @model_validator(mode="after")
    def _check_weekly_vs_daily(self) -> "InstructorCreate":
        if self.max_weekly_hours < self.max_daily_hours:
            raise ValueError(
                "max_weekly_hours must be greater than or equal to max_daily_hours (FR-2.3)."
            )
        return self


class InstructorUpdate(BaseModel):
    instructor_id: int | None = None
    department_id: int | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, min_length=3, max_length=120)
    max_daily_hours: int | None = Field(default=None, gt=0)
    max_weekly_hours: int | None = Field(default=None, gt=0)
    is_active: bool | None = None


class InstructorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    instructor_id: int
    department_id: int
    full_name: str
    email: str
    max_daily_hours: int
    max_weekly_hours: int
    is_active: bool


class AvailabilityItem(BaseModel):
    slot_id: int
    is_available: bool = False


class AvailabilityBulkUpdate(BaseModel):
    slots: list[AvailabilityItem]


class AvailabilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    availability_id: int
    instructor_id: int
    slot_id: int
    is_available: bool


# ============================================================================
# 4. Rooms (`rooms` — FR-2.4)
# ============================================================================
class RoomCreate(BaseModel):
    room_code: str = Field(..., min_length=1, max_length=20)
    building: str = Field(..., min_length=1, max_length=50)
    capacity: int = Field(..., gt=0)
    room_type: Literal["Lecture", "Lab", "Exam Hall"]
    is_active: bool = True


class RoomUpdate(BaseModel):
    room_id: int | None = None
    room_code: str | None = Field(default=None, min_length=1, max_length=20)
    building: str | None = Field(default=None, min_length=1, max_length=50)
    capacity: int | None = Field(default=None, gt=0)
    room_type: Literal["Lecture", "Lab", "Exam Hall"] | None = None
    is_active: bool | None = None


class RoomResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    room_id: int
    room_code: str
    building: str
    capacity: int
    room_type: str
    is_active: bool


# ============================================================================
# 5. Student Batches (`batches` — FR-2.5)
# ============================================================================
class BatchCreate(BaseModel):
    department_id: int = 1
    program_code: str = Field(..., min_length=1, max_length=10)
    batch_year: int = Field(..., ge=2000, le=2100)
    section: str = Field(..., min_length=1, max_length=5)
    strength: int = Field(..., gt=0)
    is_active: bool = True


class BatchUpdate(BaseModel):
    batch_id: int | None = None
    department_id: int | None = None
    program_code: str | None = Field(default=None, min_length=1, max_length=10)
    batch_year: int | None = Field(default=None, ge=2000, le=2100)
    section: str | None = Field(default=None, min_length=1, max_length=5)
    strength: int | None = Field(default=None, gt=0)
    is_active: bool | None = None


class BatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    batch_id: int
    department_id: int
    program_code: str
    batch_year: int
    section: str
    strength: int
    is_active: bool


# ============================================================================
# 6. Academic Terms, Time Slots & Exam Slots (`academic_terms`, `time_slots`, `exam_slots`)
# ============================================================================
class TermCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    start_date: date
    end_date: date
    status: Literal["Planned", "Active", "Closed"] = "Planned"

    @model_validator(mode="after")
    def _check_dates(self) -> "TermCreate":
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be strictly after start_date (FR-2.6).")
        return self


class TermUpdate(BaseModel):
    term_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=50)
    start_date: date | None = None
    end_date: date | None = None
    status: Literal["Planned", "Active", "Closed"] | None = None


class TermResponse(BaseModel):
    term_id: int
    name: str
    start_date: str
    end_date: str
    status: str


class TimeSlotCreate(BaseModel):
    term_id: int | None = None
    day_of_week: Weekday
    slot_index: SlotIndex
    start_time: WeeklyClock
    end_time: WeeklyClock
    is_blocked: bool = False
    block_reason: str | None = Field(default=None, max_length=50)


class TimeSlotUpdate(BaseModel):
    slot_id: int | None = None
    day_of_week: Weekday | None = None
    slot_index: SlotIndex | None = None
    start_time: WeeklyClock | None = None
    end_time: WeeklyClock | None = None
    is_blocked: bool | None = None
    block_reason: str | None = Field(default=None, max_length=50)


class SlotGridGenerateRequest(BaseModel):
    working_days: list[Weekday] = Field(default_factory=lambda: [1, 2, 3, 4, 5], min_length=1, max_length=7)
    first_start_time: WeeklyClock = "08:00"
    slot_length_min: int = Field(default=60, strict=True, gt=0, le=1439)
    slots_per_day: int = Field(default=6, strict=True, gt=0, le=1440)
    blocked_slot_indices: list[SlotIndex] = Field(default_factory=list)
    block_reason: str | None = Field(default="Break / Prayer", max_length=50)

    @model_validator(mode="after")
    def validate_grid_options(self):
        if len(set(self.working_days)) != len(self.working_days):
            raise ValueError("working_days must be unique.")
        if len(set(self.blocked_slot_indices)) != len(self.blocked_slot_indices) or any(i > self.slots_per_day for i in self.blocked_slot_indices):
            raise ValueError("Blocked indexes must be unique and within slots_per_day.")
        if self.blocked_slot_indices and not (self.block_reason and self.block_reason.strip()):
            raise ValueError("Blocked slots require a block_reason.")
        return self


class TimeSlotResponse(BaseModel):
    slot_id: int
    term_id: int
    day_of_week: int
    slot_index: int
    start_time: str
    end_time: str
    is_blocked: bool
    block_reason: str | None = None


class ExamSlotCreate(BaseModel):
    term_id: int | None = None
    exam_date: date
    start_time: WeeklyClock
    end_time: WeeklyClock
    label: str | None = Field(None,max_length=30)

    @model_validator(mode='after')
    def chronological(self):
        if clock_minutes(self.end_time)<=clock_minutes(self.start_time):raise ValueError('Exam slots must end after they start, without crossing midnight.')
        return self


class ExamSlotUpdate(BaseModel):
    exam_slot_id: int | None = None
    exam_date: date | None = None
    start_time: WeeklyClock | None = None
    end_time: WeeklyClock | None = None
    label: str | None = Field(None,max_length=30)


class ExamSlotResponse(BaseModel):
    exam_slot_id: int
    term_id: int
    exam_date: str
    start_time: str
    end_time: str
    label: str | None = None


# ============================================================================
# 7. Course Offerings & Enrollments (`course_offerings`, `enrollments` — FR-2.8..2.10)
# ============================================================================
class OfferingCreate(BaseModel):
    term_id: int
    course_id: int
    batch_id: int
    instructor_id: int
    enrolled_count: int = Field(..., gt=0)


class OfferingUpdate(BaseModel):
    offering_id: int | None = None
    term_id: int | None = None
    course_id: int | None = None
    batch_id: int | None = None
    instructor_id: int | None = None
    enrolled_count: int | None = Field(default=None, gt=0)


class OfferingResponse(BaseModel):
    offering_id: int
    term_id: int
    course_id: int
    batch_id: int
    instructor_id: int
    enrolled_count: int
    required_lecture_sessions: int | None = None
    required_lab_slots: int | None = None


class EnrollmentCreate(BaseModel):
    offering_id: int
    student_id: int


class EnrollmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enrollment_id: int
    offering_id: int
    student_id: int


# ============================================================================
# 8. Scheduling Configurations & Constraint Rules (`scheduling_configs`, `constraint_rules`)
# ============================================================================
class ConstraintRuleInput(BaseModel):
    rule_code: str = Field(..., min_length=2, max_length=6)
    rule_type: Literal["Hard", "Soft"] | None = None
    is_enabled: bool = True
    weight: int = Field(default=0, ge=0, le=10,strict=True)
    param_value: int | None = Field(None,strict=True,ge=1,le=2147483647)


class ConstraintRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule_id: int
    config_id: int
    rule_code: str
    rule_type: str
    is_enabled: bool
    weight: int
    param_value: int | None = None


class ConfigCreate(BaseModel):
    term_id: int
    schedule_type: Literal["Timetable", "Exam"]
    name: str = Field(..., min_length=1, max_length=60)
    solver_time_limit_s: int = Field(default=120, ge=10, le=600)
    random_seed: int = Field(1,ge=0,le=2147483647,strict=True)
    created_by: int | None = None  # Legacy input accepted but never used as authenticated identity.
    rules: list[ConstraintRuleInput] | None = None


class ConfigUpdate(BaseModel):
    config_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=60)
    solver_time_limit_s: int | None = Field(default=None, ge=10, le=600)
    random_seed: int | None = Field(None,ge=0,le=2147483647,strict=True)
    rules: list[ConstraintRuleInput] | None = None


class ConfigResponse(BaseModel):
    config_id: int
    term_id: int
    schedule_type: str
    name: str
    solver_time_limit_s: int
    random_seed: int
    created_by: int
    created_at: str
    rules: list[ConstraintRuleResponse] = Field(default_factory=list)


class ConstraintRulesUpdatePayload(BaseModel):
    rules: list[ConstraintRuleInput]


# ============================================================================
# 9. Schedule Generation, Status, Entries, Conflicts & Manual Adjustment
# ============================================================================
class ScheduleGenerateRequest(BaseModel):
    term_id: int = 1
    config_id: int | None = None
    schedule_type: Literal["Timetable", "Exam"] = "Timetable"
    solver_time_limit_s: int | None = Field(default=None, ge=10, le=600)
    random_seed: int | None = Field(None,ge=0,le=2147483647,strict=True)
    generated_by: int | None = None  # Legacy input accepted but never used as authenticated identity.


class ScheduleGenerateResponse(BaseModel):
    schedule_id: int
    term_id: int
    config_id: int
    schedule_type: str
    version_no: int
    status: str


class ScheduleStatusResponse(BaseModel):
    generation_state: str | None = None
    generation_phase: str | None = None
    worker_stopped: bool = False
    schedule_id: int
    term_id: int
    config_id: int
    schedule_type: str
    version_no: int
    status: str
    solver_status: str | None = None
    objective_score: float | None = None
    run_seconds: float | None = None
    entry_count: int = 0
    conflict_count: int = 0
    hard_violation_count: int = 0
    generated_by: int
    generated_at: str
    approved_by: int | None = None
    published_at: str | None = None


class EnrichedTimetableEntryResponse(BaseModel):
    entry_id: int
    schedule_id: int
    offering_id: int
    course_id: int
    course_code: str
    course_title: str
    instructor_id: int
    instructor_name: str
    batch_id: int
    batch_label: str
    room_id: int
    room_code: str
    slot_id: int
    day_of_week: int
    slot_index: int
    start_time: str
    end_time: str
    session_type: str
    is_locked: bool
    is_manual_override: bool


class EnrichedExamRoomAllocationResponse(BaseModel):
    allocation_id: int
    room_id: int
    room_code: str
    building: str
    seats_allocated: int


class EnrichedExamEntryResponse(BaseModel):
    is_manual_override: bool = False
    exam_entry_id: int
    schedule_id: int
    course_id: int
    course_code: str
    course_title: str
    exam_slot_id: int
    exam_date: str
    start_time: str
    end_time: str
    label: str | None = None
    student_count: int
    is_locked: bool
    room_allocations: list[EnrichedExamRoomAllocationResponse] = Field(default_factory=list)


class ScheduleEntriesResponse(BaseModel):
    edit_revision: int = 0
    context: dict[str, Any] = Field(default_factory=dict)
    schedule_id: int
    term_id: int
    term_name: str
    config_id: int
    schedule_type: str
    version_no: int
    status: str
    solver_status: str | None = None
    objective_score: float | None = None
    run_seconds: float | None = None
    hard_violation_count: int = 0
    generated_by: int
    generated_at: str
    approved_by: int | None = None
    published_at: str | None = None
    timetable_entries: list[EnrichedTimetableEntryResponse] = Field(default_factory=list)
    exam_entries: list[EnrichedExamEntryResponse] = Field(default_factory=list)
    entries: list[dict[str, Any]] = Field(default_factory=list)


class ConflictLogResponse(BaseModel):
    conflict_id: int
    schedule_id: int
    conflict_type: str
    severity: str
    description: str
    entity_ref: str | None = None
    detected_at: str
    is_resolved: bool


class ExamRoomAllocationInput(BaseModel):
    room_id: int = Field(gt=0,strict=True)
    seats_allocated: int = Field(..., gt=0,le=32767,strict=True)


class ScheduleEntryUpdateRequest(BaseModel):
    """Payload for `PUT /schedules/{id}/entries/{entry_id}` (FR-8.3..FR-8.6)."""

    entry_id: int | None = Field(None,gt=0,le=2147483647,strict=True)
    slot_id: int | None = Field(None,gt=0,le=2147483647,strict=True)
    room_id: int | None = Field(None,gt=0,le=2147483647,strict=True)
    exam_slot_id: int | None = Field(None,gt=0,le=2147483647,strict=True)
    room_allocations: list[ExamRoomAllocationInput] | None = None
    is_locked: bool | None = None
    expected_revision: int | None = Field(None,ge=0,strict=True)


class UndoScheduleRequest(BaseModel):
    expected_revision: int | None = Field(None,ge=0,strict=True)
