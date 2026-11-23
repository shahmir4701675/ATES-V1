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
from backend.manual_edits import revision_no
from backend.schedule_access import check_schedule_access, check_scope_filters, scoped_entries, scoped_offerings, view_context
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
    GenerationRun,
    ScheduleSnapshot,
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
    UndoScheduleRequest,
    ScheduleEntryUpdateRequest,
    ScheduleGenerateRequest,
    ScheduleGenerateResponse,
    ScheduleStatusResponse,
)
from engine.exam_scheduler import schedule_exams
from engine.models import (
    ExamRoomAllocation as EngineExamRoomAllocation,
    TimetableEntry as EngineTimetableEntry,
)
from engine.timetable_solver import solve_timetable
from engine.validator import ExamValidator, TimetableValidator
from backend.schedule_integrity import capture_inputs, validate_version, lock_inputs

router = APIRouter(tags=["Schedules & Generation"])


def _batch_label(batch: Batch) -> str:
    short_year = batch.batch_year % 100
    return f"{batch.program_code}-{short_year:02d} {batch.section}"


def _build_enriched_timetable_entry(
    db: Session,
    entry: TimetableEntry,
    context=None,
) -> EnrichedTimetableEntryResponse:
    offering = context.offerings_by_id.get(entry.offering_id) if context else db.get(CourseOffering, entry.offering_id)
    course = (context.courses_by_id.get(offering.course_id) if context else db.get(Course, offering.course_id)) if offering else None
    instructor = context.instructors_by_id.get(entry.instructor_id) if context else db.get(Instructor, entry.instructor_id)
    batch = context.batches_by_id.get(entry.batch_id) if context else db.get(Batch, entry.batch_id)
    room = context.rooms_by_id.get(entry.room_id) if context else db.get(Room, entry.room_id)
    slot = context.slots_by_id.get(entry.slot_id) if context else db.get(TimeSlot, entry.slot_id)

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
        start_time=str(slot.start_time)[:5] if slot else "08:00",
        end_time=str(slot.end_time)[:5] if slot else "09:00",
        session_type=entry.session_type,
        is_locked=bool(entry.is_locked),
        is_manual_override=bool(entry.is_manual_override),
    )


def _build_enriched_exam_entry(
    db: Session,
    entry: ExamEntry,
    context=None,
) -> EnrichedExamEntryResponse:
    course = context.courses_by_id.get(entry.course_id) if context else db.get(Course, entry.course_id)
    exam_slot = context.exam_slots_by_id.get(entry.exam_slot_id) if context else db.get(ExamSlot, entry.exam_slot_id)
    allocs = db.scalars(
        select(ExamRoomAllocation)
        .where(ExamRoomAllocation.exam_entry_id == entry.exam_entry_id)
        .order_by(ExamRoomAllocation.allocation_id)
    ).all()

    enriched_allocs: list[EnrichedExamRoomAllocationResponse] = []
    for a in allocs:
        room = context.rooms_by_id.get(a.room_id) if context else db.get(Room, a.room_id)
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
        exam_date=str(exam_slot.exam_date) if exam_slot else "",
        start_time=str(exam_slot.start_time)[:5] if exam_slot else "09:00",
        end_time=str(exam_slot.end_time)[:5] if exam_slot else "12:00",
        label=exam_slot.label if exam_slot else None,
        student_count=entry.student_count,
        is_locked=bool(entry.is_locked),
        is_manual_override=bool(entry.is_manual_override),
        room_allocations=enriched_allocs,
    )


def _build_schedule_status_response(db: Session, sch: Schedule, user=None) -> ScheduleStatusResponse:
    if sch.status in {"Published", "Archived"}:
        load_term_dataset(db, sch.term_id, config_id=sch.config_id, schedule_id=sch.schedule_id)
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

    if user is not None and user.role in {'Faculty','Student'}:
        context=load_term_dataset(db,sch.term_id,config_id=sch.config_id,schedule_id=sch.schedule_id)
        entry_count=len(scoped_entries(context,sch.schedule_type,user))
        conflict_count=hard_violation_count=0
    run = db.get(GenerationRun, sch.schedule_id)
    return ScheduleStatusResponse(
        generation_state=run.state if run else None,
        generation_phase=run.phase if run else None,
        worker_stopped=bool(run and run.worker_stopped_at),
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
    deadline: float | None = None,
) -> None:
    from backend.generation import supervise
    supervise(session_factory,schedule_id,deadline)


from backend.generation_execution import execute_generation


@router.post("/schedules/{schedule_id}/cancel", response_model=ScheduleStatusResponse)
def cancel_schedule(schedule_id: int, request: Request, db: Session = Depends(get_db), user: CurrentUser = Depends(require_roles("Coordinator"))):
    from backend.generation import terminal,stop_local,acknowledge_stop
    import time
    lock_inputs(db)
    sch=db.get(Schedule,schedule_id)
    if sch is None: raise HTTPException(404,"Schedule not found.")
    if sch.generated_by != user.user_id: raise HTTPException(403,"Only the Coordinator who started this run may cancel it.")
    run=db.get(GenerationRun,schedule_id)
    if run is None: raise HTTPException(409,"This version has no active generation run.")
    if run.state not in {"Queued","Running","Cancelled"}: raise HTTPException(409,"The generation run has already finished.")
    token=run.owner_token
    no_process=run.process_id is None
    terminal(db,sch,"Cancelled","Generation cancelled by its authenticated Coordinator.")
    db.add(AuditLog(user_id=user.user_id,action="CANCEL_GENERATION",entity_type="schedules",entity_id=schedule_id,details="Cancellation requested; result persistence is fenced."))
    db.commit()
    factory=get_session_factory_from_request(request)
    if no_process or stop_local(token): acknowledge_stop(factory,schedule_id,token)
    # A different API process may own the worker; durable state is its stop signal.
    for _ in range(20):
        db.expire_all(); run=db.get(GenerationRun,schedule_id)
        if run.worker_stopped_at: break
        time.sleep(.05)
    result=_build_schedule_status_response(db,db.get(Schedule,schedule_id))
    if not result.worker_stopped:
        return JSONResponse(status_code=202,content=result.model_dump(mode="json"))
    return result


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
    visible=[]
    for schedule in schedules:
        try:check_schedule_access(db,schedule,_user)
        except HTTPException as exc:
            if exc.status_code==403:continue
            raise
        visible.append(_build_schedule_status_response(db,schedule,_user))
    return visible


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
    check_schedule_access(db,sch,_user)
    return _build_schedule_status_response(db, sch, _user)


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
    user: CurrentUser = Depends(require_roles("Coordinator")),
) -> ScheduleGenerateResponse:
    """Create a new schedule with `status='Generating'` and run the solver in a background worker."""
    from backend.auth import utc_now
    from backend.generation import new_run
    submitted_at=utc_now()
    import time
    submitted_monotonic=time.monotonic()
    lock_inputs(db)  # Serialize config selection/creation and version allocation together.
    term = db.get(AcademicTerm, payload.term_id)
    if term is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AcademicTerm {payload.term_id} not found.",
        )

    if term.status=='Closed':raise HTTPException(422,'Cannot generate schedules for a Closed term.')

    if payload.config_id is not None:
        cfg = db.get(SchedulingConfig, payload.config_id)
        if cfg is None or cfg.term_id != payload.term_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"SchedulingConfig {payload.config_id} for term {payload.term_id} not found."
                ),
            )
        if 'schedule_type' in payload.model_fields_set and payload.schedule_type!=cfg.schedule_type:raise HTTPException(422,'Configuration schedule type does not match the request.')
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
                created_by=user.user_id,
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

    # Fail before queuing a worker when persisted configuration was written by
    # an older client or an external database writer.
    from backend.input_validation import validate_rules
    validate_rules(list(db.scalars(select(ConstraintRule).where(ConstraintRule.config_id==cfg.config_id))),schedule_type)
    if not 10<=cfg.solver_time_limit_s<=600 or not 0<=cfg.random_seed<=2147483647:
        raise HTTPException(422,'Stored solver settings are outside their supported domain.')
    if schedule_type=='Exam' and db.scalar(select(ExamSlot.exam_slot_id).where(ExamSlot.term_id==payload.term_id).limit(1)) is None:
        raise HTTPException(422,'An exam configuration requires at least one exam session before generation.')

    next_version = _next_schedule_version(db, payload.term_id, schedule_type)
    new_schedule = Schedule(
        term_id=payload.term_id,
        config_id=cfg.config_id,
        schedule_type=schedule_type,
        version_no=next_version,
        status="Generating",
        solver_status=None,
        generated_by=user.user_id,
    )
    db.add(new_schedule)
    db.flush()
    db.add(AuditLog(user_id=user.user_id,action="GENERATION_QUEUED",entity_type="schedules",entity_id=new_schedule.schedule_id))
    db.add(new_run(new_schedule.schedule_id,
        payload.solver_time_limit_s if payload.solver_time_limit_s is not None else cfg.solver_time_limit_s,
        payload.random_seed if payload.random_seed is not None else cfg.random_seed, submitted_at))
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
        deadline=submitted_monotonic+(payload.solver_time_limit_s if payload.solver_time_limit_s is not None else cfg.solver_time_limit_s),
    )

    return response_payload


# ============================================================================
# Status, Entries & Conflicts (`GET /schedules/{id}/status`, `/entries`, `/conflicts`)
# ============================================================================
@router.post('/schedules/{schedule_id}/publish',response_model=ScheduleStatusResponse)
def publish_schedule(schedule_id:int,db:Session=Depends(get_db),user:CurrentUser=Depends(require_roles('Approver'))):
    import json
    from backend.auth import utc_now
    from backend.schedule_integrity import publication_eligibility,check_fresh
    lock_inputs(db)
    sch=db.get(Schedule,schedule_id,populate_existing=True)
    if sch is None:raise HTTPException(404,'Schedule not found.')
    if db.get(ScheduleSnapshot,schedule_id) is None:
        raise HTTPException(409,'This legacy version has no trusted original snapshot; reviewed recovery is required.')
    publication_eligibility(db,schedule_id)
    # Reading official history remains snapshot-only. A *new* publication must
    # additionally prove that this candidate's original inputs are still current.
    original=json.loads(db.get(ScheduleSnapshot,schedule_id).inputs_json)
    source_id=original.get('source_schedule_id')
    if source_id is not None:
        source=db.get(Schedule,source_id)
        if source is None or (source.term_id,source.schedule_type)!=(sch.term_id,sch.schedule_type):
            raise HTTPException(409,'The candidate source version is missing or inconsistent; regenerate.')
    check_fresh(db,original)
    previous=db.scalars(select(Schedule).where(Schedule.term_id==sch.term_id,Schedule.schedule_type==sch.schedule_type,Schedule.status=='Published')).all()
    for old in previous:
        # Refuse to silently archive an unreadable legacy official version.
        load_term_dataset(db,old.term_id,config_id=old.config_id,schedule_id=old.schedule_id)
        old.status='Archived'
        db.add(AuditLog(user_id=user.user_id,action='ARCHIVE_SCHEDULE',entity_type='schedules',entity_id=old.schedule_id,details=f'Replaced by version {sch.version_no}.'))
    db.flush()  # Release the unique Published slot before publishing the replacement.
    sch.status,sch.approved_by,sch.published_at='Published',user.user_id,utc_now()
    db.add(AuditLog(user_id=user.user_id,action='PUBLISH_SCHEDULE',entity_type='schedules',entity_id=schedule_id))
    db.commit()
    return _build_schedule_status_response(db,sch,user)


@router.post('/schedules/{schedule_id}/archive',response_model=ScheduleStatusResponse)
def archive_schedule(schedule_id:int,db:Session=Depends(get_db),user:CurrentUser=Depends(require_roles('Approver'))):
    lock_inputs(db)
    sch=db.get(Schedule,schedule_id,populate_existing=True)
    if sch is None:raise HTTPException(404,'Schedule not found.')
    if sch.status!='Published':raise HTTPException(409,'Only a Published version can be archived.')
    load_term_dataset(db,sch.term_id,config_id=sch.config_id,schedule_id=schedule_id)
    sch.status='Archived'
    db.add(AuditLog(user_id=user.user_id,action='ARCHIVE_SCHEDULE',entity_type='schedules',entity_id=schedule_id))
    db.commit()
    return _build_schedule_status_response(db,sch,user)


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
    check_schedule_access(db,sch,_user)
    return _build_schedule_status_response(db, sch, _user)


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
    check_schedule_access(db,sch,_user)
    check_scope_filters(_user,batch_id,instructor_id)
    if _user.role=="Student":batch_id=_user.batch_id
    if _user.role=="Faculty":instructor_id=_user.instructor_id
    context = load_term_dataset(db, sch.term_id, config_id=sch.config_id, schedule_id=schedule_id)
    term = context.academic_terms[0] if context.academic_terms else None
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
        item = _build_enriched_timetable_entry(db, te, context)
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
        item_ex = _build_enriched_exam_entry(db, ee, context)
        if course_id is not None and item_ex.course_id != course_id:
            continue
        if exam_date is not None and item_ex.exam_date != exam_date:
            continue
        if room_id is not None and all(
            a.room_id != room_id for a in item_ex.room_allocations
        ):
            continue
        if instructor_id is not None and not any(off.course_id==item_ex.course_id and off.instructor_id==instructor_id for off in context.course_offerings):
            continue
        if batch_id is not None:
            batch_offerings = [off for off in context.course_offerings if off.course_id == item_ex.course_id and off.batch_id == batch_id]
            if not batch_offerings:
                continue
        enriched_exam.append(item_ex)

    active_entries_dicts: list[dict[str, Any]] = (
        [e.model_dump() for e in enriched_tt]
        if sch.schedule_type == "Timetable"
        else [e.model_dump() for e in enriched_exam]
    )

    return ScheduleEntriesResponse(
        context=view_context(context,_user,enriched_tt,enriched_exam),
        edit_revision=revision_no(db,schedule_id),
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
    check_schedule_access(db,sch,_user)
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
    from backend.manual_edits import apply,ManualEditError
    try:
        sch,dataset,number=apply(db,schedule_id,entry_id,payload,user)
        row=db.get(TimetableEntry if sch.schedule_type=='Timetable' else ExamEntry,entry_id)
        result=_build_enriched_timetable_entry(db,row,dataset) if sch.schedule_type=='Timetable' else _build_enriched_exam_entry(db,row,dataset)
        return {**result.model_dump(),'edit_revision':number}
    except ManualEditError as exc:return JSONResponse(status_code=409,content=exc.payload)


@router.put("/schedules/{schedule_id}/entries/{entry_id}")
def update_schedule_entry(
    schedule_id: int,
    entry_id: int,
    payload: ScheduleEntryUpdateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles("Coordinator")),
) -> Any:
    """Move or lock a timetable session or exam entry with immediate hard-constraint re-validation."""
    return _handle_schedule_entry_update(db, schedule_id, entry_id, payload, user)


@router.put("/schedules/{schedule_id}/entries")
def update_schedule_entry_from_body(
    schedule_id: int,
    payload: ScheduleEntryUpdateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles("Coordinator")),
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


@router.post('/schedules/{schedule_id}/undo')
def undo_schedule(schedule_id:int,payload:UndoScheduleRequest,db:Session=Depends(get_db),user:CurrentUser=Depends(require_roles('Coordinator'))):
    from backend.manual_edits import undo,ManualEditError
    try:return undo(db,schedule_id,user,payload.expected_revision)
    except ManualEditError as exc:return JSONResponse(status_code=409,content=exc.payload)
