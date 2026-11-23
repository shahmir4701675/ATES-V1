"""Worker execution without importing the HTTP routers or constructing API schemas.

The supervisor owns the same end-to-end deadline, cancellation and commit fences.
"""
from sqlalchemy import select
from backend.database import session_scope
from backend.models import Schedule,GenerationRun,SchedulingConfig
from backend.adapter import save_timetable_result,save_exam_result
from backend.schedule_integrity import lock_inputs,capture_inputs
from engine.models import TimetableEntry as EngineTimetableEntry
from engine.timetable_solver import solve_timetable
from engine.exam_scheduler import schedule_exams


def execute_generation(session_factory, schedule_id, run_token):
    """Background worker that solves a timetable or exam schedule and saves in one transaction (`DB-6`, `SAF-2`)."""
    try:
        with session_scope(session_factory) as session:
            from engine.execution import check_deadline
            lock_inputs(session)
            check_deadline()
            sch = session.get(Schedule, schedule_id)
            if sch is None:
                return
            if sch.status != "Generating":
                return
            run = session.get(GenerationRun,schedule_id)
            if run is None or run.owner_token!=run_token or run.state!="Running":
                return
            time_limit_override,random_seed_override = run.time_limit_s,run.random_seed
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

            source_context = capture_inputs(session, term_id, schedule_type, config_id,
                source_schedule_id=prev_schedule_id, time_limit_override=time_limit_override,
                random_seed_override=random_seed_override)
            run.phase="Solving"
            # Solve exactly the data captured under the common source-write lock.
            from engine.models import TimetableDataset
            dataset = TimetableDataset.from_dict(source_context["dataset"])
            captured_cfg = dataset.scheduling_configs[0]
            time_limit_s = float(time_limit_override if time_limit_override is not None else captured_cfg.solver_time_limit_s)
            random_seed = int(random_seed_override if random_seed_override is not None else captured_cfg.random_seed)
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
                previous_entries=[EngineTimetableEntry(**entry) for entry in source_context["previous_timetable"]],
            )
            save_timetable_result(
                session_factory,
                tt_result,
                term_id=term_id,
                config_id=config_id,
                generated_by=generated_by,
                schedule_id=schedule_id,
                source_context=source_context,
                run_token=run_token,
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
                source_context=source_context,
                run_token=run_token,
            )
    except Exception:
        raise  # The isolated worker owns terminal-state recording and fencing.

