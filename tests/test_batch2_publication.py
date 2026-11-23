"""B008 real publication, historical context, rollback and multi-client persistence."""
from fastapi.testclient import TestClient
from sqlalchemy import select
import pytest
from backend import models as m
from backend.main import create_app
from tests.test_batch1_generation import batch_template, env
from tests.test_schedule_integrity import freeze


def clone_timetable(factory,version=2):
    with factory.begin() as session:
        row=m.Schedule(term_id=1,config_id=1,schedule_type='Timetable',version_no=version,status='Generated',generated_by=1)
        session.add(row);session.flush();sid=row.schedule_id
        for old in session.scalars(select(m.TimetableEntry).where(m.TimetableEntry.schedule_id==1)).all():
            session.add(m.TimetableEntry(schedule_id=sid,**{field:getattr(old,field) for field in ('offering_id','instructor_id','batch_id','slot_id','room_id','session_type','is_locked','is_manual_override')}))
    freeze(factory,sid)
    return sid


@pytest.mark.parametrize('username',['admin','coordinator','fakhra','cs24a_9002'])
def test_only_approvers_publish_or_archive(env,login_as,username):
    client,factory,_=env;headers=login_as(client,factory,username)
    assert client.post('/schedules/1/publish',headers=headers).status_code==403
    assert client.post('/schedules/1/archive',headers=headers).status_code==403


@pytest.mark.parametrize('sid',[1,2])
def test_publication_persists_approval_and_is_visible_to_another_client(env,login_as,test_auth_settings,sid):
    client,factory,engine=env;freeze(factory,sid)
    approver=login_as(client,factory,'approver')
    response=client.post(f'/schedules/{sid}/publish',headers={**approver,'X-User-Id':'2'})
    assert response.status_code==200,response.text
    with factory() as session:
        row=session.get(m.Schedule,sid)
        assert (row.status,row.approved_by)==('Published',3) and row.published_at is not None
        original=session.get(m.ScheduleSnapshot,sid).inputs_json
    second=TestClient(create_app(engine=engine,session_factory=factory,auth_settings=test_auth_settings))
    student=login_as(second,factory,'cs24a_9002')
    assert second.get(f'/schedules/{sid}/entries',headers=student).status_code==200
    assert client.post(f'/schedules/{sid}/publish',headers=approver).status_code==409
    assert client.post(f'/schedules/{sid}/archive',headers=approver).status_code==200
    assert second.get(f'/schedules/{sid}',headers=student).status_code==403
    with factory() as session:assert session.get(m.ScheduleSnapshot,sid).inputs_json==original
    second.close()


def test_publish_archives_only_same_term_type_and_keeps_history(env,login_as):
    client,factory,_=env;freeze(factory,1,True);freeze(factory,2,True)
    with factory() as session:old=session.get(m.ScheduleSnapshot,1).inputs_json
    new=clone_timetable(factory);headers=login_as(client,factory,'approver')
    assert client.post(f'/schedules/{new}/publish',headers=headers).status_code==200
    with factory() as session:
        assert session.get(m.Schedule,1).status=='Archived'
        assert session.get(m.Schedule,2).status=='Published'
        assert session.get(m.Schedule,new).status=='Published'
        assert session.get(m.ScheduleSnapshot,1).inputs_json==old


def test_untrusted_legacy_and_corrupt_snapshot_publication_is_rejected(env,login_as):
    client,factory,engine=env;headers=login_as(client,factory,'approver')
    assert client.post('/schedules/1/publish',headers=headers).status_code==409
    with factory() as session:assert session.get(m.ScheduleSnapshot,1) is None
    freeze(factory,1)
    with engine.begin() as conn:
        conn.exec_driver_sql('DROP TRIGGER b004_snapshot_update')
        conn.exec_driver_sql("UPDATE schedule_snapshots SET inputs_json='{}' WHERE schedule_id=1")
    assert client.post('/schedules/1/publish',headers=headers).status_code==409
    with factory() as session:assert session.get(m.Schedule,1).status=='Generated'


def test_failed_publish_rolls_back_archive_and_approval(env,login_as):
    client,factory,engine=env;freeze(factory,1,True);new=clone_timetable(factory)
    with engine.begin() as conn:
        conn.exec_driver_sql(f"CREATE TRIGGER reject_publish BEFORE UPDATE OF status ON schedules WHEN NEW.schedule_id={new} AND NEW.status='Published' BEGIN SELECT RAISE(ABORT,'test failure'); END")
    headers=login_as(client,factory,'approver')
    assert client.post(f'/schedules/{new}/publish',headers=headers).status_code==409
    with factory() as session:
        assert session.get(m.Schedule,1).status=='Published'
        row=session.get(m.Schedule,new);assert row.status=='Generated' and row.approved_by is None


def test_hard_conflicts_and_incomplete_versions_cannot_publish(env,login_as):
    client,factory,_=env;freeze(factory,1)
    with factory.begin() as session:session.add(m.ConflictLog(schedule_id=1,conflict_type='Test',severity='Hard',description='Unresolved'))
    headers=login_as(client,factory,'approver')
    assert client.post('/schedules/1/publish',headers=headers).status_code==409


def test_stale_candidate_is_rejected_without_reinterpreting_official_history(env,login_as):
    client,factory,_=env;freeze(factory,1,True);candidate=clone_timetable(factory)
    with factory.begin() as s:s.get(m.Room,1).capacity=1
    headers=login_as(client,factory,'approver')
    assert client.post(f'/schedules/{candidate}/publish',headers=headers).status_code==409
    assert client.get('/schedules/1/entries',headers=headers).status_code==200
    with factory() as s:
        assert s.get(m.Schedule,1).status=='Published'
        assert s.get(m.Schedule,candidate).status=='Generated'


def test_competing_publications_remain_atomic(env,login_as):
    from threading import Barrier,Thread
    client,factory,_=env;one=clone_timetable(factory);two=clone_timetable(factory,3)
    headers=login_as(client,factory,'approver');barrier=Barrier(2);responses=[]
    def publish(sid):
        barrier.wait();responses.append(client.post(f'/schedules/{sid}/publish',headers=headers))
    threads=[Thread(target=publish,args=(sid,)) for sid in (one,two)]
    for thread in threads:thread.start()
    for thread in threads:thread.join(15)
    assert len(responses)==2 and all(r.status_code==200 for r in responses)
    with factory() as s:
        assert sorted(s.get(m.Schedule,sid).status for sid in (one,two))==['Archived','Published']
