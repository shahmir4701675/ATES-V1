"""FastAPI routes for Schedule Generation, Status Polling, Views, Conflicts, and Manual Moves.

Implements SRS Table 9 & Figures 7–9:
- `POST /schedules/generate`: Creates a new `Schedule` version with `status='Generating'`,
  dispatches the timetable (`solve_timetable`) or exam (`schedule_exams`) engine in a
  background worker, and saves all results in a single database transaction (`FR-6.2`,
  `FR-6.8`, `FR-7.7`, `DB-6`, `SAF-2`).
- `GET /schedules/{id}/status`: Polls the progress and statistics of a schedule run.
- `GET /schedules/{id}/entries`: Returns enriched timetable and exam entries with filter parameters
  (`FR-10.1`–`FR-10.6`, `docs/data-contract.md` Section 10.3).
- `GET /schedules/{id}/conflicts`: Returns the conflict report (`FR-8.1`, `FR-8.2`).
- `PUT /schedules/{id}/entries/{entry_id}`: Re-validates a manual move or lock change against all
  enabled hard constraints (`H01`–`H10` or `E01`–`E05`); returns HTTP `409 Conflict` naming the
  violated constraint if invalid, or saves the change and marks `is_manual_override = True`
  in one transaction (`FR-8.3`–`FR-8.6`, `SAF-4`).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.adapter import (
    _next_schedule_version,
    load_term_dataset,
    save_exam_result,
    save_timetable_result,
)
from backend.database import session_scope
from backend.dependencies import (
    CurrentUser,
    get_db,
    get_session_factory_from_request,
    require_roles,
)
from backend.models import (
    AcademicTerm,
    AuditLog,
    Batch,
    ConflictLog,
    ConstraintRule,
    Course,
    CourseOffering,
    ExamEntry,
    ExamRoomAllocation,
    ExamSlot,
    Instructor,
    Room,
    Schedule,
    SchedulingConfig,
    TimeSlot,
    TimetableEntry,
)
from backend.routers.master_data import (
    DEFAULT_EXAM_CATALOGUE,
    DEFAULT_TIMETABLE_CATALOGUE,
    _fmt_dt,
    _fmt_time,
)
from backend.schemas import (
    ConflictLogResponse,
    EnrichedExamEntryResponse,
    EnrichedExamRoomAllocationResponse,
    EnrichedTimetableEntryResponse,
    ScheduleEntriesResponse,
    ScheduleEntryUpdateRequest,
    ScheduleGenerateRequest,
    ScheduleGenerateResponse,
    ScheduleStatusResponse,
)
from engine.exam_scheduler import schedule_exams
from engine.models import (
    ExamRoomAllocation as EngineExamRoomAllocation,
)
from engine.timetable_solver import solve_timetable
from engine.validator import ExamValidator, TimetableValidator

router = APIRouter(tags=["Schedules & Generation"])


def _batch_label(batch: Batch) -> str:
    short_year = batch.batch_year % 100
    return f"{batch.program_code}-{short_year:02d} {batch.section}"


def _build_enriched_timetable_entry(
    db: Session,
    entry: TimetableEntry,
) -> EnrichedTimetableEntryResponse:
    offering = db.get(CourseOffering, entry.offering_id)
    course = db.get(Course, offering.course_id) if offering is not None else None
    instructor = db.get(Instructor, entry.instructor_id)
    batch = db.get(Batch, entry.batch_id)
    room = db.get(Room, entry.room_id)
    slot = db.get(TimeSlot, entry.slot_id)

    return EnrichedTimetableEntryResponse(
        entry_id=entry.entry_id,
        schedule_id=entry.schedule_id,
        offering_id=entry.offering_id,
        course_id=course.course_id if course else (offering.course_id if offering else 0),
        course_code=course.course_code if course else "",
        course_title=course.title if course else "",
        instructor_id=entry.instructor_id,
        instructor_name=instructor.full_name if instructor else "",
        batch_id=entry.batch_id,
        batch_label=_batch_label(batch) if batch else "",
        room_id=entry.room_id,
        room_code=room.room_code if room else "",
        slot_id=entry.slot_id,
        day_of_week=slot.day_of_week if slot else 1,
        slot_index=slot.slot_index if slot else 1,
        start_time=_fmt_time(slot.start_time) if slot else "08:00",
        end_time=_fmt_time(slot.end_time) if slot else "09:00",
        session_type=entry.session_type,
        is_locked=bool(entry.is_locked),
        is_manual_override=bool(entry.is_manual_override),
    )


def _build_enriched_exam_entry(
    db: Session,
    entry: ExamEntry,
) -> EnrichedExamEntryResponse:
    course = db.get(Course, entry.course_id)
    exam_slot = db.get(ExamSlot, entry.exam_slot_id)
    allocs = db.scalars(
        select(ExamRoomAllocation)
        .where(ExamRoomAllocation.exam_entry_id == entry.exam_entry_id)
        .order_by(ExamRoomAllocation.allocation_id)
    ).all()

    enriched_allocs: list[EnrichedExamRoomAllocationResponse] = []
    for a in allocs:
        room = db.get(Room, a.room_id)
        enriched_allocs.append(
            EnrichedExamRoomAllocationResponse(
                allocation_id=a.allocation_id,
                room_id=a.room_id,
                room_code=room.room_code if room else "",
                building=room.building if room else "",
                seats_allocated=a.seats_allocated,
            )
        )

    return EnrichedExamEntryResponse(
        exam_entry_id=entry.exam_entry_id,
        schedule_id=entry.schedule_id,
        course_id=entry.course_id,
        course_code=course.course_code if course else "",
        course_title=course.title if course else "",
        exam_slot_id=entry.exam_slot_id,
        exam_date=exam_slot.exam_date.isoformat() if exam_slot else "",
        start_time=_fmt_time(exam_slot.start_time) if exam_slot else "09:00",
        end_time=_fmt_time(exam_slot.end_time) if exam_slot else "12:00",
        label=exam_slot.label if exam_slot else None,
        student_count=entry.student_count,
        is_locked=bool(entry.is_locked),
        room_allocations=enriched_allocs,
    )


def _build_schedule_status_response(db: Session, sch: Schedule) -> ScheduleStatusResponse:
    if sch.schedule_type == "Timetable":
        entry_count = int(
            db.scalar(
                select(func.count(TimetableEntry.entry_id)).where(
                    TimetableEntry.schedule_id == sch.schedule_id
                )
            )
            or 0
        )
    else:
        entry_count = int(
            db.scalar(
                select(func.count(ExamEntry.exam_entry_id)).where(
                    ExamEntry.schedule_id == sch.schedule_id
                )
            )
            or 0
        )

    conflict_count = int(
        db.scalar(
            select(func.count(ConflictLog.conflict_id)).where(
                ConflictLog.schedule_id == sch.schedule_id
            )
        )
        or 0
    )
    hard_violation_count = int(
        db.scalar(
            select(func.count(ConflictLog.conflict_id)).where(
                ConflictLog.schedule_id == sch.schedule_id,
                ConflictLog.severity == "Hard",
            )
        )
        or 0
    )

    return ScheduleStatusResponse(
        schedule_id=sch.schedule_id,
        term_id=sch.term_id,
        config_id=sch.config_id,
        schedule_type=sch.schedule_type,
        version_no=sch.version_no,
        status=sch.status,
        solver_status=sch.solver_status,
        objective_score=(
            float(sch.objective_score) if sch.objective_score is not None else None
        ),
        run_seconds=(
            float(sch.run_seconds) if sch.run_seconds is not None else None
        ),
        entry_count=entry_count,
        conflict_count=conflict_count,
        hard_violation_count=hard_violation_count,
        generated_by=sch.generated_by,
        generated_at=_fmt_dt(sch.generated_at),
        approved_by=sch.approved_by,
        published_at=_fmt_dt(sch.published_at) if sch.published_at else None,
    )


def run_schedule_generation_worker(
    session_factory: sessionmaker[Session],
    schedule_id: int,
    *,
    time_limit_override: int | None = None,
    random_seed_override: int | None = None,
) -> None:
    """Background worker that solves a timetable or exam schedule and saves in one transaction (`DB-6`, `SAF-2`)."""
    try:
        with session_scope(session_factory) as session:
            sch = session.get(Schedule, schedule_id)
            if sch is None:
                return
            term_id = sch.term_id
            config_id = sch.config_id
            schedule_type = sch.schedule_type
            generated_by = sch.generated_by

            cfg = session.get(SchedulingConfig, config_id)
            time_limit_s = float(
                time_limit_override
                if time_limit_override is not None
                else (cfg.solver_time_limit_s if cfg is not None else 120)
            )
            random_seed = int(
                random_seed_override
                if random_seed_override is not None
                else (cfg.random_seed if cfg is not None else 1)
            )

            # Find latest previous Generated or Published schedule to preserve locked entries (FR-6.10)
            prev_schedule = session.scalar(
                select(Schedule)
                .where(
                    Schedule.term_id == term_id,
                    Schedule.schedule_type == schedule_type,
                    Schedule.schedule_id != schedule_id,
                    Schedule.status.in_(("Generated", "Published")),
                )
                .order_by(Schedule.version_no.desc())
            )
            prev_schedule_id = prev_schedule.schedule_id if prev_schedule is not None else None

            dataset = load_term_dataset(
                session,
                term_id=term_id,
                config_id=config_id,
                schedule_id=prev_schedule_id,
                include_existing_schedules=prev_schedule_id is not None,
            )
            if prev_schedule_id is not None:
                dataset.timetable_entries = [
                    e for e in dataset.timetable_entries if e.is_locked
                ]
                dataset.exam_entries = [
                    e for e in dataset.exam_entries if e.is_locked
                ]

        if schedule_type == "Timetable":
            tt_result = solve_timetable(
                dataset,
                term_id=term_id,
                config_id=config_id,
                time_limit_s=time_limit_s,
                random_seed=random_seed,
            )
            save_timetable_result(
                session_factory,
                tt_result,
                term_id=term_id,
                config_id=config_id,
                generated_by=generated_by,
                schedule_id=schedule_id,
            )
        else:
            exam_result = schedule_exams(
                dataset,
                term_id=term_id,
                config_id=config_id,
                time_limit_s=time_limit_s,
                random_seed=random_seed,
            )
            save_exam_result(
                session_factory,
                exam_result,
                term_id=term_id,
                config_id=config_id,
                generated_by=generated_by,
                schedule_id=schedule_id,
            )
    except Exception as exc:
        # Ensure a failed/interrupted run never leaves the schedule stuck in 'Generating' (SRS 4.3.2, SAF-2)
        with session_scope(session_factory) as session:
            sch = session.get(Schedule, schedule_id)
            if sch is not None and sch.status == "Generating":
                sch.status = "Infeasible"
                sch.solver_status = "interrupted"
                session.add(
                    ConflictLog(
                        schedule_id=schedule_id,
                        conflict_type="WorkerInterrupted",
                        severity="Hard",
                        description=f"Solver worker interrupted: {exc}",
                        entity_ref=f"schedule_id={schedule_id}",
                        is_resolved=False,
                    )
                )


# ============================================================================
# Schedule Listing & Generation (`GET /schedules`, `POST /schedules/generate`)
# ============================================================================
@router.get("/schedules", response_model=list[ScheduleStatusResponse])
def list_schedules(
    term_id: int | None = Query(default=None),
    schedule_type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator", "Faculty", "Student")
    ),
) -> list[ScheduleStatusResponse]:
    stmt = select(Schedule)
    if term_id is not None:
        stmt = stmt.where(Schedule.term_id == term_id)
    if schedule_type is not None:
        stmt = stmt.where(Schedule.schedule_type == schedule_type)
    if status_filter is not None:
        stmt = stmt.where(Schedule.status == status_filter)
    schedules = db.scalars(stmt.order_by(Schedule.schedule_id)).all()
    return [_build_schedule_status_response(db, s) for s in schedules]


@router.get("/schedules/{schedule_id}", response_model=ScheduleStatusResponse)
def get_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator", "Faculty", "Student")
    ),
) -> ScheduleStatusResponse:
    sch = db.get(Schedule, schedule_id)
    if sch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule {schedule_id} not found.",
        )
    return _build_schedule_status_response(db, sch)


@router.post(
    "/schedules/generate",
    response_model=ScheduleGenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_schedule(
    payload: ScheduleGenerateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles("Coordinator", "Administrator")),
) -> ScheduleGenerateResponse:
    """Create a new schedule with `status='Generating'` and run the solver in a background worker."""
    term = db.get(AcademicTerm, payload.term_id)
    if term is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AcademicTerm {payload.term_id} not found.",
        )

    if payload.config_id is not None:
        cfg = db.get(SchedulingConfig, payload.config_id)
        if cfg is None or cfg.term_id != payload.term_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"SchedulingConfig {payload.config_id} for term {payload.term_id} not found."
                ),
            )
        schedule_type = cfg.schedule_type
    else:
        schedule_type = payload.schedule_type
        cfg = db.scalar(
            select(SchedulingConfig)
            .where(
                SchedulingConfig.term_id == payload.term_id,
                SchedulingConfig.schedule_type == schedule_type,
            )
            .order_by(SchedulingConfig.config_id)
        )
        if cfg is None:
            cfg = SchedulingConfig(
                term_id=payload.term_id,
                schedule_type=schedule_type,
                name=f"Default {schedule_type.lower()}",
                solver_time_limit_s=payload.solver_time_limit_s or 120,
                random_seed=payload.random_seed or 1,
                created_by=payload.generated_by or user.user_id,
            )
            db.add(cfg)
            db.flush()
            catalogue = (
                DEFAULT_TIMETABLE_CATALOGUE
                if schedule_type == "Timetable"
                else DEFAULT_EXAM_CATALOGUE
            )
            for code, r_type, enabled, weight, param in catalogue:
                db.add(
                    ConstraintRule(
                        config_id=cfg.config_id,
                        rule_code=code,
                        rule_type=r_type,
                        is_enabled=enabled,
                        weight=weight,
                        param_value=param,
                    )
                )
            db.flush()

    next_version = _next_schedule_version(db, payload.term_id, schedule_type)
    new_schedule = Schedule(
        term_id=payload.term_id,
        config_id=cfg.config_id,
        schedule_type=schedule_type,
        version_no=next_version,
        status="Generating",
        solver_status=None,
        generated_by=payload.generated_by or user.user_id,
    )
    db.add(new_schedule)
    db.commit()
    db.refresh(new_schedule)

    response_payload = ScheduleGenerateResponse(
        schedule_id=new_schedule.schedule_id,
        term_id=new_schedule.term_id,
        config_id=new_schedule.config_id,
        schedule_type=new_schedule.schedule_type,
        version_no=new_schedule.version_no,
        status=new_schedule.status,  # 'Generating'
    )

    session_factory = get_session_factory_from_request(request)
    background_tasks.add_task(
        run_schedule_generation_worker,
        session_factory=session_factory,
        schedule_id=new_schedule.schedule_id,
        time_limit_override=payload.solver_time_limit_s,
        random_seed_override=payload.random_seed,
    )

    return response_payload


# ============================================================================
# Status, Entries & Conflicts (`GET /schedules/{id}/status`, `/entries`, `/conflicts`)
# ============================================================================
@router.get("/schedules/{schedule_id}/status", response_model=ScheduleStatusResponse)
def get_schedule_status(
    schedule_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator", "Faculty", "Student")
    ),
) -> ScheduleStatusResponse:
    sch = db.get(Schedule, schedule_id)
    if sch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule {schedule_id} not found.",
        )
    return _build_schedule_status_response(db, sch)


@router.get("/schedules/{schedule_id}/entries", response_model=ScheduleEntriesResponse)
def get_schedule_entries(
    schedule_id: int,
    batch_id: int | None = Query(default=None),
    instructor_id: int | None = Query(default=None),
    room_id: int | None = Query(default=None),
    course_id: int | None = Query(default=None),
    day_of_week: int | None = Query(default=None),
    exam_date: str | None = Query(default=None),
    session_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator", "Faculty", "Student")
    ),
) -> ScheduleEntriesResponse:
    sch = db.get(Schedule, schedule_id)
    if sch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule {schedule_id} not found.",
        )
    term = db.get(AcademicTerm, sch.term_id)
    hard_violation_count = int(
        db.scalar(
            select(func.count(ConflictLog.conflict_id)).where(
                ConflictLog.schedule_id == schedule_id,
                ConflictLog.severity == "Hard",
            )
        )
        or 0
    )

    tt_entries_orm = db.scalars(
        select(TimetableEntry)
        .where(TimetableEntry.schedule_id == schedule_id)
        .order_by(TimetableEntry.entry_id)
    ).all()
    enriched_tt: list[EnrichedTimetableEntryResponse] = []
    for te in tt_entries_orm:
        item = _build_enriched_timetable_entry(db, te)
        if batch_id is not None and item.batch_id != batch_id:
            continue
        if instructor_id is not None and item.instructor_id != instructor_id:
            continue
        if room_id is not None and item.room_id != room_id:
            continue
        if course_id is not None and item.course_id != course_id:
            continue
        if day_of_week is not None and item.day_of_week != day_of_week:
            continue
        if session_type is not None and item.session_type != session_type:
            continue
        enriched_tt.append(item)

    exam_entries_orm = db.scalars(
        select(ExamEntry)
        .where(ExamEntry.schedule_id == schedule_id)
        .order_by(ExamEntry.exam_entry_id)
    ).all()
    enriched_exam: list[EnrichedExamEntryResponse] = []
    for ee in exam_entries_orm:
        item_ex = _build_enriched_exam_entry(db, ee)
        if course_id is not None and item_ex.course_id != course_id:
            continue
        if exam_date is not None and item_ex.exam_date != exam_date:
            continue
        if room_id is not None and all(
            a.room_id != room_id for a in item_ex.room_allocations
        ):
            continue
        if batch_id is not None:
            batch_offerings = db.scalars(
                select(CourseOffering).where(
                    CourseOffering.term_id == sch.term_id,
                    CourseOffering.course_id == item_ex.course_id,
                    CourseOffering.batch_id == batch_id,
                )
            ).all()
            if not batch_offerings:
                continue
        enriched_exam.append(item_ex)

    active_entries_dicts: list[dict[str, Any]] = (
        [e.model_dump() for e in enriched_tt]
        if sch.schedule_type == "Timetable"
        else [e.model_dump() for e in enriched_exam]
    )

    return ScheduleEntriesResponse(
        schedule_id=sch.schedule_id,
        term_id=sch.term_id,
        term_name=term.name if term else "",
        config_id=sch.config_id,
        schedule_type=sch.schedule_type,
        version_no=sch.version_no,
        status=sch.status,
        solver_status=sch.solver_status,
        objective_score=(
            float(sch.objective_score) if sch.objective_score is not None else None
        ),
        run_seconds=(
            float(sch.run_seconds) if sch.run_seconds is not None else None
        ),
        hard_violation_count=hard_violation_count,
        generated_by=sch.generated_by,
        generated_at=_fmt_dt(sch.generated_at),
        approved_by=sch.approved_by,
        published_at=_fmt_dt(sch.published_at) if sch.published_at else None,
        timetable_entries=enriched_tt,
        exam_entries=enriched_exam,
        entries=active_entries_dicts,
    )


@router.get("/schedules/{schedule_id}/conflicts", response_model=list[ConflictLogResponse])
def get_schedule_conflicts(
    schedule_id: int,
    conflict_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(
        require_roles("Coordinator", "Approver", "Administrator")
    ),
) -> list[ConflictLogResponse]:
    sch = db.get(Schedule, schedule_id)
    if sch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule {schedule_id} not found.",
        )
    stmt = select(ConflictLog).where(ConflictLog.schedule_id == schedule_id)
    if conflict_type:
        stmt = stmt.where(ConflictLog.conflict_type == conflict_type)
    if severity:
        stmt = stmt.where(ConflictLog.severity == severity)
    rows = db.scalars(stmt.order_by(ConflictLog.conflict_id)).all()
    return [
        ConflictLogResponse(
            conflict_id=r.conflict_id,
            schedule_id=r.schedule_id,
            conflict_type=r.conflict_type,
            severity=r.severity,
            description=r.description,
            entity_ref=r.entity_ref,
            detected_at=_fmt_dt(r.detected_at),
            is_resolved=bool(r.is_resolved),
        )
        for r in rows
    ]


# ============================================================================
# Manual Move & Re-Validation (`PUT /schedules/{id}/entries/{entry_id}` — FR-8.3..FR-8.6)
# ============================================================================
def _handle_schedule_entry_update(
    db: Session,
    schedule_id: int,
    entry_id: int,
    payload: ScheduleEntryUpdateRequest,
    user: CurrentUser,
) -> Any:
    sch = db.get(Schedule, schedule_id)
    if sch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule {schedule_id} not found.",
        )

    # SAF-4 & FR-8.3: Published and Archived schedules are read-only
    if sch.status in ("Published", "Archived"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Schedule {schedule_id} has status '{sch.status}' and cannot be edited in place "
                "(SAF-4, FR-8.3). Only 'Generated' or 'Draft' schedules allow manual moves."
            ),
        )

    dataset = load_term_dataset(
        db,
        term_id=sch.term_id,
        config_id=sch.config_id,
        schedule_id=schedule_id,
    )

    if sch.schedule_type == "Timetable":
        entry_orm = db.get(TimetableEntry, entry_id)
        if entry_orm is None or entry_orm.schedule_id != schedule_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"TimetableEntry {entry_id} in schedule {schedule_id} not found.",
            )

        new_slot_id = payload.slot_id if payload.slot_id is not None else entry_orm.slot_id
        new_room_id = payload.room_id if payload.room_id is not None else entry_orm.room_id
        new_locked = (
            payload.is_locked if payload.is_locked is not None else bool(entry_orm.is_locked)
        )

        slot_orm = db.get(TimeSlot, new_slot_id)
        if slot_orm is None or slot_orm.term_id != sch.term_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"TimeSlot {new_slot_id} in term {sch.term_id} not found.",
            )
        room_orm = db.get(Room, new_room_id)
        if room_orm is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Room {new_room_id} not found.",
            )

        moved = (new_slot_id != entry_orm.slot_id) or (new_room_id != entry_orm.room_id)
        new_override = True if moved else bool(entry_orm.is_manual_override)

        # Apply candidate change in memory and run the independent validator (FR-8.4)
        candidate_entries = [
            replace(
                e,
                slot_id=new_slot_id,
                room_id=new_room_id,
                is_locked=new_locked,
                is_manual_override=new_override,
            )
            if e.entry_id == entry_id
            else e
            for e in dataset.timetable_entries
        ]
        dataset.timetable_entries = candidate_entries

        violations = TimetableValidator().validate(
            dataset,
            entries=candidate_entries,
            config_id=sch.config_id,
        )
        hard_violations = [v for v in violations if v.severity == "Hard"]

        if hard_violations:
            # Order violations directly involving the moved entry/slot/room first
            def _relevance(v: Any) -> int:
                aff = v.affected_entities or {}
                if entry_id in aff.get("entry_ids", []):
                    return 0
                if aff.get("offering_id") == entry_orm.offering_id:
                    return 1
                if aff.get("slot_id") == new_slot_id or aff.get("room_id") == new_room_id:
                    return 2
                return 3

            hard_violations.sort(key=_relevance)
            violated_codes = list(dict.fromkeys(v.rule_code for v in hard_violations))
            primary_v = hard_violations[0]
            detail_msg = (
                f"Manual move violates hard constraint {', '.join(violated_codes)}: "
                f"{primary_v.description}"
            )
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "detail": detail_msg,
                    "rule_code": primary_v.rule_code,
                    "violated_constraints": violated_codes,
                    "violations": [v.to_conflict_log_dict() for v in hard_violations],
                },
            )

        entry_orm.slot_id = new_slot_id
        entry_orm.room_id = new_room_id
        entry_orm.is_locked = new_locked
        entry_orm.is_manual_override = new_override

        db.add(
            AuditLog(
                user_id=user.user_id,
                action="MANUAL_ADJUST",
                entity_type="timetable_entries",
                entity_id=entry_id,
                details=(
                    f"schedule_id={schedule_id}, entry_id={entry_id}, "
                    f"slot_id={new_slot_id}, room_id={new_room_id}, "
                    f"is_locked={new_locked}, is_manual_override={new_override}"
                ),
            )
        )
        db.commit()
        db.refresh(entry_orm)
        return _build_enriched_timetable_entry(db, entry_orm)

    # Exam schedule entry adjustment (`schedule_type == "Exam"`)
    exam_entry_orm = db.get(ExamEntry, entry_id)
    if exam_entry_orm is None or exam_entry_orm.schedule_id != schedule_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ExamEntry {entry_id} in schedule {schedule_id} not found.",
        )

    target_exam_slot_id = (
        payload.exam_slot_id
        if payload.exam_slot_id is not None
        else (payload.slot_id if payload.slot_id is not None else exam_entry_orm.exam_slot_id)
    )
    new_locked = (
        payload.is_locked
        if payload.is_locked is not None
        else bool(exam_entry_orm.is_locked)
    )

    exam_slot_orm = db.get(ExamSlot, target_exam_slot_id)
    if exam_slot_orm is None or exam_slot_orm.term_id != sch.term_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ExamSlot {target_exam_slot_id} in term {sch.term_id} not found.",
        )

    # Build candidate room allocations if room_allocations or room_id was supplied
    candidate_allocs = list(dataset.exam_room_allocations)
    new_entry_allocs: list[EngineExamRoomAllocation] | None = None

    if payload.room_allocations is not None:
        for ra in payload.room_allocations:
            if db.get(Room, ra.room_id) is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Room {ra.room_id} not found.",
                )
        new_entry_allocs = [
            EngineExamRoomAllocation(
                allocation_id=-(idx + 1),
                exam_entry_id=entry_id,
                room_id=ra.room_id,
                seats_allocated=ra.seats_allocated,
            )
            for idx, ra in enumerate(payload.room_allocations)
        ]
    elif payload.room_id is not None:
        if db.get(Room, payload.room_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Room {payload.room_id} not found.",
            )
        new_entry_allocs = [
            EngineExamRoomAllocation(
                allocation_id=-1,
                exam_entry_id=entry_id,
                room_id=payload.room_id,
                seats_allocated=exam_entry_orm.student_count,
            )
        ]

    if new_entry_allocs is not None:
        candidate_allocs = [
            a for a in candidate_allocs if a.exam_entry_id != entry_id
        ] + new_entry_allocs

    candidate_exam_entries = [
        replace(
            e,
            exam_slot_id=target_exam_slot_id,
            is_locked=new_locked,
            is_manual_override=True,
            room_allocations=(
                new_entry_allocs if new_entry_allocs is not None else e.room_allocations
            ),
        )
        if e.exam_entry_id == entry_id
        else e
        for e in dataset.exam_entries
    ]
    dataset.exam_entries = candidate_exam_entries
    dataset.exam_room_allocations = candidate_allocs

    exam_violations = ExamValidator().validate(
        dataset,
        entries=candidate_exam_entries,
        allocations=candidate_allocs,
        config_id=sch.config_id,
    )
    hard_exam_violations = [v for v in exam_violations if v.severity == "Hard"]

    if hard_exam_violations:
        violated_codes = list(dict.fromkeys(v.rule_code for v in hard_exam_violations))
        primary_v = hard_exam_violations[0]
        detail_msg = (
            f"Manual exam move violates hard constraint {', '.join(violated_codes)}: "
            f"{primary_v.description}"
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": detail_msg,
                "rule_code": primary_v.rule_code,
                "violated_constraints": violated_codes,
                "violations": [v.to_conflict_log_dict() for v in hard_exam_violations],
            },
        )

    exam_entry_orm.exam_slot_id = target_exam_slot_id
    exam_entry_orm.is_locked = new_locked

    if new_entry_allocs is not None:
        existing_allocs = db.scalars(
            select(ExamRoomAllocation).where(
                ExamRoomAllocation.exam_entry_id == entry_id
            )
        ).all()
        for old_a in existing_allocs:
            db.delete(old_a)
        db.flush()
        for na in new_entry_allocs:
            db.add(
                ExamRoomAllocation(
                    exam_entry_id=entry_id,
                    room_id=na.room_id,
                    seats_allocated=na.seats_allocated,
                )
            )

    db.add(
        AuditLog(
            user_id=user.user_id,
            action="MANUAL_ADJUST",
            entity_type="exam_entries",
            entity_id=entry_id,
            details=(
                f"schedule_id={schedule_id}, exam_entry_id={entry_id}, "
                f"exam_slot_id={target_exam_slot_id}, is_locked={new_locked}"
            ),
        )
    )
    db.commit()
    db.refresh(exam_entry_orm)
    return _build_enriched_exam_entry(db, exam_entry_orm)


@router.put("/schedules/{schedule_id}/entries/{entry_id}")
def update_schedule_entry(
    schedule_id: int,
    entry_id: int,
    payload: ScheduleEntryUpdateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles("Coordinator", "Administrator")),
) -> Any:
    """Move or lock a timetable session or exam entry with immediate hard-constraint re-validation."""
    return _handle_schedule_entry_update(db, schedule_id, entry_id, payload, user)


@router.put("/schedules/{schedule_id}/entries")
def update_schedule_entry_from_body(
    schedule_id: int,
    payload: ScheduleEntryUpdateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles("Coordinator", "Administrator")),
) -> Any:
    """Table 9 alias (`PUT /schedules/{id}/entries`) reading `entry_id` from the request body."""
    if payload.entry_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="entry_id is required when calling PUT /schedules/{id}/entries.",
        )
    return _handle_schedule_entry_update(
        db, schedule_id, payload.entry_id, payload, user
    )
