"""Batch 1: actual child processes, persistent fences, real lifespan and API S05."""
from datetime import datetime, timedelta
import os
from pathlib import Path
import shutil
import threading
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func, text

from backend import models as m
from backend.database import create_db_engine,create_session_factory
from backend.seed import seed_database
from backend.main import create_app,recover_interrupted_generations
from backend.generation import new_run,supervise,guard_save,RunStopped
from backend.auth import utc_now
from engine.execution import budget_until,DeadlineExceeded,remaining_seconds
from engine.models import load_dataset_from_json
from engine.timetable_solver import solve_timetable
from engine.exam_scheduler import schedule_exams

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def batch_template(tmp_path_factory):
    path=tmp_path_factory.mktemp("batch1_seed")/"template.sqlite"
    engine=create_db_engine(f"sqlite:///{path.as_posix()}")
    seed_database(create_session_factory(engine));engine.dispose()
    return path


@pytest.fixture
def env(tmp_path,batch_template,test_auth_settings,login_as):
    path=tmp_path/"batch.sqlite";shutil.copyfile(batch_template,path)
    engine=create_db_engine(f"sqlite:///{path.as_posix()}");factory=create_session_factory(engine)
    client=TestClient(create_app(engine=engine,session_factory=factory,auth_settings=test_auth_settings))
    client.headers.update(login_as(client,factory))
    yield client,factory,engine
    client.close();engine.dispose()


def queue(factory,kind="Timetable",limit=10):
    with factory.begin() as session:
        version=session.scalar(select(func.max(m.Schedule.version_no)).where(m.Schedule.schedule_type==kind))+1
        sch=m.Schedule(term_id=1,config_id=1 if kind=="Timetable" else 2,schedule_type=kind,version_no=version,status="Generating",generated_by=1)
        session.add(sch);session.flush()
        session.add(new_run(sch.schedule_id,limit,1))
        return sch.schedule_id


def wait_until(predicate,timeout=10):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        value=predicate()
        if value:return value
        time.sleep(.02)
    raise AssertionError("Condition did not become true before the test deadline")


@pytest.mark.parametrize("kind",["Timetable","Exam"])
def test_real_process_cancellation_is_authorized_fenced_and_acknowledged(env,kind):
    client,factory,_=env
    sid=queue(factory,kind,30)
    # Hold the ordinary capture lock so cancellation lands during real input
    # loading rather than racing a tiny solver fixture to completion.
    blocker=factory();blocker.begin()
    from backend.schedule_integrity import lock_inputs
    # Start supervisor first; observe its actual process before taking capture lock.
    thread=threading.Thread(target=supervise,args=(factory,sid));thread.start()
    def started():
        with factory() as session:
            run=session.get(m.GenerationRun,sid)
            return run.process_id
    pid=wait_until(started)
    assert pid!=os.getpid()
    lock_inputs(blocker)
    # Cancellation waits for this same transaction lock; release it immediately
    # after the request is issued so the durable cancellation wins before capture.
    responses=[]
    request=threading.Thread(target=lambda:responses.append(client.post(f"/schedules/{sid}/cancel")))
    request.start();time.sleep(.05);blocker.rollback();blocker.close()
    request.join(5);thread.join(5)
    assert not request.is_alive() and not thread.is_alive()
    assert responses[0].status_code==200, responses[0].text
    assert responses[0].json()["generation_state"]=="Cancelled"
    assert responses[0].json()["worker_stopped"] is True
    with factory() as session:
        assert session.get(m.Schedule,sid).status=="Infeasible"
        assert session.get(m.ScheduleSnapshot,sid) is None
        assert session.get(m.GenerationRun,sid).worker_stopped_at is not None
        assert session.scalar(select(func.count()).select_from(m.TimetableEntry).where(m.TimetableEntry.schedule_id==sid))==0
        assert session.scalar(select(func.count()).select_from(m.ExamEntry).where(m.ExamEntry.schedule_id==sid))==0


def test_anonymous_forged_and_nonowner_cancellation_are_denied(env,login_as,test_password_hash):
    client,factory,_=env;sid=queue(factory)
    token=dict(client.headers)
    client.headers.clear()
    assert client.post(f"/schedules/{sid}/cancel",headers={"X-User-Role":"Coordinator","X-User-Id":"1"}).status_code==401
    student=login_as(client,factory,"cs24a_9002")
    assert client.post(f"/schedules/{sid}/cancel",headers=student).status_code==403
    with factory.begin() as session:
        session.add(m.User(user_id=999,username="othercoordinator",password_hash=test_password_hash,full_name="Other Coordinator",email="other@example.test",role="Coordinator",account_status="Active"))
    other=login_as(client,factory,"othercoordinator")
    assert client.post(f"/schedules/{sid}/cancel",headers=other).status_code==403
    client.headers.update(token)
    assert client.post(f"/schedules/{sid}/cancel").status_code==200
    assert client.post(f"/schedules/{sid}/cancel").status_code==200


def test_cancellation_stops_worker_after_real_model_phase_begins(env):
    client,factory,_=env;responses=[]
    thread=threading.Thread(target=lambda:responses.append(client.post("/schedules/generate",json={"term_id":1,"config_id":1,"solver_time_limit_s":60})))
    thread.start()
    def solving():
        with factory() as session:
            return session.scalar(select(m.GenerationRun.schedule_id).where(m.GenerationRun.state=="Running",m.GenerationRun.phase=="Solving"))
    sid=wait_until(solving,timeout=45)
    response=client.post(f"/schedules/{sid}/cancel")
    thread.join(5)
    assert response.status_code==200,response.text
    assert response.json()["worker_stopped"] is True
    assert not thread.is_alive()
    assert responses[0].status_code==202
    with factory() as session:
        assert session.get(m.ScheduleSnapshot,sid) is None
        assert session.get(m.GenerationRun,sid).state=="Cancelled"


def test_deadline_at_commit_rolls_back_header_and_terminal_state(env):
    from backend.generation import finish_run
    _,factory,_=env;sid=queue(factory)
    with factory.begin() as session:
        run=session.get(m.GenerationRun,sid);run.state="Running";token=run.owner_token
    with pytest.raises(DeadlineExceeded):
        with factory.begin() as session:
            from backend.schedule_integrity import lock_inputs
            lock_inputs(session)
            guard_save(session,sid,token)
            session.get(m.Schedule,sid).status="Generated"
            finish_run(session,sid,token)
            # Expiration after all writes but before commit must roll back both.
            session.get(m.GenerationRun,sid).deadline_at=utc_now()-timedelta(seconds=1)
    with factory() as session:
        assert session.get(m.Schedule,sid).status=="Generating"
        assert session.get(m.GenerationRun,sid).state=="Running"
        assert session.get(m.ScheduleSnapshot,sid) is None


@pytest.mark.parametrize("kind",["Timetable","Exam"])
def test_deadline_stops_real_process_including_spawn_and_loading(env,kind):
    _,factory,_=env
    # Internal run-control accepts a short budget for this real timeout test;
    # the public API continues enforcing the SRS 10..600-second range.
    sid=queue(factory,kind,.05)
    start=time.monotonic();supervise(factory,sid)
    assert time.monotonic()-start<3
    with factory() as session:
        assert session.get(m.GenerationRun,sid).state=="TimedOut"
        assert session.get(m.Schedule,sid).status=="Infeasible"
        assert session.get(m.ScheduleSnapshot,sid) is None


def test_completion_wins_race_and_cannot_be_relabelled_cancelled(env):
    client,factory,_=env
    result=client.post("/schedules/generate",json={"term_id":1,"config_id":2,"solver_time_limit_s":10})
    assert result.status_code==202
    sid=result.json()["schedule_id"]
    assert client.get(f"/schedules/{sid}/status").json()["status"]=="Generated"
    assert client.post(f"/schedules/{sid}/cancel").status_code==409
    with factory() as session:
        assert session.get(m.GenerationRun,sid).state=="Completed"
        assert session.get(m.ScheduleSnapshot,sid) is not None


@pytest.mark.parametrize("state",["Cancelled","TimedOut","Interrupted"])
def test_terminal_and_wrong_owner_workers_cannot_save(env,state):
    _,factory,_=env;sid=queue(factory)
    with factory.begin() as session:
        run=session.get(m.GenerationRun,sid);token=run.owner_token;run.state=state
    with factory() as session:
        with pytest.raises(RunStopped):guard_save(session,sid,token)
    with factory.begin() as session: session.get(m.GenerationRun,sid).state="Running"
    with factory() as session:
        with pytest.raises(RunStopped):guard_save(session,sid,"forged-worker-token")


def test_shared_budget_does_not_reset_for_repeated_calls():
    with budget_until(time.monotonic()+.1):
        a=remaining_seconds(5);time.sleep(.02);b=remaining_seconds(5)
        assert 0<b<a<.11
    with pytest.raises(DeadlineExceeded):
        with budget_until(time.monotonic()-.1): pass


@pytest.mark.parametrize("kind",["Timetable","Exam"])
def test_direct_engines_discard_results_after_expired_shared_budget(kind):
    ds=load_dataset_from_json(ROOT/("data/seed_timetable.json" if kind=="Timetable" else "data/seed_exam.json"))
    with pytest.raises(DeadlineExceeded):
        with budget_until(time.monotonic()+.05):
            time.sleep(.06)
            result=solve_timetable(ds,time_limit_s=10) if kind=="Timetable" else schedule_exams(ds,time_limit_s=10)
            assert (result.solver_status if kind=="Timetable" else result.status)=="unknown"
            assert (result.schedule if kind=="Timetable" else result.entries)==[]


def test_default_application_lifespan_recovers_legacy_orphans_idempotently(env,test_auth_settings):
    _,factory,engine=env
    with factory.begin() as session: session.get(m.Schedule,1).status="Generating"
    app=create_app(auth_settings=test_auth_settings)
    with patch("backend.dependencies.create_db_engine",return_value=engine):
        with TestClient(app):
            assert app.state.session_factory is not None
            with factory() as session:
                assert session.get(m.Schedule,1).status=="Infeasible"
                assert session.get(m.Schedule,2).status=="Generated"
            assert recover_interrupted_generations(factory)==0
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.ConflictLog).where(m.ConflictLog.schedule_id==1,m.ConflictLog.conflict_type=="ServerRestart"))==1


def test_recovery_respects_live_leases_and_recovers_expired_ones(env):
    _,factory,_=env;live=queue(factory);dead=queue(factory)
    with factory.begin() as session:
        run=session.get(m.GenerationRun,dead);run.state="Running";run.lease_until=utc_now()-timedelta(seconds=1)
    assert recover_interrupted_generations(factory)==1
    assert recover_interrupted_generations(factory)==0
    with factory() as session:
        assert session.get(m.Schedule,live).status=="Generating"
        assert session.get(m.Schedule,dead).status=="Infeasible"


def small_timetable(factory,*,weight=10,enabled=True,locked=False,invalid=False,no_previous=False):
    """One real offering: prefer a deliberately spacious room over S06's small one."""
    from sqlalchemy import delete
    with factory.begin() as session:
        session.execute(delete(m.ExamRoomAllocation));session.execute(delete(m.ExamEntry))
        session.execute(delete(m.TimetableEntry));session.execute(delete(m.Enrollment))
        session.execute(delete(m.CourseOffering).where(m.CourseOffering.offering_id!=1))
        course=session.get(m.Course,1);course.lecture_hours=1;course.lab_hours=0
        session.add(m.Room(room_id=100,room_code="S05-SPACIOUS",building="A",capacity=100,room_type="Lecture"))
        if not no_previous:
            session.add(m.TimetableEntry(schedule_id=1,offering_id=1,instructor_id=1,batch_id=1,slot_id=1,room_id=3 if invalid else 100,session_type="Lecture",is_locked=locked,is_manual_override=False))
        else: session.delete(session.get(m.Schedule,1))
        existing={r.rule_code for r in session.scalars(select(m.ConstraintRule).where(m.ConstraintRule.config_id==1))}
        for code in [f"S0{i}" for i in range(1,7)]:
            if code not in existing:
                session.add(m.ConstraintRule(config_id=1,rule_code=code,rule_type="Soft",weight=0,is_enabled=False))
        session.flush()
        for rule in session.scalars(select(m.ConstraintRule).where(m.ConstraintRule.config_id==1)):
            if rule.rule_type=="Soft":
                rule.is_enabled=rule.rule_code in {"S05","S06"}
                rule.weight=weight if rule.rule_code=="S05" else (1 if rule.rule_code=="S06" else 0)
            if rule.rule_code=="S05":rule.is_enabled=enabled


@pytest.mark.parametrize("weight,enabled,expected_room",[(10,True,100),(0,True,None),(10,False,None)])
def test_api_s05_unlocked_history_influences_only_enabled_positive_weight(env,weight,enabled,expected_room):
    client,factory,_=env;small_timetable(factory,weight=weight,enabled=enabled)
    res=client.post("/schedules/generate",json=dict(term_id=1,config_id=1,solver_time_limit_s=30,random_seed=7))
    sid=res.json()["schedule_id"]
    entries=client.get(f"/schedules/{sid}/entries").json()["timetable_entries"]
    assert len(entries)==1
    if expected_room:
        assert (entries[0]["slot_id"],entries[0]["room_id"])==(1,100)
    else: assert entries[0]["room_id"]!=100
    with factory() as session:
        import json
        context=json.loads(session.get(m.ScheduleSnapshot,sid).inputs_json)
        assert len(context["previous_timetable"])==1
        assert not context["dataset"]["timetable_entries"]  # Unlocked history is not pinned.


@pytest.mark.parametrize("locked,invalid,no_previous",[(True,False,False),(False,True,False),(False,False,True)])
def test_api_s05_preserves_locks_hard_constraints_and_absent_history(env,locked,invalid,no_previous):
    client,factory,_=env;small_timetable(factory,locked=locked,invalid=invalid,no_previous=no_previous)
    res=client.post("/schedules/generate",json=dict(term_id=1,config_id=1,solver_time_limit_s=30))
    sid=res.json()["schedule_id"]
    entries=client.get(f"/schedules/{sid}/entries").json()["timetable_entries"]
    assert len(entries)==1
    if locked:
        assert (entries[0]["slot_id"],entries[0]["room_id"],entries[0]["is_locked"])==(1,100,True)
    if invalid: assert entries[0]["room_id"]!=3  # 30 seats cannot serve 45 students.
    if no_previous:
        import json
        with factory() as session: assert json.loads(session.get(m.ScheduleSnapshot,sid).inputs_json)["previous_timetable"]==[]


def test_run_control_migration_is_additive_and_repeatable(tmp_path):
    engine=create_db_engine(f"sqlite:///{(tmp_path/'migration.sqlite').as_posix()}")
    m.Base.metadata.create_all(engine,tables=[t for t in m.Base.metadata.sorted_tables if t.name!="generation_runs"])
    raw=engine.raw_connection()
    try:
        migration=(ROOT/"db/migrations/003_generation_runs.sqlite.sql").read_text()
        raw.driver_connection.executescript(migration);raw.driver_connection.executescript(migration)
    finally:raw.close()
    with engine.connect() as conn: assert conn.exec_driver_sql("SELECT count(*) FROM generation_runs").scalar()==0
    engine.dispose()
