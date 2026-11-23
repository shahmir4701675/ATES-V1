"""Database-to-Engine adapter for loading academic terms and persisting solver results.

Conforms to:
- `docs/SRS.pdf` Section 3.1.4 (Database Interface)
- `docs/SRS.pdf` Section 4.2 `SAF-2` (Failed or aborted solver runs never overwrite or delete
  an existing schedule; every generation run writes to a new version inside a single
  database transaction that rolls back on error)
- `docs/SRS.pdf` Section 5.1 `DB-6` (Writing a new `schedules` row and its `timetable_entries`
  or `exam_entries` + `exam_room_allocations` and `conflict_log` rows executes inside a
  single database transaction; any failure rolls back the entire run)
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Sequence
from copy import deepcopy

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.database import session_scope
from backend.models import (
    AcademicTerm as AcademicTermORM,
    AuditLog as AuditLogORM,
    Batch as BatchORM,
    ConflictLog as ConflictLogORM,
    ConstraintRule as ConstraintRuleORM,
    Course as CourseORM,
    CourseOffering as CourseOfferingORM,
    Department as DepartmentORM,
    Enrollment as EnrollmentORM,
    ExamEntry as ExamEntryORM,
    ExamRoomAllocation as ExamRoomAllocationORM,
    ExamSlot as ExamSlotORM,
    Instructor as InstructorORM,
    InstructorAvailability as InstructorAvailabilityORM,
    Room as RoomORM,
    Schedule as ScheduleORM,
    SchedulingConfig as SchedulingConfigORM,
    TimeSlot as TimeSlotORM,
    TimetableEntry as TimetableEntryORM,
    ScheduleSnapshot,
)
from engine.exam_scheduler import ExamScheduleResult
from engine.models import (
    AcademicTerm,
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
    TimetableDataset,
    TimetableEntry,
    Violation,
)
from engine.timetable_solver import TimetableSolveResult


def _format_date(value: date | str) -> str:
    """Format a `datetime.date` or ISO date string as `'YYYY-MM-DD'`."""
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _format_time(value: time | str) -> str:
    """Format a `datetime.time` or time string as `'HH:MM'`."""
    if isinstance(value, time):
        if value.microsecond:
            return value.isoformat(timespec="microseconds")
        if value.second or value.tzinfo is not None:
            return value.isoformat(timespec="seconds")
        return value.strftime("%H:%M")
    return str(value).strip()


def _format_datetime(value: datetime | str | None) -> str | None:
    """Format a `datetime` as an ISO-8601 UTC string (`'YYYY-MM-DDTHH:MM:SSZ'`)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            utc_val = value.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            utc_val = value
        return utc_val.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _to_decimal(value: float | Decimal | None, places: str = "0.01") -> Decimal | None:
    """Convert a float or Decimal to a fixed-precision `Decimal` for `NUMERIC` columns."""
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal(places))


def load_term_dataset(
    session: Session,
    term_id: int,
    *,
    config_id: int | None = None,
    schedule_id: int | None = None,
    include_existing_schedules: bool = True,
    use_snapshot: bool = True,
) -> TimetableDataset:
    """Load all master, offering, enrollment, slot, and config records for `term_id` into `TimetableDataset`.

    Args:
        session: Active SQLAlchemy `Session`.
        term_id: Target `academic_terms.term_id` to load.
        config_id: Optional `scheduling_configs.config_id` to prioritize/filter.
        schedule_id: Optional `schedules.schedule_id` whose entries (e.g. locked slots) should be loaded.
        include_existing_schedules: Whether to load existing `schedules` and their entries for the term.

    Returns:
        A populated `engine.models.TimetableDataset` ready for `solve_timetable`,
        `schedule_exams`, `TimetableValidator`, or `ExamValidator`.

    Raises:
        ValueError: If `term_id` (or specified `config_id` / `schedule_id`) does not exist.
    """
    if schedule_id is not None and use_snapshot:
        from backend.schedule_integrity import hydrate_snapshot, SnapshotIntegrityError
        sch = session.get(ScheduleORM, schedule_id)
        if sch is None or sch.term_id != term_id or (config_id is not None and sch.config_id != config_id):
            raise SnapshotIntegrityError("Requested version context does not match term/configuration.")
        snapshot = session.get(ScheduleSnapshot, schedule_id)
        if snapshot is not None:
            return hydrate_snapshot(session, snapshot, sch)
        if sch.status in {"Published", "Archived"}:
            raise SnapshotIntegrityError("Legacy official version has no authoritative snapshot; reviewed recovery required.")
    elif use_snapshot and include_existing_schedules:
        official = session.scalar(select(ScheduleORM.schedule_id).where(ScheduleORM.term_id == term_id, ScheduleORM.status.in_(("Published", "Archived"))).limit(1))
        if official is not None:
            from backend.schedule_integrity import SnapshotIntegrityError
            raise SnapshotIntegrityError("Select an explicit version for historical inputs, or explicitly load current inputs for generation.")
    term_orm = session.get(AcademicTermORM, term_id)
    if term_orm is None:
        raise ValueError(f"AcademicTerm with term_id={term_id} does not exist.")

    departments_orm = session.scalars(
        select(DepartmentORM).order_by(DepartmentORM.department_id)
    ).all()
    batches_orm = session.scalars(
        select(BatchORM).order_by(BatchORM.batch_id)
    ).all()
    courses_orm = session.scalars(
        select(CourseORM).order_by(CourseORM.course_id)
    ).all()
    instructors_orm = session.scalars(
        select(InstructorORM).order_by(InstructorORM.instructor_id)
    ).all()
    rooms_orm = session.scalars(
        select(RoomORM).order_by(RoomORM.room_id)
    ).all()

    time_slots_orm = session.scalars(
        select(TimeSlotORM)
        .where(TimeSlotORM.term_id == term_id)
        .order_by(TimeSlotORM.slot_id)
    ).all()
    slot_ids = [s.slot_id for s in time_slots_orm]

    if slot_ids:
        availabilities_orm: Sequence[InstructorAvailabilityORM] = session.scalars(
            select(InstructorAvailabilityORM)
            .where(InstructorAvailabilityORM.slot_id.in_(slot_ids))
            .order_by(InstructorAvailabilityORM.availability_id)
        ).all()
    else:
        availabilities_orm = []

    offerings_orm = session.scalars(
        select(CourseOfferingORM)
        .where(CourseOfferingORM.term_id == term_id)
        .order_by(CourseOfferingORM.offering_id)
    ).all()
    offering_ids = [o.offering_id for o in offerings_orm]

    if offering_ids:
        enrollments_orm: Sequence[EnrollmentORM] = session.scalars(
            select(EnrollmentORM)
            .where(EnrollmentORM.offering_id.in_(offering_ids))
            .order_by(EnrollmentORM.enrollment_id)
        ).all()
    else:
        enrollments_orm = []

    configs_stmt = select(SchedulingConfigORM).where(SchedulingConfigORM.term_id == term_id)
    if config_id is not None:
        target_cfg = session.get(SchedulingConfigORM, config_id)
        if target_cfg is None or target_cfg.term_id != term_id:
            raise ValueError(
                f"SchedulingConfig with config_id={config_id} for term_id={term_id} does not exist."
            )
        configs_stmt = configs_stmt.where(SchedulingConfigORM.config_id == config_id)
    configs_orm = session.scalars(configs_stmt.order_by(SchedulingConfigORM.config_id)).all()
    config_ids = [c.config_id for c in configs_orm]

    if config_ids:
        rules_orm: Sequence[ConstraintRuleORM] = session.scalars(
            select(ConstraintRuleORM)
            .where(ConstraintRuleORM.config_id.in_(config_ids))
            .order_by(ConstraintRuleORM.rule_id)
        ).all()
    else:
        rules_orm = []

    exam_slots_orm = session.scalars(
        select(ExamSlotORM)
        .where(ExamSlotORM.term_id == term_id)
        .order_by(ExamSlotORM.exam_slot_id)
    ).all()

    schedules_orm: Sequence[ScheduleORM] = []
    timetable_entries_orm: Sequence[TimetableEntryORM] = []
    exam_entries_orm: Sequence[ExamEntryORM] = []
    exam_allocations_orm: Sequence[ExamRoomAllocationORM] = []

    if include_existing_schedules or schedule_id is not None:
        sch_stmt = select(ScheduleORM).where(ScheduleORM.term_id == term_id)
        if schedule_id is not None:
            target_sch = session.get(ScheduleORM, schedule_id)
            if target_sch is None or target_sch.term_id != term_id:
                raise ValueError(
                    f"Schedule with schedule_id={schedule_id} for term_id={term_id} does not exist."
                )
            sch_stmt = sch_stmt.where(ScheduleORM.schedule_id == schedule_id)
        schedules_orm = session.scalars(sch_stmt.order_by(ScheduleORM.schedule_id)).all()
        loaded_schedule_ids = [s.schedule_id for s in schedules_orm]

        if loaded_schedule_ids:
            timetable_entries_orm = session.scalars(
                select(TimetableEntryORM)
                .where(TimetableEntryORM.schedule_id.in_(loaded_schedule_ids))
                .order_by(TimetableEntryORM.entry_id)
            ).all()
            exam_entries_orm = session.scalars(
                select(ExamEntryORM)
                .where(ExamEntryORM.schedule_id.in_(loaded_schedule_ids))
                .order_by(ExamEntryORM.exam_entry_id)
            ).all()
            exam_entry_ids = [e.exam_entry_id for e in exam_entries_orm]
            if exam_entry_ids:
                exam_allocations_orm = session.scalars(
                    select(ExamRoomAllocationORM)
                    .where(ExamRoomAllocationORM.exam_entry_id.in_(exam_entry_ids))
                    .order_by(ExamRoomAllocationORM.allocation_id)
                ).all()

    allocations_domain = [
        ExamRoomAllocation(
            allocation_id=a.allocation_id,
            exam_entry_id=a.exam_entry_id,
            room_id=a.room_id,
            seats_allocated=a.seats_allocated,
        )
        for a in exam_allocations_orm
    ]
    allocs_by_entry: dict[int, list[ExamRoomAllocation]] = {}
    for alloc in allocations_domain:
        allocs_by_entry.setdefault(alloc.exam_entry_id, []).append(alloc)

    exam_entries_domain = [
        ExamEntry(
            exam_entry_id=e.exam_entry_id,
            schedule_id=e.schedule_id,
            course_id=e.course_id,
            exam_slot_id=e.exam_slot_id,
            student_count=e.student_count,
            is_locked=bool(e.is_locked),
            is_manual_override=bool(e.is_manual_override),
            room_allocations=list(allocs_by_entry.get(e.exam_entry_id, [])),
        )
        for e in exam_entries_orm
    ]

    return TimetableDataset(
        departments=[
            Department(
                department_id=d.department_id,
                code=d.code,
                name=d.name,
            )
            for d in departments_orm
        ],
        academic_terms=[
            AcademicTerm(
                term_id=term_orm.term_id,
                name=term_orm.name,
                start_date=_format_date(term_orm.start_date),
                end_date=_format_date(term_orm.end_date),
                status=term_orm.status,
            )
        ],
        time_slots=[
            TimeSlot(
                slot_id=s.slot_id,
                term_id=s.term_id,
                day_of_week=s.day_of_week,
                slot_index=s.slot_index,
                start_time=_format_time(s.start_time),
                end_time=_format_time(s.end_time),
                is_blocked=bool(s.is_blocked),
                block_reason=s.block_reason,
            )
            for s in time_slots_orm
        ],
        batches=[
            Batch(
                batch_id=b.batch_id,
                department_id=b.department_id,
                program_code=b.program_code,
                batch_year=b.batch_year,
                section=b.section,
                strength=b.strength,
                is_active=bool(b.is_active),
            )
            for b in batches_orm
        ],
        courses=[
            Course(
                course_id=c.course_id,
                course_code=c.course_code,
                title=c.title,
                department_id=c.department_id,
                credit_hours=c.credit_hours,
                lecture_hours=c.lecture_hours,
                lab_hours=c.lab_hours,
                is_active=bool(c.is_active),
            )
            for c in courses_orm
        ],
        instructors=[
            Instructor(
                instructor_id=i.instructor_id,
                department_id=i.department_id,
                full_name=i.full_name,
                email=i.email,
                max_daily_hours=i.max_daily_hours,
                max_weekly_hours=i.max_weekly_hours,
                is_active=bool(i.is_active),
            )
            for i in instructors_orm
        ],
        instructor_availability=[
            InstructorAvailability(
                availability_id=a.availability_id,
                instructor_id=a.instructor_id,
                slot_id=a.slot_id,
                is_available=bool(a.is_available),
            )
            for a in availabilities_orm
        ],
        rooms=[
            Room(
                room_id=r.room_id,
                room_code=r.room_code,
                building=r.building,
                capacity=r.capacity,
                room_type=r.room_type,
                is_active=bool(r.is_active),
            )
            for r in rooms_orm
        ],
        course_offerings=[
            CourseOffering(
                offering_id=o.offering_id,
                term_id=o.term_id,
                course_id=o.course_id,
                batch_id=o.batch_id,
                instructor_id=o.instructor_id,
                enrolled_count=o.enrolled_count,
            )
            for o in offerings_orm
        ],
        scheduling_configs=[
            SchedulingConfig(
                config_id=cfg.config_id,
                term_id=cfg.term_id,
                schedule_type=cfg.schedule_type,
                name=cfg.name,
                solver_time_limit_s=cfg.solver_time_limit_s,
                random_seed=cfg.random_seed,
                created_by=cfg.created_by,
                created_at=_format_datetime(cfg.created_at) or "2026-10-20T09:00:00Z",
            )
            for cfg in configs_orm
        ],
        constraint_rules=[
            ConstraintRule(
                rule_id=cr.rule_id,
                config_id=cr.config_id,
                rule_code=cr.rule_code,
                rule_type=cr.rule_type,
                is_enabled=bool(cr.is_enabled),
                weight=cr.weight,
                param_value=cr.param_value,
            )
            for cr in rules_orm
        ],
        schedules=[
            Schedule(
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
                generated_by=sch.generated_by,
                generated_at=_format_datetime(sch.generated_at) or "2026-10-20T09:15:00Z",
                approved_by=sch.approved_by,
                published_at=_format_datetime(sch.published_at),
            )
            for sch in schedules_orm
        ],
        timetable_entries=[
            TimetableEntry(
                entry_id=te.entry_id,
                schedule_id=te.schedule_id,
                offering_id=te.offering_id,
                instructor_id=te.instructor_id,
                batch_id=te.batch_id,
                room_id=te.room_id,
                slot_id=te.slot_id,
                session_type=te.session_type,
                is_locked=bool(te.is_locked),
                is_manual_override=bool(te.is_manual_override),
            )
            for te in timetable_entries_orm
        ],
        enrollments=[
            Enrollment(
                enrollment_id=enr.enrollment_id,
                offering_id=enr.offering_id,
                student_id=enr.student_id,
            )
            for enr in enrollments_orm
        ],
        exam_slots=[
            ExamSlot(
                exam_slot_id=es.exam_slot_id,
                term_id=es.term_id,
                exam_date=_format_date(es.exam_date),
                start_time=_format_time(es.start_time),
                end_time=_format_time(es.end_time),
                label=es.label,
                session_label=es.label,
            )
            for es in exam_slots_orm
        ],
        exam_entries=exam_entries_domain,
        exam_room_allocations=allocations_domain,
    )


def _next_schedule_version(session: Session, term_id: int, schedule_type: str) -> int:
    """Compute the next sequential `version_no` for `(term_id, schedule_type)` (`SAF-2`)."""
    from backend.schedule_integrity import lock_inputs
    lock_inputs(session)
    max_version = session.scalar(
        select(func.max(ScheduleORM.version_no)).where(
            ScheduleORM.term_id == term_id,
            ScheduleORM.schedule_type == schedule_type,
        )
    )
    if int(max_version or 0)>=32767:
        from backend.schedule_integrity import SnapshotIntegrityError
        raise SnapshotIntegrityError("Schedule version number range exhausted; no version was allocated.")
    return int(max_version or 0) + 1


def _build_conflict_log_rows(
    schedule_id: int,
    term_id: int,
    violations: Sequence[Violation],
    reasons: Sequence[str],
) -> list[ConflictLogORM]:
    """Convert validator `Violation` items and solver infeasibility `reasons` into `ConflictLogORM` rows."""
    rows: list[ConflictLogORM] = []
    seen_descriptions: set[str] = set()

    for v in violations:
        severity = v.severity if v.severity in ("Hard", "Warning") else "Hard"
        conflict_type = (v.conflict_type or v.rule_code or "ConstraintViolation")[:30]
        entity_ref = v.entity_ref[:100] if v.entity_ref else None
        rows.append(
            ConflictLogORM(
                schedule_id=schedule_id,
                conflict_type=conflict_type,
                severity=severity,
                description=v.description,
                entity_ref=entity_ref,
                is_resolved=False,
            )
        )
        seen_descriptions.add(v.description)

    for reason in reasons:
        if reason in seen_descriptions:
            continue
        rows.append(
            ConflictLogORM(
                schedule_id=schedule_id,
                conflict_type="InfeasibleSchedule",
                severity="Hard",
                description=reason,
                entity_ref=f"term_id={term_id}",
                is_resolved=False,
            )
        )
        seen_descriptions.add(reason)

    return rows


def save_timetable_result(
    session_or_factory: Session | sessionmaker[Session] | Engine,
    result: TimetableSolveResult,
    *,
    term_id: int,
    config_id: int,
    generated_by: int,
    version_no: int | None = None,
    schedule_id: int | None = None,
    source_context: dict | None = None,
    run_token: str | None = None,
) -> ScheduleORM:
    """Persist a `TimetableSolveResult` inside a single atomic database transaction (`DB-6`, `SAF-2`).

    Writes:
    1. A new `schedules` version row (or updates an existing `'Generating'` row when `schedule_id`
       is provided) with `status='Generated'` or `'Infeasible'`.
    2. All `timetable_entries` rows (when feasible).
    3. All `conflict_log` rows for any violations or infeasibility diagnostics.
    4. An `audit_logs` entry recording the solver run.

    Any database or validation error rolls back the entire transaction so existing
    schedules remain untouched (`SAF-2`).
    """
    with session_scope(session_or_factory) as session:
        from backend.schedule_integrity import lock_inputs, finish_version
        lock_inputs(session)
        from backend.generation import guard_save, finish_run
        if schedule_id is not None: guard_save(session,schedule_id,run_token)
        is_feasible = result.solver_status in ("optimal", "feasible") and not any(
            v.severity == "Hard" for v in result.violations
        )
        schedule_status = "Generated" if is_feasible else "Infeasible"
        obj_score = (
            result.schedule_record.objective_score
            if result.schedule_record is not None
            else None
        )

        if schedule_id is not None:
            schedule_orm = session.get(ScheduleORM, schedule_id)
            if schedule_orm is None:
                raise ValueError(f"Schedule with schedule_id={schedule_id} does not exist.")
            if schedule_orm.status != "Generating" or schedule_orm.term_id != term_id or schedule_orm.config_id != config_id or schedule_orm.schedule_type != "Timetable":
                raise ValueError("Only the matching Generating version may receive a solver result.")
            schedule_orm.status = schedule_status
            schedule_orm.solver_status = result.solver_status
            schedule_orm.objective_score = _to_decimal(obj_score)
            schedule_orm.run_seconds = _to_decimal(max(0.0, float(result.run_time)))
            resolved_version = schedule_orm.version_no
            session.flush()
        else:
            resolved_version = (
                version_no
                if version_no is not None
                else _next_schedule_version(session, term_id, "Timetable")
            )
            schedule_orm = ScheduleORM(
                term_id=term_id,
                config_id=config_id,
                schedule_type="Timetable",
                version_no=resolved_version,
                status=schedule_status,
                solver_status=result.solver_status,
                objective_score=_to_decimal(obj_score),
                run_seconds=_to_decimal(max(0.0, float(result.run_time))),
                generated_by=generated_by,
            )
            session.add(schedule_orm)
            session.flush()  # Obtain `schedule_orm.schedule_id` within the transaction

        if is_feasible:
            for entry in result.schedule:
                session.add(
                    TimetableEntryORM(
                        schedule_id=schedule_orm.schedule_id,
                        offering_id=entry.offering_id,
                        instructor_id=entry.instructor_id,
                        batch_id=entry.batch_id,
                        room_id=entry.room_id,
                        slot_id=entry.slot_id,
                        session_type=entry.session_type,
                        is_locked=bool(entry.is_locked),
                        is_manual_override=bool(entry.is_manual_override),
                    )
                )

        conflict_rows = _build_conflict_log_rows(
            schedule_id=schedule_orm.schedule_id,
            term_id=term_id,
            violations=result.violations,
            reasons=result.reasons if not is_feasible else [],
        )
        session.add_all(conflict_rows)

        session.add(
            AuditLogORM(
                user_id=generated_by,
                action="GENERATE_TIMETABLE",
                entity_type="schedules",
                entity_id=schedule_orm.schedule_id,
                details=(
                    f"term_id={term_id}, version_no={resolved_version}, "
                    f"status={schedule_status}, solver_status={result.solver_status}, "
                    f"entries={len(result.schedule) if is_feasible else 0}"
                ),
            )
        )
        session.flush()
        if is_feasible:
            finish_version(session, schedule_orm, source_context)
            from backend.manual_edits import generation_baseline
            generation_baseline(session,schedule_orm,source_context)
        finish_run(session,schedule_orm.schedule_id,run_token)
        return schedule_orm


def save_exam_result(
    session_or_factory: Session | sessionmaker[Session] | Engine,
    result: ExamScheduleResult,
    *,
    term_id: int,
    config_id: int,
    generated_by: int,
    version_no: int | None = None,
    schedule_id: int | None = None,
    source_context: dict | None = None,
    run_token: str | None = None,
) -> ScheduleORM:
    """Persist an `ExamScheduleResult` inside a single atomic database transaction (`DB-6`, `SAF-2`).

    Writes:
    1. A new `schedules` version row (or updates an existing `'Generating'` row when `schedule_id`
       is provided) with `schedule_type='Exam'`, `status='Generated'` or `'Infeasible'`.
    2. All `exam_entries` and `exam_room_allocations` rows (when feasible).
    3. All `conflict_log` rows for any violations or infeasibility diagnostics.
    4. An `audit_logs` entry recording the examination scheduler run.
    """
    with session_scope(session_or_factory) as session:
        from backend.schedule_integrity import lock_inputs, finish_version
        lock_inputs(session)
        from backend.generation import guard_save, finish_run
        if schedule_id is not None: guard_save(session,schedule_id,run_token)
        is_feasible = result.status in ("optimal", "feasible") and not any(
            v.severity == "Hard" for v in result.violations
        )
        schedule_status = "Generated" if is_feasible else "Infeasible"
        obj_score = (
            result.objective_score
            if result.objective_score is not None
            else (result.schedule.objective_score if result.schedule is not None else None)
        )

        if schedule_id is not None:
            schedule_orm = session.get(ScheduleORM, schedule_id)
            if schedule_orm is None:
                raise ValueError(f"Schedule with schedule_id={schedule_id} does not exist.")
            if schedule_orm.status != "Generating" or schedule_orm.term_id != term_id or schedule_orm.config_id != config_id or schedule_orm.schedule_type != "Exam":
                raise ValueError("Only the matching Generating version may receive a solver result.")
            schedule_orm.status = schedule_status
            schedule_orm.solver_status = result.status
            schedule_orm.objective_score = _to_decimal(obj_score)
            schedule_orm.run_seconds = _to_decimal(max(0.0, float(result.run_time_s)))
            resolved_version = schedule_orm.version_no
            session.flush()
        else:
            resolved_version = (
                version_no
                if version_no is not None
                else _next_schedule_version(session, term_id, "Exam")
            )
            schedule_orm = ScheduleORM(
                term_id=term_id,
                config_id=config_id,
                schedule_type="Exam",
                version_no=resolved_version,
                status=schedule_status,
                solver_status=result.status,
                objective_score=_to_decimal(obj_score),
                run_seconds=_to_decimal(max(0.0, float(result.run_time_s))),
                generated_by=generated_by,
            )
            session.add(schedule_orm)
            session.flush()

        if is_feasible:
            top_allocs_by_old_entry_id: dict[int, list[ExamRoomAllocation]] = {}
            for alloc in result.room_allocations:
                top_allocs_by_old_entry_id.setdefault(alloc.exam_entry_id, []).append(alloc)

            for entry in result.entries:
                exam_entry_orm = ExamEntryORM(
                    schedule_id=schedule_orm.schedule_id,
                    course_id=entry.course_id,
                    exam_slot_id=entry.exam_slot_id,
                    student_count=entry.student_count,
                    is_manual_override=bool(entry.is_manual_override),
                    is_locked=bool(entry.is_locked),
                )
                session.add(exam_entry_orm)
                session.flush()  # Obtain `exam_entry_orm.exam_entry_id`

                entry_allocs = (
                    list(entry.room_allocations)
                    if entry.room_allocations
                    else top_allocs_by_old_entry_id.get(entry.exam_entry_id, [])
                )
                for alloc in entry_allocs:
                    session.add(
                        ExamRoomAllocationORM(
                            exam_entry_id=exam_entry_orm.exam_entry_id,
                            room_id=alloc.room_id,
                            seats_allocated=alloc.seats_allocated,
                        )
                    )

        conflict_rows = _build_conflict_log_rows(
            schedule_id=schedule_orm.schedule_id,
            term_id=term_id,
            violations=result.violations,
            reasons=result.reasons if not is_feasible else [],
        )
        session.add_all(conflict_rows)

        session.add(
            AuditLogORM(
                user_id=generated_by,
                action="GENERATE_EXAM_SCHEDULE",
                entity_type="schedules",
                entity_id=schedule_orm.schedule_id,
                details=(
                    f"term_id={term_id}, version_no={resolved_version}, "
                    f"status={schedule_status}, solver_status={result.status}, "
                    f"entries={len(result.entries) if is_feasible else 0}"
                ),
            )
        )
        session.flush()
        if is_feasible:
            finish_version(session, schedule_orm, source_context)
            from backend.manual_edits import generation_baseline
            generation_baseline(session,schedule_orm,source_context)
        finish_run(session,schedule_orm.schedule_id,run_token)
        return schedule_orm


def save_engine_result(
    session_or_factory: Session | sessionmaker[Session] | Engine,
    result: TimetableSolveResult | ExamScheduleResult,
    *,
    term_id: int,
    config_id: int,
    generated_by: int,
    version_no: int | None = None,
    schedule_id: int | None = None,
    source_context: dict | None = None,
) -> ScheduleORM:
    """Unified dispatcher that persists either a `TimetableSolveResult` or `ExamScheduleResult` in one transaction."""
    if isinstance(result, TimetableSolveResult):
        return save_timetable_result(
            session_or_factory,
            result,
            term_id=term_id,
            config_id=config_id,
            generated_by=generated_by,
            version_no=version_no,
            schedule_id=schedule_id,
            source_context=source_context,
        )
    if isinstance(result, ExamScheduleResult):
        return save_exam_result(
            session_or_factory,
            result,
            term_id=term_id,
            config_id=config_id,
            generated_by=generated_by,
            version_no=version_no,
            schedule_id=schedule_id,
            source_context=source_context,
        )
    raise TypeError(
        f"Unsupported engine result type: {type(result).__name__}. "
        "Expected TimetableSolveResult or ExamScheduleResult."
    )


class TermScheduleAdapter:
    """High-level adapter binding a SQLAlchemy session/factory to the ATES scheduling engine."""

    def __init__(self, session_or_factory: Session | sessionmaker[Session] | Engine) -> None:
        self._session_or_factory = session_or_factory

    def load_term(
        self,
        term_id: int,
        *,
        config_id: int | None = None,
        schedule_id: int | None = None,
        include_existing_schedules: bool = True,
    ) -> TimetableDataset:
        """Load `term_id` from the database into an `engine.models.TimetableDataset`."""
        if isinstance(self._session_or_factory, Session):
            from backend.schedule_integrity import lock_inputs
            lock_inputs(self._session_or_factory)
            dataset = load_term_dataset(
                self._session_or_factory,
                term_id=term_id,
                config_id=config_id,
                schedule_id=schedule_id,
                include_existing_schedules=include_existing_schedules,
            )
        else:
            with session_scope(self._session_or_factory) as session:
                from backend.schedule_integrity import lock_inputs
                lock_inputs(session)
                dataset = load_term_dataset(
                session,
                term_id=term_id,
                config_id=config_id,
                schedule_id=schedule_id,
                include_existing_schedules=include_existing_schedules,
                )
        self._loaded_inputs = deepcopy(dataset) if schedule_id is None else None
        return dataset

    def save_result(
        self,
        result: TimetableSolveResult | ExamScheduleResult,
        *,
        term_id: int,
        config_id: int,
        generated_by: int,
        version_no: int | None = None,
    ) -> ScheduleORM:
        """Save a `TimetableSolveResult` or `ExamScheduleResult` back to the database in one transaction."""
        from backend.schedule_integrity import make_context
        source = getattr(self, "_loaded_inputs", None)
        context = make_context(source, term_id, "Timetable" if isinstance(result, TimetableSolveResult) else "Exam", config_id) if source is not None else None
        return save_engine_result(
            self._session_or_factory,
            result,
            term_id=term_id,
            config_id=config_id,
            generated_by=generated_by,
            version_no=version_no,
            source_context=context,
        )
