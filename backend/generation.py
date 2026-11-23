"""Real spawned generation processes, durable cancellation and commit fencing."""
from datetime import timedelta
import multiprocessing
import os
import threading
import time
import uuid

from sqlalchemy import event, select, update
from sqlalchemy.orm import Session

from backend.auth import utc_now
from backend.database import create_db_engine, create_session_factory, session_scope
from backend.models import GenerationRun, Schedule, ConflictLog
from backend.schedule_integrity import lock_inputs, SnapshotIntegrityError
from engine.execution import budget_until, check_deadline, DeadlineExceeded

ACTIVE = {"Queued", "Running"}
LEASE_SECONDS = 15
_processes = {}
_registry_lock = threading.RLock()
_slots = threading.BoundedSemaphore(2)


class RunStopped(RuntimeError):
    pass


def new_run(schedule_id, limit, seed, started=None):
    started = started or utc_now()
    return GenerationRun(schedule_id=schedule_id,owner_token=uuid.uuid4().hex,state="Queued",phase="Queued",
        started_at=started,deadline_at=started+timedelta(seconds=limit),lease_until=utc_now()+timedelta(seconds=LEASE_SECONDS),
        time_limit_s=limit,random_seed=seed)


def guard_save(session, schedule_id, token):
    run = session.scalar(select(GenerationRun).where(GenerationRun.schedule_id==schedule_id).execution_options(populate_existing=True))
    if run is None:
        if token is not None: raise RunStopped("Generation ownership was lost.")
        return
    if token != run.owner_token or run.state != "Running":
        raise RunStopped("The generation run is no longer active or owned by this worker.")
    if utc_now() >= run.deadline_at or utc_now() >= run.lease_until:
        raise DeadlineExceeded("The generation deadline or worker lease expired.")
    check_deadline()
    session.info["generation_fence"] = (schedule_id,token)


def finish_run(session, schedule_id, token):
    if token is None: return
    guard_save(session,schedule_id,token)
    run = session.get(GenerationRun,schedule_id)
    run.state,run.phase,run.ended_at = "Completed","Terminal",utc_now()
    session.info["generation_finalizing"] = True
    session.flush()


@event.listens_for(Session,"before_commit")
def _commit_fence(session):
    fence = session.info.get("generation_fence")
    if not fence: return
    session.flush()
    run = session.get(GenerationRun,fence[0],populate_existing=True)
    if (run is None or run.owner_token!=fence[1] or run.state!="Completed"
            or not session.info.get("generation_finalizing")):
        raise RunStopped("Generation completion lost its commit fence.")
    if utc_now()>=run.deadline_at or utc_now()>=run.lease_until:
        raise DeadlineExceeded("The generation deadline expired before commit.")
    check_deadline()


@event.listens_for(Session,"after_transaction_end")
def _clear_fence(session,transaction):
    if transaction.parent is None:
        session.info.pop("generation_fence",None)
        session.info.pop("generation_finalizing",None)


def terminal(session, schedule, state, reason, conflict_type=None):
    """Caller holds the shared input/run lock; never rewrite a completed version."""
    if schedule.status != "Generating": return False
    run = session.get(GenerationRun,schedule.schedule_id)
    if run is not None:
        if run.state not in ACTIVE: return False
        run.state,run.phase,run.ended_at = state,"Terminal",utc_now()
        schedule.run_seconds=max(0,(run.ended_at-run.started_at).total_seconds())
    schedule.status,schedule.solver_status = "Infeasible","interrupted"
    session.add(ConflictLog(schedule_id=schedule.schedule_id,conflict_type=conflict_type or state,severity="Hard",description=reason,
                            entity_ref=f"schedule_id={schedule.schedule_id}",is_resolved=False))
    return True


def fail_run(factory,sid,state,reason,token=None):
    with session_scope(factory) as session:
        lock_inputs(session)
        run = session.get(GenerationRun,sid)
        if token is not None and (run is None or run.owner_token!=token): return
        sch = session.get(Schedule,sid)
        if sch is not None: terminal(session,sch,state,reason)


def recover_runs(factory):
    with session_scope(factory) as session:
        lock_inputs(session)
        count=0; now=utc_now()
        for sch in session.scalars(select(Schedule).where(Schedule.status=="Generating")):
            run=session.get(GenerationRun,sch.schedule_id)
            if run is not None and run.state in ACTIVE and run.lease_until>now and run.deadline_at>now:
                continue  # Another live supervisor may own this job.
            state="TimedOut" if run is not None and run.deadline_at<=now else "Interrupted"
            if run is not None and run.state not in ACTIVE:
                # Repair an inconsistent legacy header without resurrecting a job.
                sch.status,sch.solver_status="Infeasible","interrupted"
                session.add(ConflictLog(schedule_id=sch.schedule_id,conflict_type="ServerRestart",severity="Hard",description="Interrupted run header recovered.",is_resolved=False))
                count+=1
            else:
                count += int(terminal(session,sch,state,"Generation run interrupted by server restart or expired worker lease.","ServerRestart"))
        return count


def _watchdog(factory,sid,token,end,done):
    while not done.wait(.1):
        if time.monotonic()>=end: os._exit(124)
        try:
            with factory() as session:
                run=session.get(GenerationRun,sid)
                if run is None or run.owner_token!=token or run.state not in ACTIVE or run.lease_until<=utc_now():
                    # A successful commit also makes state Completed; leave normally
                    # when main has finished, otherwise exiting is safe after commit.
                    os._exit(125)
        except Exception:
            os._exit(126)  # Lost authority/database connectivity: fail closed.


def _deadline_watchdog(end,done):
    # Never put database I/O on this timer: a locked/unreachable database must
    # not prevent preemption of loading, model construction or persistence.
    if not done.wait(max(0,end-time.monotonic())):
        os._exit(124)


def _process_main(url,sid,token,end):
    done=threading.Event()
    threading.Thread(target=_deadline_watchdog,args=(end,done),daemon=True).start()
    try:
        engine=create_db_engine(url); factory=create_session_factory(engine)
        threading.Thread(target=_watchdog,args=(factory,sid,token,end,done),daemon=True).start()
        with budget_until(end):
            from backend.generation_execution import execute_generation
            execute_generation(factory,sid,token)
    except DeadlineExceeded:
        try: fail_run(factory,sid,"TimedOut","The end-to-end generation deadline expired.",token)
        except Exception: pass
    except Exception as exc:
        reason=str(exc) if isinstance(exc,(SnapshotIntegrityError,RunStopped)) else f"Generation worker failed ({type(exc).__name__})."
        try: fail_run(factory,sid,"Interrupted",reason,token)
        except Exception: pass
    finally:
        done.set()
        if 'engine' in locals(): engine.dispose()


def stop_local(token):
    with _registry_lock:
        process=_processes.get(token)
        if process is None: return False
        if process.is_alive(): process.terminate()
        process.join(1)
        if process.is_alive(): process.kill(); process.join(1)
        return not process.is_alive()


def acknowledge_stop(factory,sid,token):
    with session_scope(factory) as session:
        run=session.get(GenerationRun,sid)
        if run is not None and run.owner_token==token:
            run.worker_stopped_at=utc_now()


def supervise(factory,sid,deadline=None):
    """I/O supervision only; all database loading/CPU/validation/save is in a child."""
    process=None; acquired=False; token=None
    try:
        with factory() as session:
            run=session.get(GenerationRun,sid)
            if run is None: raise RunStopped("Generation run-control migration/record is missing.")
            token=run.owner_token
            end=time.monotonic()+max(0,(run.deadline_at-utc_now()).total_seconds())
            if deadline is not None: end=min(end,deadline)
        while not _slots.acquire(timeout=.1):
            with session_scope(factory) as session:
                run=session.get(GenerationRun,sid)
                if run.state not in ACTIVE: return
                run.lease_until=utc_now()+timedelta(seconds=LEASE_SECONDS)
            if time.monotonic()>=end: raise DeadlineExceeded()
        acquired=True
        engine=factory.kw['bind']; url=engine.url.render_as_string(hide_password=False)
        if engine.dialect.name=="sqlite" and engine.url.database in (None,"",":memory:"):
            raise RunStopped("Process generation requires a file-backed SQLite or PostgreSQL database.")
        # Lock order: registry -> input lock. Cancellation releases its DB lock
        # before acquiring registry, so it cannot acknowledge a not-yet-started child.
        with _registry_lock:
            with session_scope(factory) as session:
                lock_inputs(session)
                run=session.get(GenerationRun,sid,populate_existing=True)
                if run.state not in ACTIVE or run.owner_token!=token: return
                if time.monotonic()>=end: raise DeadlineExceeded()
                run.state,run.phase="Running","Loading"
                process=multiprocessing.get_context("spawn").Process(target=_process_main,args=(url,sid,token,end),daemon=True)
                process.start(); _processes[token]=process
                run.process_id=process.pid
        heartbeat=0
        while process.is_alive():
            process.join(.05)
            now=time.monotonic()
            if now>=end:
                stop_local(token)
                fail_run(factory,sid,"TimedOut","The end-to-end generation deadline expired.",token)
                break
            if now>=heartbeat:
                with session_scope(factory) as session:
                    run=session.get(GenerationRun,sid)
                    active=run.state in ACTIVE and run.owner_token==token
                    if active: run.lease_until=utc_now()+timedelta(seconds=LEASE_SECONDS)
                if not active: stop_local(token); break
                heartbeat=now+0.2
        process.join()
        with factory() as session: state=session.get(GenerationRun,sid).state
        if state in ACTIVE:
            fail_run(factory,sid,"TimedOut" if time.monotonic()>=end else "Interrupted",
                     "Worker exited before committing a complete result.",token)
    except DeadlineExceeded:
        if token: fail_run(factory,sid,"TimedOut","The end-to-end generation deadline expired.",token)
    except Exception as exc:
        if token:
            reason=str(exc) if isinstance(exc,RunStopped) else f"Generation supervisor failed ({type(exc).__name__})."
            fail_run(factory,sid,"Interrupted",reason,token)
    finally:
        if process is not None:
            stop_local(token)
            if not process.is_alive(): acknowledge_stop(factory,sid,token)
            with _registry_lock: _processes.pop(token,None)
        elif token:
            acknowledge_stop(factory,sid,token)
        if acquired: _slots.release()
