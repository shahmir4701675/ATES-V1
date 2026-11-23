"""FastAPI routes for Master Data, Instructor Availability, and Constraint Configurations.

Implements SRS Table 9 resources:
- `GET, POST, PUT /courses` (`FR-2.1`, `FR-2.2`, `FR-2.11`, `FR-2.12`)
- `GET, POST, PUT /instructors` and `/instructors/{id}/availability` (`FR-2.3`, `FR-3.1`–`FR-3.4`)
- `GET, POST, PUT /rooms` (`FR-2.4`, `FR-2.11`)
- `GET, POST, PUT /batches` (`FR-2.5`, `FR-2.11`)
- `GET, POST, PUT /terms`, `/terms/{id}/slots`, and `/terms/{id}/exam-slots` (`FR-2.6`, `FR-2.7`, `FR-5.7`)
- `GET, POST, PUT /offerings` and `/enrollments` (`FR-2.8`–`FR-2.11`)
- `GET, POST, PUT /configs` and `GET, PUT /configs/{id}/rules` (`FR-5.1`–`FR-5.6`)
"""

from __future__ import annotations

from datetime import datetime, time, timezone
import math
from typing import Any
from types import SimpleNamespace
from engine.weekly_grid import validate_weekly_grid, slot_interval

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.dependencies import CurrentUser, get_db, require_roles
from backend.input_validation import validate_rules
from backend.models import (
    AcademicTerm,
    AuditLog,
    Batch,
    ConstraintRule,
    Course,
    CourseOffering,
    Department,
    Enrollment,
    ExamSlot,
    Instructor,
    InstructorAvailability,
    Room,
    SchedulingConfig,
    TimeSlot,
    TimetableEntry,
    User,
)
from backend.schemas import (
    AvailabilityBulkUpdate,
    AvailabilityItem,
    AvailabilityResponse,
    BatchCreate,
    BatchResponse,
    BatchUpdate,
    ConfigCreate,
    ConfigResponse,
    ConfigUpdate,
    ConstraintRuleInput,
    ConstraintRuleResponse,
    ConstraintRulesUpdatePayload,
    CourseCreate,
    CourseResponse,
    CourseUpdate,
    DepartmentCreate,
    DepartmentResponse,
    DepartmentUpdate,
    EnrollmentCreate,
    EnrollmentResponse,
    ExamSlotCreate,
    ExamSlotResponse,
    ExamSlotUpdate,
    InstructorCreate,
    InstructorResponse,
    InstructorUpdate,
    OfferingCreate,
    OfferingResponse,
    OfferingUpdate,
    RoomCreate,
    RoomResponse,
    RoomUpdate,
    SlotGridGenerateRequest,
    TermCreate,
    TermResponse,
    TermUpdate,
    TimeSlotCreate,
    TimeSlotResponse,
    TimeSlotUpdate,
)
from engine.models import (
    DEFAULT_SLOT_MIN,
    MANDATORY_EXAM_RULES,
    MANDATORY_TIMETABLE_RULES,
)

router = APIRouter(tags=["Master Data & Configuration"])

MANDATORY_RULES_ALL: frozenset[str] = MANDATORY_TIMETABLE_RULES | MANDATORY_EXAM_RULES

DEFAULT_TIMETABLE_CATALOGUE: tuple[tuple[str, str, bool, int, int | None], ...] = (
    ("H01", "Hard", True, 0, None),
    ("H02", "Hard", True, 0, None),
    ("H03", "Hard", True, 0, None),
    ("H04", "Hard", True, 0, None),
    ("H05", "Hard", True, 0, None),
    ("H06", "Hard", True, 0, None),
    ("H07", "Hard", True, 0, None),
    ("H08", "Hard", True, 0, None),
    ("H09", "Hard", True, 0, None),
    ("H10", "Hard", True, 0, None),
    ("S01", "Soft", True, 5, None),
    ("S02", "Soft", True, 5, None),
    ("S03", "Soft", True, 5, 5),
    ("S04", "Soft", True, 5, 3),
    ("S05", "Soft", True, 5, None),
    ("S06", "Soft", True, 5, None),
)

DEFAULT_EXAM_CATALOGUE: tuple[tuple[str, str, bool, int, int | None], ...] = (
    ("E01", "Hard", True, 0, None),
    ("E02", "Hard", True, 0, 2),
    ("E03", "Hard", True, 0, None),
    ("E04", "Hard", True, 0, None),
    ("E05", "Hard", True, 0, None),
    ("ES01", "Soft", True, 8, None),
    ("ES02", "Soft", True, 5, None),
    ("ES03", "Soft", True, 4, None),
)


def _parse_time_str(val: str | time) -> time:
    if isinstance(val, time):
        return val
    parts = [int(p) for p in str(val).strip().split(":")]
    if len(parts) == 2:
        return time(parts[0], parts[1])
    if len(parts) == 3:
        return time(parts[0], parts[1], parts[2])
    raise ValueError(f"Invalid time string: {val!r}. Expected HH:MM or HH:MM:SS.")


def _fmt_time(val: time) -> str:
    return val.strftime("%H:%M")


def _fmt_dt(val: datetime | None) -> str:
    if val is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if val.tzinfo is not None:
        val = val.astimezone(timezone.utc).replace(tzinfo=None)
    return val.strftime("%Y-%m-%dT%H:%M:%SZ")


def _serialize_term(term: AcademicTerm) -> TermResponse:
    return TermResponse(
        term_id=term.term_id,
        name=term.name,
        start_date=term.start_date.isoformat(),
        end_date=term.end_date.isoformat(),
        status=term.status,
    )


def _serialize_slot(slot: TimeSlot) -> TimeSlotResponse:
    return TimeSlotResponse(
        slot_id=slot.slot_id,
        term_id=slot.term_id,
        day_of_week=slot.day_of_week,
        slot_index=slot.slot_index,
        start_time=_fmt_time(slot.start_time),
        end_time=_fmt_time(slot.end_time),
        is_blocked=bool(slot.is_blocked),
        block_reason=slot.block_reason,
    )


def _serialize_exam_slot(es: ExamSlot) -> ExamSlotResponse:
    return ExamSlotResponse(
        exam_slot_id=es.exam_slot_id,
        term_id=es.term_id,
        exam_date=es.exam_date.isoformat(),
        start_time=_fmt_time(es.start_time),
        end_time=_fmt_time(es.end_time),
        label=es.label,
    )


def _serialize_offering(db: Session, off: CourseOffering) -> OfferingResponse:
    course = db.get(Course, off.course_id)
    first_slot = db.scalar(
        select(TimeSlot).where(TimeSlot.term_id == off.term_id).order_by(TimeSlot.slot_id)
    )
    slot_min = DEFAULT_SLOT_MIN
    if first_slot is not None:
        diff = (
            first_slot.end_time.hour * 60
            + first_slot.end_time.minute
            - (first_slot.start_time.hour * 60 + first_slot.start_time.minute)
        )
        if diff > 0:
            slot_min = diff

    req_lec = (
        math.ceil((course.lecture_hours * 60) / slot_min)
        if course is not None and course.lecture_hours > 0
        else 0
    )
    req_lab = (
        math.ceil((course.lab_hours * 60) / slot_min)
        if course is not None and course.lab_hours > 0
        else 0
    )
    return OfferingResponse(
        offering_id=off.offering_id,
        term_id=off.term_id,
        course_id=off.course_id,
        batch_id=off.batch_id,
        instructor_id=off.instructor_id,
        enrolled_count=off.enrolled_count,
        required_lecture_sessions=req_lec,
        required_lab_slots=req_lab,
    )


def _serialize_config(db: Session, cfg: SchedulingConfig) -> ConfigResponse:
    rules = db.scalars(
        select(ConstraintRule)
        .where(ConstraintRule.config_id == cfg.config_id)
        .order_by(ConstraintRule.rule_id)
    ).all()
    return ConfigResponse(
        config_id=cfg.config_id,
        term_id=cfg.term_id,
        schedule_type=cfg.schedule_type,
        name=cfg.name,
        solver_time_limit_s=cfg.solver_time_limit_s,
        random_seed=cfg.random_seed,
        created_by=cfg.created_by,
        created_at=_fmt_dt(cfg.created_at),
        rules=[ConstraintRuleResponse.model_validate(r) for r in rules],
    )


# ============================================================================
# Departments (`/departments`)
# ============================================================================
@router.get("/departments", response_model=list[DepartmentResponse])
def list_departments(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator", "Faculty", "Student")
    ),
) -> list[Department]:
    return list(db.scalars(select(Department).order_by(Department.department_id)).all())


@router.post(
    "/departments",
    response_model=DepartmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_department(
    payload: DepartmentCreate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> Department:
    dept = Department(code=payload.code.strip(), name=payload.name.strip())
    db.add(dept)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Department with code '{payload.code}' already exists.",
        ) from exc
    db.refresh(dept)
    return dept


@router.put("/departments/{department_id}", response_model=DepartmentResponse)
def update_department(
    department_id: int,
    payload: DepartmentUpdate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> Department:
    dept = db.get(Department, department_id)
    if dept is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Department {department_id} not found.",
        )
    if payload.code is not None:
        dept.code = payload.code.strip()
    if payload.name is not None:
        dept.name = payload.name.strip()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Department code already exists.",
        ) from exc
    db.refresh(dept)
    return dept


# ============================================================================
# Courses (`/courses` — FR-2.1, FR-2.2, FR-2.11, FR-2.12)
# ============================================================================
@router.get("/courses", response_model=list[CourseResponse])
def list_courses(
    search: str | None = Query(default=None),
    department_id: int | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator", "Faculty", "Student")
    ),
) -> list[Course]:
    stmt = select(Course)
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(Course.course_code.ilike(pattern), Course.title.ilike(pattern))
        )
    if department_id is not None:
        stmt = stmt.where(Course.department_id == department_id)
    if is_active is not None:
        stmt = stmt.where(Course.is_active == is_active)

    stmt = (
        stmt.order_by(Course.course_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(db.scalars(stmt).all())


@router.get("/courses/{course_id}", response_model=CourseResponse)
def get_course(
    course_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator", "Faculty", "Student")
    ),
) -> Course:
    course = db.get(Course, course_id)
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course {course_id} not found.",
        )
    return course


@router.post("/courses", response_model=CourseResponse, status_code=status.HTTP_201_CREATED)
def create_course(
    payload: CourseCreate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> Course:
    if db.get(Department, payload.department_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Department {payload.department_id} does not exist.",
        )
    course = Course(
        course_code=payload.course_code.strip(),
        title=payload.title.strip(),
        department_id=payload.department_id,
        credit_hours=payload.credit_hours,
        lecture_hours=payload.lecture_hours,
        lab_hours=payload.lab_hours,
        is_active=payload.is_active,
    )
    db.add(course)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Course with course_code '{payload.course_code}' already exists.",
        ) from exc
    db.refresh(course)
    return course


def _apply_course_update(db: Session, course_id: int, payload: CourseUpdate) -> Course:
    course = db.get(Course, course_id)
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course {course_id} not found.",
        )
    if payload.course_code is not None:
        course.course_code = payload.course_code.strip()
    if payload.title is not None:
        course.title = payload.title.strip()
    if payload.department_id is not None:
        course.department_id = payload.department_id
    if payload.credit_hours is not None:
        course.credit_hours = payload.credit_hours
    if payload.lecture_hours is not None:
        course.lecture_hours = payload.lecture_hours
    if payload.lab_hours is not None:
        course.lab_hours = payload.lab_hours
    if payload.is_active is not None:
        course.is_active = payload.is_active

    if course.lecture_hours + course.lab_hours <= 0:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Total weekly contact hours (lecture_hours + lab_hours) must be > 0 (FR-2.2).",
        )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Course update violated uniqueness or foreign-key constraints.",
        ) from exc
    db.refresh(course)
    return course


@router.put("/courses/{course_id}", response_model=CourseResponse)
def update_course(
    course_id: int,
    payload: CourseUpdate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> Course:
    return _apply_course_update(db, course_id, payload)


@router.put("/courses", response_model=CourseResponse)
def update_course_from_body(
    payload: CourseUpdate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> Course:
    if payload.course_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="course_id is required when calling PUT /courses.",
        )
    return _apply_course_update(db, payload.course_id, payload)


@router.delete("/courses/{course_id}", response_model=CourseResponse)
def deactivate_course(
    course_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> Course:
    """Soft-deactivate a course instead of permanently deleting it (`FR-2.11`, `DB-5`)."""
    course = db.get(Course, course_id)
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course {course_id} not found.",
        )
    course.is_active = False
    db.commit()
    db.refresh(course)
    return course


# ============================================================================
# Instructors & Availability (`/instructors` — FR-2.3, FR-3.1..FR-3.4)
# ============================================================================
@router.get("/instructors", response_model=list[InstructorResponse])
def list_instructors(
    search: str | None = Query(default=None),
    department_id: int | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator", "Faculty", "Student")
    ),
) -> list[Instructor]:
    stmt = select(Instructor)
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(Instructor.full_name.ilike(pattern), Instructor.email.ilike(pattern))
        )
    if department_id is not None:
        stmt = stmt.where(Instructor.department_id == department_id)
    if is_active is not None:
        stmt = stmt.where(Instructor.is_active == is_active)

    stmt = (
        stmt.order_by(Instructor.instructor_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(db.scalars(stmt).all())


@router.get("/instructors/{instructor_id}", response_model=InstructorResponse)
def get_instructor(
    instructor_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator", "Faculty", "Student")
    ),
) -> Instructor:
    inst = db.get(Instructor, instructor_id)
    if inst is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instructor {instructor_id} not found.",
        )
    return inst


@router.post(
    "/instructors",
    response_model=InstructorResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_instructor(
    payload: InstructorCreate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> Instructor:
    if db.get(Department, payload.department_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Department {payload.department_id} does not exist.",
        )
    inst = Instructor(
        department_id=payload.department_id,
        full_name=payload.full_name.strip(),
        email=payload.email.strip(),
        max_daily_hours=payload.max_daily_hours,
        max_weekly_hours=payload.max_weekly_hours,
        is_active=payload.is_active,
    )
    db.add(inst)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Instructor with email '{payload.email}' already exists.",
        ) from exc
    db.refresh(inst)
    return inst


def _apply_instructor_update(
    db: Session, instructor_id: int, payload: InstructorUpdate
) -> Instructor:
    inst = db.get(Instructor, instructor_id)
    if inst is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instructor {instructor_id} not found.",
        )
    if payload.department_id is not None:
        inst.department_id = payload.department_id
    if payload.full_name is not None:
        inst.full_name = payload.full_name.strip()
    if payload.email is not None:
        inst.email = payload.email.strip()
    if payload.max_daily_hours is not None:
        inst.max_daily_hours = payload.max_daily_hours
    if payload.max_weekly_hours is not None:
        inst.max_weekly_hours = payload.max_weekly_hours
    if payload.is_active is not None:
        inst.is_active = payload.is_active

    if inst.max_weekly_hours < inst.max_daily_hours:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="max_weekly_hours must be >= max_daily_hours (FR-2.3).",
        )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Instructor update violated uniqueness or foreign-key constraints.",
        ) from exc
    db.refresh(inst)
    return inst


@router.put("/instructors/{instructor_id}", response_model=InstructorResponse)
def update_instructor(
    instructor_id: int,
    payload: InstructorUpdate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> Instructor:
    return _apply_instructor_update(db, instructor_id, payload)


@router.put("/instructors", response_model=InstructorResponse)
def update_instructor_from_body(
    payload: InstructorUpdate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> Instructor:
    if payload.instructor_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="instructor_id is required when calling PUT /instructors.",
        )
    return _apply_instructor_update(db, payload.instructor_id, payload)


@router.delete("/instructors/{instructor_id}", response_model=InstructorResponse)
def deactivate_instructor(
    instructor_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> Instructor:
    inst = db.get(Instructor, instructor_id)
    if inst is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instructor {instructor_id} not found.",
        )
    inst.is_active = False
    db.commit()
    db.refresh(inst)
    return inst


@router.get(
    "/instructors/{instructor_id}/availability",
    response_model=list[AvailabilityResponse],
)
def get_instructor_availability(
    instructor_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Faculty", "Approver", "Administrator")
    ),
) -> list[InstructorAvailability]:
    if _user.role == 'Faculty' and _user.instructor_id != instructor_id:
        raise HTTPException(403,'Faculty may only read their linked instructor availability.')
    if db.get(Instructor, instructor_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instructor {instructor_id} not found.",
        )
    return list(
        db.scalars(
            select(InstructorAvailability)
            .where(InstructorAvailability.instructor_id == instructor_id)
            .order_by(InstructorAvailability.slot_id)
        ).all()
    )


@router.put(
    "/instructors/{instructor_id}/availability",
    response_model=list[AvailabilityResponse],
)
def update_instructor_availability(
    instructor_id: int,
    payload: AvailabilityBulkUpdate | list[AvailabilityItem] = Body(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles("Coordinator", "Faculty")),
) -> list[InstructorAvailability]:
    if db.get(Instructor, instructor_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instructor {instructor_id} not found.",
        )
    if (
        user.role == "Faculty"
        and user.instructor_id != instructor_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Faculty members can only edit their own availability (FR-3.1).",
        )

    items = payload.slots if isinstance(payload, AvailabilityBulkUpdate) else payload
    for item in items:
        if db.get(TimeSlot, item.slot_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"TimeSlot {item.slot_id} does not exist.",
            )
        existing = db.scalar(
            select(InstructorAvailability).where(
                InstructorAvailability.instructor_id == instructor_id,
                InstructorAvailability.slot_id == item.slot_id,
            )
        )
        if existing is not None:
            existing.is_available = item.is_available
        else:
            db.add(
                InstructorAvailability(
                    instructor_id=instructor_id,
                    slot_id=item.slot_id,
                    is_available=item.is_available,
                )
            )

    db.commit()
    return list(
        db.scalars(
            select(InstructorAvailability)
            .where(InstructorAvailability.instructor_id == instructor_id)
            .order_by(InstructorAvailability.slot_id)
        ).all()
    )


# ============================================================================
# Rooms (`/rooms` — FR-2.4, FR-2.11)
# ============================================================================
@router.get("/rooms", response_model=list[RoomResponse])
def list_rooms(
    search: str | None = Query(default=None),
    room_type: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator", "Faculty", "Student")
    ),
) -> list[Room]:
    stmt = select(Room)
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(Room.room_code.ilike(pattern), Room.building.ilike(pattern))
        )
    if room_type:
        stmt = stmt.where(Room.room_type == room_type)
    if is_active is not None:
        stmt = stmt.where(Room.is_active == is_active)

    stmt = (
        stmt.order_by(Room.room_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(db.scalars(stmt).all())


@router.get("/rooms/{room_id}", response_model=RoomResponse)
def get_room(
    room_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator", "Faculty", "Student")
    ),
) -> Room:
    room = db.get(Room, room_id)
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Room {room_id} not found.",
        )
    return room


@router.post("/rooms", response_model=RoomResponse, status_code=status.HTTP_201_CREATED)
def create_room(
    payload: RoomCreate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> Room:
    room = Room(
        room_code=payload.room_code.strip(),
        building=payload.building.strip(),
        capacity=payload.capacity,
        room_type=payload.room_type,
        is_active=payload.is_active,
    )
    db.add(room)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Room with room_code '{payload.room_code}' already exists.",
        ) from exc
    db.refresh(room)
    return room


def _apply_room_update(db: Session, room_id: int, payload: RoomUpdate) -> Room:
    room = db.get(Room, room_id)
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Room {room_id} not found.",
        )
    if payload.room_code is not None:
        room.room_code = payload.room_code.strip()
    if payload.building is not None:
        room.building = payload.building.strip()
    if payload.capacity is not None:
        room.capacity = payload.capacity
    if payload.room_type is not None:
        room.room_type = payload.room_type
    if payload.is_active is not None:
        room.is_active = payload.is_active

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Room update violated uniqueness constraints.",
        ) from exc
    db.refresh(room)
    return room


@router.put("/rooms/{room_id}", response_model=RoomResponse)
def update_room(
    room_id: int,
    payload: RoomUpdate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> Room:
    return _apply_room_update(db, room_id, payload)


@router.put("/rooms", response_model=RoomResponse)
def update_room_from_body(
    payload: RoomUpdate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> Room:
    if payload.room_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="room_id is required when calling PUT /rooms.",
        )
    return _apply_room_update(db, payload.room_id, payload)


@router.delete("/rooms/{room_id}", response_model=RoomResponse)
def deactivate_room(
    room_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> Room:
    room = db.get(Room, room_id)
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Room {room_id} not found.",
        )
    room.is_active = False
    db.commit()
    db.refresh(room)
    return room


# ============================================================================
# Batches (`/batches` — FR-2.5, FR-2.11)
# ============================================================================
@router.get("/batches", response_model=list[BatchResponse])
def list_batches(
    search: str | None = Query(default=None),
    department_id: int | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator", "Faculty", "Student")
    ),
) -> list[Batch]:
    stmt = select(Batch)
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(Batch.program_code.ilike(pattern), Batch.section.ilike(pattern))
        )
    if department_id is not None:
        stmt = stmt.where(Batch.department_id == department_id)
    if is_active is not None:
        stmt = stmt.where(Batch.is_active == is_active)

    stmt = (
        stmt.order_by(Batch.batch_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(db.scalars(stmt).all())


@router.get("/batches/{batch_id}", response_model=BatchResponse)
def get_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator", "Faculty", "Student")
    ),
) -> Batch:
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch {batch_id} not found.",
        )
    return batch


@router.post("/batches", response_model=BatchResponse, status_code=status.HTTP_201_CREATED)
def create_batch(
    payload: BatchCreate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> Batch:
    if db.get(Department, payload.department_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Department {payload.department_id} does not exist.",
        )
    batch = Batch(
        department_id=payload.department_id,
        program_code=payload.program_code.strip(),
        batch_year=payload.batch_year,
        section=payload.section.strip(),
        strength=payload.strength,
        is_active=payload.is_active,
    )
    db.add(batch)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Batch '{payload.program_code} {payload.batch_year} {payload.section}' "
                "already exists."
            ),
        ) from exc
    db.refresh(batch)
    return batch


def _apply_batch_update(db: Session, batch_id: int, payload: BatchUpdate) -> Batch:
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch {batch_id} not found.",
        )
    if payload.department_id is not None:
        batch.department_id = payload.department_id
    if payload.program_code is not None:
        batch.program_code = payload.program_code.strip()
    if payload.batch_year is not None:
        batch.batch_year = payload.batch_year
    if payload.section is not None:
        batch.section = payload.section.strip()
    if payload.strength is not None:
        batch.strength = payload.strength
    if payload.is_active is not None:
        batch.is_active = payload.is_active

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Batch update violated uniqueness or foreign-key constraints.",
        ) from exc
    db.refresh(batch)
    return batch


@router.put("/batches/{batch_id}", response_model=BatchResponse)
def update_batch(
    batch_id: int,
    payload: BatchUpdate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> Batch:
    return _apply_batch_update(db, batch_id, payload)


@router.put("/batches", response_model=BatchResponse)
def update_batch_from_body(
    payload: BatchUpdate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> Batch:
    if payload.batch_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="batch_id is required when calling PUT /batches.",
        )
    return _apply_batch_update(db, payload.batch_id, payload)


@router.delete("/batches/{batch_id}", response_model=BatchResponse)
def deactivate_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> Batch:
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch {batch_id} not found.",
        )
    batch.is_active = False
    db.commit()
    db.refresh(batch)
    return batch


# ============================================================================
# Academic Terms, Time Slots & Exam Slots (`/terms` — FR-2.6, FR-2.7, FR-5.7)
# ============================================================================
@router.get("/terms", response_model=list[TermResponse])
def list_terms(
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator", "Faculty", "Student")
    ),
) -> list[TermResponse]:
    stmt = select(AcademicTerm)
    if status_filter:
        stmt = stmt.where(AcademicTerm.status == status_filter)
    terms = db.scalars(stmt.order_by(AcademicTerm.term_id)).all()
    return [_serialize_term(t) for t in terms]


@router.get("/terms/{term_id}", response_model=TermResponse)
def get_term(
    term_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator", "Faculty", "Student")
    ),
) -> TermResponse:
    term = db.get(AcademicTerm, term_id)
    if term is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Term {term_id} not found.",
        )
    return _serialize_term(term)


@router.post("/terms", response_model=TermResponse, status_code=status.HTTP_201_CREATED)
def create_term(
    payload: TermCreate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> TermResponse:
    if payload.status == "Active":
        active_term = db.scalar(
            select(AcademicTerm).where(AcademicTerm.status == "Active")
        )
        if active_term is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Term '{active_term.name}' is already Active. "
                    "At most one term may be Active at a time (FR-2.6)."
                ),
            )
    term = AcademicTerm(
        name=payload.name.strip(),
        start_date=payload.start_date,
        end_date=payload.end_date,
        status=payload.status,
    )
    db.add(term)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Term with name '{payload.name}' already exists or violates constraints.",
        ) from exc
    db.refresh(term)
    return _serialize_term(term)


def _apply_term_update(db: Session, term_id: int, payload: TermUpdate) -> TermResponse:
    term = db.get(AcademicTerm, term_id)
    if term is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Term {term_id} not found.",
        )
    if payload.name is not None:
        term.name = payload.name.strip()
    if payload.start_date is not None:
        term.start_date = payload.start_date
    if payload.end_date is not None:
        term.end_date = payload.end_date
    if term.end_date <= term.start_date:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_date must be strictly after start_date (FR-2.6).",
        )
    if payload.status is not None and payload.status != term.status:
        if payload.status == "Active":
            other_active = db.scalar(
                select(AcademicTerm).where(
                    AcademicTerm.status == "Active",
                    AcademicTerm.term_id != term_id,
                )
            )
            if other_active is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Term '{other_active.name}' is already Active (FR-2.6).",
                )
        term.status = payload.status

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Term update violated uniqueness or date constraints.",
        ) from exc
    db.refresh(term)
    return _serialize_term(term)


@router.put("/terms/{term_id}", response_model=TermResponse)
def update_term(
    term_id: int,
    payload: TermUpdate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> TermResponse:
    return _apply_term_update(db, term_id, payload)


@router.put("/terms", response_model=TermResponse)
def update_term_from_body(
    payload: TermUpdate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> TermResponse:
    if payload.term_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="term_id is required when calling PUT /terms.",
        )
    return _apply_term_update(db, payload.term_id, payload)


@router.get("/terms/{term_id}/slots", response_model=list[TimeSlotResponse])
def list_term_slots(
    term_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator", "Faculty", "Student")
    ),
) -> list[TimeSlotResponse]:
    if db.get(AcademicTerm, term_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Term {term_id} not found.",
        )
    slots = db.scalars(
        select(TimeSlot)
        .where(TimeSlot.term_id == term_id)
        .order_by(TimeSlot.day_of_week, TimeSlot.slot_index)
    ).all()
    return [_serialize_slot(s) for s in slots]


def _check_weekly_candidate(db: Session, term_id: int, candidates: list, replacing: set[int] | None = None) -> None:
    # Use the same lock order as generation/publication and bulk grid saves.
    from backend.schedule_integrity import lock_inputs
    lock_inputs(db)
    # Serialize same-term mutations on databases supporting row locks. Validate
    # before attaching/mutating ORM rows, so a rejected bulk operation is atomic.
    db.scalar(select(AcademicTerm).where(AcademicTerm.term_id == term_id).with_for_update())
    existing = list(db.scalars(select(TimeSlot).where(TimeSlot.term_id == term_id)).all())
    duration = None
    if existing:
        try:
            start, end = slot_interval(existing[0])
            duration = end - start
        except ValueError:
            pass  # The complete grid below will report the invalid stored row.
    issues = validate_weekly_grid(
        [s for s in existing if s.slot_id not in (replacing or set())] + candidates,
        allow_unassigned_ids=True, expected_duration_minutes=duration,
    )
    if issues:
        code = 409 if any(i.kind in {"overlap", "duplicate_index"} for i in issues) else 422
        raise HTTPException(status_code=code, detail=" ".join(i.description for i in issues))


@router.post(
    "/terms/{term_id}/slots",
    response_model=TimeSlotResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_term_slot(
    term_id: int,
    payload: TimeSlotCreate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> TimeSlotResponse:
    if payload.term_id is not None and payload.term_id!=term_id:raise HTTPException(422,'Body term_id must match the path term.')
    if db.get(AcademicTerm, term_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Term {term_id} not found.",
        )
    if payload.is_blocked and (not payload.block_reason or not payload.block_reason.strip()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="block_reason is required when is_blocked is true (FR-2.7).",
        )
    start_t = _parse_time_str(payload.start_time)
    end_t = _parse_time_str(payload.end_time)
    if end_t <= start_t:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_time must be after start_time.",
        )
    slot = TimeSlot(
        term_id=term_id,
        day_of_week=payload.day_of_week,
        slot_index=payload.slot_index,
        start_time=start_t,
        end_time=end_t,
        is_blocked=payload.is_blocked,
        block_reason=payload.block_reason.strip() if payload.block_reason else None,
    )
    _check_weekly_candidate(db, term_id, [slot])
    db.add(slot)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Slot already exists for this (term_id, day_of_week, slot_index).",
        ) from exc
    db.refresh(slot)
    return _serialize_slot(slot)


def _build_slot_grid(term_id: int, payload: SlotGridGenerateRequest) -> list[TimeSlot]:
    """Build detached candidates; callers validate the whole grid before writing."""
    first_t = _parse_time_str(payload.first_start_time)
    base_minutes = first_t.hour * 60 + first_t.minute
    if base_minutes + payload.slot_length_min * payload.slots_per_day >= 1440:
        raise HTTPException(status_code=422, detail="Weekly slots must end before midnight on the same day.")
    created_slots: list[TimeSlot] = []

    for day in sorted(set(payload.working_days)):
        for idx in range(1, payload.slots_per_day + 1):
            s_min = base_minutes + (idx - 1) * payload.slot_length_min
            e_min = s_min + payload.slot_length_min
            is_blk = idx in payload.blocked_slot_indices
            slot = TimeSlot(
                term_id=term_id,
                day_of_week=day,
                slot_index=idx,
                start_time=time(s_min // 60, s_min % 60),
                end_time=time(e_min // 60, e_min % 60),
                is_blocked=is_blk,
                block_reason=payload.block_reason if is_blk else None,
            )
            created_slots.append(slot)

    return created_slots


@router.post(
    "/terms/{term_id}/slots/generate",
    response_model=list[TimeSlotResponse],
    status_code=status.HTTP_201_CREATED,
)
def generate_term_slot_grid(
    term_id: int,
    payload: SlotGridGenerateRequest,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> list[TimeSlotResponse]:
    """Create new slots; existing indexes remain conflicts on the POST endpoint."""
    if db.get(AcademicTerm, term_id) is None:
        raise HTTPException(404, f"Term {term_id} not found.")
    created_slots = _build_slot_grid(term_id, payload)
    _check_weekly_candidate(db, term_id, created_slots)
    db.add_all(created_slots)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Slot grid overlaps existing slots in this term.",
        ) from exc

    for s in created_slots:
        db.refresh(s)
    return [_serialize_slot(s) for s in created_slots]


@router.put("/terms/{term_id}/slots/generate", response_model=list[TimeSlotResponse])
def save_term_slot_grid(
    term_id: int,
    payload: SlotGridGenerateRequest,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> list[TimeSlotResponse]:
    """Atomically save a grid without replacing IDs, deleting slots or appending duplicates."""
    from backend.schedule_integrity import lock_inputs

    candidates = _build_slot_grid(term_id, payload)
    lock_inputs(db)
    if db.get(AcademicTerm, term_id) is None:
        raise HTTPException(404, f"Term {term_id} not found.")
    existing = list(db.scalars(select(TimeSlot).where(TimeSlot.term_id == term_id)).all())
    by_key = {(s.day_of_week, s.slot_index): s for s in existing}
    if len(by_key) != len(existing):
        raise HTTPException(409, "Stored grid contains duplicate weekday/index pairs; no slots were changed.")
    requested = {(s.day_of_week, s.slot_index) for s in candidates}
    if set(by_key) - requested:
        raise HTTPException(409, "Saving this grid would remove existing slots. Keep all existing working days and slot indexes; no slots were changed.")

    for candidate in candidates:
        old = by_key.get((candidate.day_of_week, candidate.slot_index))
        if old is not None:
            candidate.slot_id = old.slot_id
            # The grid form edits clock windows, not individual break settings.
            if "blocked_slot_indices" not in payload.model_fields_set:
                candidate.is_blocked, candidate.block_reason = old.is_blocked, old.block_reason

    # Exclude rows being updated, not the rest of the grid. B002's validator and
    # the existing fixed duration still apply before any persistent row changes.
    _check_weekly_candidate(db, term_id, candidates, {s.slot_id for s in existing})
    saved = []
    for candidate in candidates:
        old = by_key.get((candidate.day_of_week, candidate.slot_index))
        if old is None:
            db.add(candidate)
            saved.append(candidate)
        else:
            for field in ("start_time", "end_time", "is_blocked", "block_reason"):
                setattr(old, field, getattr(candidate, field))
            saved.append(old)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Slot grid conflicts with existing slots; no changes were saved.") from exc
    for slot in saved:
        db.refresh(slot)
    return [_serialize_slot(slot) for slot in saved]


@router.put("/terms/{term_id}/slots/{slot_id}", response_model=TimeSlotResponse)
def update_term_slot(
    term_id: int,
    slot_id: int,
    payload: TimeSlotUpdate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> TimeSlotResponse:
    if payload.slot_id is not None and payload.slot_id!=slot_id:raise HTTPException(422,'Body slot_id must match the path.')
    slot = db.get(TimeSlot, slot_id)
    if slot is None or slot.term_id != term_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"TimeSlot {slot_id} in term {term_id} not found.",
        )
    values = {name: getattr(slot, name) for name in (
        "slot_id", "term_id", "day_of_week", "slot_index", "start_time", "end_time", "is_blocked", "block_reason"
    )}
    for name, value in payload.model_dump(exclude_unset=True).items():
        if value is not None and name != "slot_id":
            values[name] = _parse_time_str(value) if name in {"start_time", "end_time"} else value
    values["block_reason"] = (values["block_reason"] or "").strip() or None
    if not values["is_blocked"]:
        values["block_reason"] = None
    elif not values["block_reason"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="block_reason is required when is_blocked is true (FR-2.7).",
        )
    _check_weekly_candidate(db, term_id, [SimpleNamespace(**values)], {slot_id})
    for name, value in values.items():
        setattr(slot, name, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Slot grid conflicts with existing slots.") from exc
    db.refresh(slot)
    return _serialize_slot(slot)


@router.get("/terms/{term_id}/exam-slots", response_model=list[ExamSlotResponse])
def list_term_exam_slots(
    term_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator", "Faculty", "Student")
    ),
) -> list[ExamSlotResponse]:
    if db.get(AcademicTerm, term_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Term {term_id} not found.",
        )
    exam_slots = db.scalars(
        select(ExamSlot)
        .where(ExamSlot.term_id == term_id)
        .order_by(ExamSlot.exam_date, ExamSlot.start_time)
    ).all()
    return [_serialize_exam_slot(es) for es in exam_slots]


@router.post(
    "/terms/{term_id}/exam-slots",
    response_model=ExamSlotResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_term_exam_slot(
    term_id: int,
    payload: ExamSlotCreate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> ExamSlotResponse:
    """Create an exam session and reject overlapping sessions on the same date (`FR-5.7`)."""
    if payload.term_id is not None and payload.term_id!=term_id:raise HTTPException(422,'Body term_id must match the path term.')
    if db.get(AcademicTerm, term_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Term {term_id} not found.",
        )
    start_t = _parse_time_str(payload.start_time)
    end_t = _parse_time_str(payload.end_time)
    if end_t <= start_t:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_time must be after start_time.",
        )
    same_day_slots = db.scalars(
        select(ExamSlot).where(
            ExamSlot.term_id == term_id,
            ExamSlot.exam_date == payload.exam_date,
        )
    ).all()
    for existing in same_day_slots:
        if start_t < existing.end_time and existing.start_time < end_t:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Exam session { _fmt_time(start_t) }–{ _fmt_time(end_t) } overlaps "
                    f"existing session { _fmt_time(existing.start_time) }–{ _fmt_time(existing.end_time) } "
                    f"on {payload.exam_date.isoformat()} (FR-5.7)."
                ),
            )

    es = ExamSlot(
        term_id=term_id,
        exam_date=payload.exam_date,
        start_time=start_t,
        end_time=end_t,
        label=payload.label,
    )
    db.add(es)
    db.commit()
    db.refresh(es)
    return _serialize_exam_slot(es)


# ============================================================================
# Course Offerings & Enrollments (`/offerings`, `/enrollments` — FR-2.8..FR-2.11)
# ============================================================================
@router.get("/offerings", response_model=list[OfferingResponse])
def list_offerings(
    term_id: int | None = Query(default=None),
    course_id: int | None = Query(default=None),
    batch_id: int | None = Query(default=None),
    instructor_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator", "Faculty", "Student")
    ),
) -> list[OfferingResponse]:
    stmt = select(CourseOffering)
    if term_id is not None:
        stmt = stmt.where(CourseOffering.term_id == term_id)
    if course_id is not None:
        stmt = stmt.where(CourseOffering.course_id == course_id)
    if batch_id is not None:
        stmt = stmt.where(CourseOffering.batch_id == batch_id)
    if instructor_id is not None:
        stmt = stmt.where(CourseOffering.instructor_id == instructor_id)

    offerings = db.scalars(
        stmt.order_by(CourseOffering.offering_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [_serialize_offering(db, o) for o in offerings]


@router.get("/offerings/{offering_id}", response_model=OfferingResponse)
def get_offering(
    offering_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator", "Faculty", "Student")
    ),
) -> OfferingResponse:
    off = db.get(CourseOffering, offering_id)
    if off is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CourseOffering {offering_id} not found.",
        )
    return _serialize_offering(db, off)


@router.post(
    "/offerings",
    response_model=OfferingResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_offering(
    payload: OfferingCreate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> OfferingResponse:
    if db.get(AcademicTerm, payload.term_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AcademicTerm {payload.term_id} not found.",
        )
    if db.get(Course, payload.course_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course {payload.course_id} not found.",
        )
    if db.get(Batch, payload.batch_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch {payload.batch_id} not found.",
        )
    if db.get(Instructor, payload.instructor_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instructor {payload.instructor_id} not found.",
        )

    off = CourseOffering(
        term_id=payload.term_id,
        course_id=payload.course_id,
        batch_id=payload.batch_id,
        instructor_id=payload.instructor_id,
        enrolled_count=payload.enrolled_count,
    )
    db.add(off)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A course offering for this (term_id, course_id, batch_id) already exists "
                "(FR-2.8)."
            ),
        ) from exc
    db.refresh(off)
    return _serialize_offering(db, off)


def _apply_offering_update(
    db: Session, offering_id: int, payload: OfferingUpdate
) -> OfferingResponse:
    off = db.get(CourseOffering, offering_id)
    if off is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CourseOffering {offering_id} not found.",
        )
    if payload.term_id is not None:
        off.term_id = payload.term_id
    if payload.course_id is not None:
        off.course_id = payload.course_id
    if payload.batch_id is not None:
        off.batch_id = payload.batch_id
    if payload.instructor_id is not None:
        off.instructor_id = payload.instructor_id
    if payload.enrolled_count is not None:
        off.enrolled_count = payload.enrolled_count

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Offering update violated uniqueness or foreign-key constraints.",
        ) from exc
    db.refresh(off)
    return _serialize_offering(db, off)


@router.put("/offerings/{offering_id}", response_model=OfferingResponse)
def update_offering(
    offering_id: int,
    payload: OfferingUpdate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> OfferingResponse:
    return _apply_offering_update(db, offering_id, payload)


@router.put("/offerings", response_model=OfferingResponse)
def update_offering_from_body(
    payload: OfferingUpdate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> OfferingResponse:
    if payload.offering_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="offering_id is required when calling PUT /offerings.",
        )
    return _apply_offering_update(db, payload.offering_id, payload)


@router.delete("/offerings/{offering_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_offering(
    offering_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> None:
    off = db.get(CourseOffering, offering_id)
    if off is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CourseOffering {offering_id} not found.",
        )
    referenced = db.scalar(
        select(TimetableEntry).where(TimetableEntry.offering_id == offering_id)
    )
    if referenced is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"CourseOffering {offering_id} is referenced by an existing schedule "
                "and cannot be deleted (FR-2.11)."
            ),
        )
    db.delete(off)
    db.commit()


@router.get("/enrollments", response_model=list[EnrollmentResponse])
def list_enrollments(
    offering_id: int | None = Query(default=None),
    student_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator", "Faculty", "Student")
    ),
) -> list[Enrollment]:
    stmt = select(Enrollment)
    if offering_id is not None:
        stmt = stmt.where(Enrollment.offering_id == offering_id)
    if student_id is not None:
        stmt = stmt.where(Enrollment.student_id == student_id)
    return list(db.scalars(stmt.order_by(Enrollment.enrollment_id)).all())


@router.post(
    "/enrollments",
    response_model=EnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_enrollment(
    payload: EnrollmentCreate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> Enrollment:
    if db.get(CourseOffering, payload.offering_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CourseOffering {payload.offering_id} not found.",
        )
    student = db.get(User, payload.student_id)
    if student is None or student.role != "Student":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"User {payload.student_id} must be an existing user with role 'Student'.",
        )
    enr = Enrollment(offering_id=payload.offering_id, student_id=payload.student_id)
    db.add(enr)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Student is already enrolled in this course offering.",
        ) from exc
    db.refresh(enr)
    return enr


@router.delete("/enrollments/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_enrollment(
    enrollment_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> None:
    enr = db.get(Enrollment, enrollment_id)
    if enr is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Enrollment {enrollment_id} not found.",
        )
    db.delete(enr)
    db.commit()


# ============================================================================
# Configurations & Constraint Rules (`/configs`, `/configs/{id}/rules` — FR-5.1..FR-5.6)
# ============================================================================
@router.get("/configs", response_model=list[ConfigResponse])
def list_configs(
    term_id: int | None = Query(default=None),
    schedule_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator")
    ),
) -> list[ConfigResponse]:
    stmt = select(SchedulingConfig)
    if term_id is not None:
        stmt = stmt.where(SchedulingConfig.term_id == term_id)
    if schedule_type is not None:
        stmt = stmt.where(SchedulingConfig.schedule_type == schedule_type)
    configs = db.scalars(stmt.order_by(SchedulingConfig.config_id)).all()
    return [_serialize_config(db, c) for c in configs]


@router.get("/configs/{config_id}", response_model=ConfigResponse)
def get_config(
    config_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator")
    ),
) -> ConfigResponse:
    cfg = db.get(SchedulingConfig, config_id)
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SchedulingConfig {config_id} not found.",
        )
    return _serialize_config(db, cfg)


@router.post("/configs", response_model=ConfigResponse, status_code=status.HTTP_201_CREATED)
def create_config(
    payload: ConfigCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles("Coordinator")),
) -> ConfigResponse:
    if db.get(AcademicTerm, payload.term_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Term {payload.term_id} not found.",
        )
    if payload.rules is not None:validate_rules(payload.rules,payload.schedule_type)
    if payload.rules:
        for r in payload.rules:
            if r.rule_code in MANDATORY_RULES_ALL and not r.is_enabled:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Mandatory constraint '{r.rule_code}' cannot be disabled (FR-5.2).",
                )

    cfg = SchedulingConfig(
        term_id=payload.term_id,
        schedule_type=payload.schedule_type,
        name=payload.name.strip(),
        solver_time_limit_s=payload.solver_time_limit_s,
        random_seed=payload.random_seed,
        created_by=user.user_id,
    )
    db.add(cfg)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Config '{payload.name}' already exists for this term and schedule type.",
        ) from exc

    catalogue = DEFAULT_TIMETABLE_CATALOGUE if payload.schedule_type == 'Timetable' else DEFAULT_EXAM_CATALOGUE
    overrides={r.rule_code:r for r in payload.rules or []}
    for code,kind,enabled,weight,param in catalogue:
        rule=overrides.get(code)
        db.add(ConstraintRule(config_id=cfg.config_id,rule_code=code,rule_type=kind,
            is_enabled=rule.is_enabled if rule else enabled,weight=rule.weight if rule else weight,
            param_value=rule.param_value if rule else param))

    db.commit()
    db.refresh(cfg)
    return _serialize_config(db, cfg)


def _apply_config_update(
    db: Session, config_id: int, payload: ConfigUpdate
) -> ConfigResponse:
    from backend.schedule_integrity import lock_inputs
    lock_inputs(db)
    cfg = db.get(SchedulingConfig, config_id)
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SchedulingConfig {config_id} not found.",
        )
    if payload.rules is not None:
        validate_rules(payload.rules,cfg.schedule_type)
        _write_config_rules(db,cfg,payload.rules)
    if payload.name is not None:
        cfg.name = payload.name.strip()
    if payload.solver_time_limit_s is not None:
        cfg.solver_time_limit_s = payload.solver_time_limit_s
    if payload.random_seed is not None:
        cfg.random_seed = payload.random_seed

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Configuration update violated uniqueness constraints.",
        ) from exc
    db.refresh(cfg)
    return _serialize_config(db, cfg)


@router.put("/configs/{config_id}", response_model=ConfigResponse)
def update_config(
    config_id: int,
    payload: ConfigUpdate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> ConfigResponse:
    return _apply_config_update(db, config_id, payload)


@router.put("/configs", response_model=ConfigResponse)
def update_config_from_body(
    payload: ConfigUpdate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(require_roles("Coordinator")),
) -> ConfigResponse:
    if payload.config_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="config_id is required when calling PUT /configs.",
        )
    return _apply_config_update(db, payload.config_id, payload)


@router.get("/configs/{config_id}/rules", response_model=list[ConstraintRuleResponse])
def get_config_rules(
    config_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator")
    ),
) -> list[ConstraintRule]:
    if db.get(SchedulingConfig, config_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SchedulingConfig {config_id} not found.",
        )
    return list(
        db.scalars(
            select(ConstraintRule)
            .where(ConstraintRule.config_id == config_id)
            .order_by(ConstraintRule.rule_id)
        ).all()
    )


@router.put("/configs/{config_id}/rules", response_model=list[ConstraintRuleResponse])
def update_config_rules(
    config_id: int,
    payload: ConstraintRulesUpdatePayload | list[ConstraintRuleInput] = Body(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles("Coordinator")),
) -> list[ConstraintRule]:
    from backend.schedule_integrity import lock_inputs
    lock_inputs(db)
    cfg = db.get(SchedulingConfig, config_id)
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SchedulingConfig {config_id} not found.",
        )
    items = payload.rules if isinstance(payload, ConstraintRulesUpdatePayload) else payload

    validate_rules(items,cfg.schedule_type)
    _write_config_rules(db,cfg,items)
    db.add(AuditLog(user_id=user.user_id,action='CONFIG_CHANGE',entity_type='scheduling_configs',entity_id=config_id,details=f'Updated {len(items)} rules.'))
    db.commit()
    return list(db.scalars(select(ConstraintRule).where(ConstraintRule.config_id==config_id).order_by(ConstraintRule.rule_id)))


def _write_config_rules(db,cfg,items):
    config_id=cfg.config_id
    for item in items:
        if item.rule_code in MANDATORY_RULES_ALL and not item.is_enabled:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Mandatory constraint '{item.rule_code}' cannot be disabled (FR-5.2).",
            )
        existing = db.scalar(
            select(ConstraintRule).where(
                ConstraintRule.config_id == config_id,
                ConstraintRule.rule_code == item.rule_code,
            )
        )
        inferred_type = (
            item.rule_type
            if item.rule_type is not None
            else ("Soft" if item.rule_code.startswith(("S", "ES")) else "Hard")
        )
        if existing is not None:
            existing.is_enabled = item.is_enabled
            existing.weight = item.weight
            existing.param_value = item.param_value
            existing.rule_type = inferred_type
        else:
            db.add(
                ConstraintRule(
                    config_id=config_id,
                    rule_code=item.rule_code,
                    rule_type=inferred_type,
                    is_enabled=item.is_enabled,
                    weight=item.weight,
                    param_value=item.param_value,
                )
            )



@router.delete('/configs/{config_id}',status_code=204)
def delete_config(config_id:int,db:Session=Depends(get_db),user:CurrentUser=Depends(require_roles('Coordinator'))):
    from backend.schedule_integrity import lock_inputs
    from backend.models import Schedule
    lock_inputs(db)
    cfg=db.get(SchedulingConfig,config_id)
    if cfg is None:raise HTTPException(404,'Configuration not found.')
    if db.scalar(select(Schedule.schedule_id).where(Schedule.config_id==config_id).limit(1)) is not None:
        raise HTTPException(409,'A schedule references this configuration. Clone it instead; historical configurations cannot be deleted.')
    for rule in db.scalars(select(ConstraintRule).where(ConstraintRule.config_id==config_id)).all():db.delete(rule)
    db.flush()
    db.delete(cfg)
    db.commit()


@router.put('/terms/{term_id}/exam-slots/{slot_id}',response_model=ExamSlotResponse)
def update_exam_slot(term_id:int,slot_id:int,payload:ExamSlotUpdate,db:Session=Depends(get_db),user:CurrentUser=Depends(require_roles('Coordinator'))):
    from backend.schedule_integrity import lock_inputs
    lock_inputs(db)
    row=db.get(ExamSlot,slot_id)
    if row is None or row.term_id!=term_id:raise HTTPException(404,'Exam slot not found in this term.')
    if payload.exam_slot_id is not None and payload.exam_slot_id!=slot_id:raise HTTPException(422,'Body exam_slot_id must match the path.')
    for key,value in payload.model_dump(exclude_unset=True,exclude={'exam_slot_id'}).items():
        if value is None and key!='label':raise HTTPException(422,'Required exam fields cannot be null.')
        setattr(row,key,_parse_time_str(value) if key in {'start_time','end_time'} else value)
    db.commit();return _serialize_exam_slot(row)
