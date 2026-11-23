"""B015 actual atomic edits, locked placements and durable undo boundaries."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from backend import models as m
from backend.main import create_app
from tests.test_batch1_generation import batch_template,env
from tests.test_schedule_integrity import freeze


@pytest.mark.parametrize('state',['Draft','Generating','Infeasible','Published','Archived'])
def test_adjustments_and_undo_are_generated_only(env,state):
    client,factory,_=env
    if state in {'Published','Archived'}:freeze(factory,1,True)
    with factory.begin() as s:s.get(m.Schedule,1).status=state
    assert client.put('/schedules/1/entries/1',json={'is_locked':True}).status_code==409
    assert client.post('/schedules/1/undo',json={}).status_code==409


def test_atomic_lab_room_move_lock_and_durable_undo(env,test_auth_settings,login_as):
    client,factory,engine=env
    with factory.begin() as s:s.add(m.Room(room_id=99,room_code='B3-LAB',building='A',capacity=100,room_type='Lab'))
    freeze(factory,1)
    before=client.get('/schedules/1/entries').json()
    labs=[e for e in before['entries'] if e['offering_id']==1 and e['session_type']=='Lab']
    assert len(labs)==2
    eid=labs[0]['entry_id'];oldroom=labs[0]['room_id'];newroom=99
    response=client.put(f'/schedules/1/entries/{eid}',json={'room_id':newroom,'is_locked':True,'expected_revision':0})
    assert response.status_code==200,response.text
    after=client.get('/schedules/1/entries').json();assert after['edit_revision']==1
    moved=[e for e in after['entries'] if e['entry_id'] in {x['entry_id'] for x in labs}]
    assert all(e['room_id']==newroom and e['is_locked'] and e['is_manual_override'] for e in moved)
    assert client.put(f'/schedules/1/entries/{eid}',json={'room_id':oldroom}).status_code==409
    assert client.put(f'/schedules/1/entries/{eid}',json={'is_locked':False,'expected_revision':0}).status_code==409
    with TestClient(create_app(engine=engine,session_factory=factory,auth_settings=test_auth_settings)) as second:
        second.headers.update(login_as(second,factory))
        undo=second.post('/schedules/1/undo',json={'expected_revision':1})
        assert undo.status_code==200,undo.text
        restored=second.get('/schedules/1/entries').json()
        assert restored['entries']==before['entries'] and restored['edit_revision']==2
    with factory() as s:assert s.scalar(select(func.count()).select_from(m.ScheduleEditRevision).where(m.ScheduleEditRevision.schedule_id==1))==3


def test_exam_reassignment_persists_override_and_undo_restores_allocations(env):
    client,factory,_=env;freeze(factory,2)
    before=client.get('/schedules/2/entries').json()
    entry=before['exam_entries'][1];eid=entry['exam_entry_id']
    result=client.put(f'/schedules/2/entries/{eid}',json={'room_allocations':[{'room_id':1,'seats_allocated':entry['student_count']}],'is_locked':True})
    assert result.status_code==200,result.text
    row=client.get('/schedules/2/entries').json()['exam_entries'][1]
    assert row['is_manual_override'] and row['is_locked']
    assert row['room_allocations'][0]['room_id']==1
    with factory() as s:assert s.get(m.ExamEntry,eid).is_manual_override
    assert client.post('/schedules/2/undo',json={}).status_code==200
    assert client.get('/schedules/2/entries').json()['entries']==before['entries']


def test_invalid_lab_or_exam_changes_are_atomic(env):
    client,factory,_=env;freeze(factory,1);freeze(factory,2)
    before=client.get('/schedules/1/entries').json()['entries']
    # A lecture-only room is not a lab, and a one-seat exam assignment is incomplete.
    assert client.put('/schedules/1/entries/4',json={'room_id':1}).status_code==409
    assert client.put('/schedules/2/entries/1',json={'room_allocations':[{'room_id':1,'seats_allocated':1}]}).status_code==409
    assert client.get('/schedules/1/entries').json()['entries']==before
    with factory() as s:assert s.scalar(select(func.count()).select_from(m.ScheduleEditRevision))==0


@pytest.mark.parametrize('username',['admin','approver','fakhra','cs24a_9002'])
def test_adjustment_lock_undo_permissions(env,login_as,username):
    client,factory,_=env;headers=login_as(client,factory,username)
    assert client.put('/schedules/1/entries/1',headers=headers,json={'is_locked':True}).status_code==403
    assert client.post('/schedules/1/undo',headers=headers,json={}).status_code==403


def minimal_lab(factory):
    from sqlalchemy import delete
    with factory.begin() as s:
        s.execute(delete(m.ExamRoomAllocation));s.execute(delete(m.ExamEntry));s.execute(delete(m.Enrollment))
        s.execute(delete(m.TimetableEntry).where((m.TimetableEntry.offering_id!=1)|(m.TimetableEntry.session_type!='Lab')))
        s.execute(delete(m.CourseOffering).where(m.CourseOffering.offering_id!=1))
        course=s.get(m.Course,1);course.lecture_hours=0;course.lab_hours=2


def test_lab_shift_over_its_own_slots_is_atomic_and_locks_survive_real_generation(env):
    client,factory,_=env;minimal_lab(factory);freeze(factory,1)
    first=client.get('/schedules/1/entries').json()['entries'][0]
    response=client.put(f"/schedules/1/entries/{first['entry_id']}",json={'slot_id':9,'is_locked':True})
    assert response.status_code==200,response.text
    assert [e['slot_id'] for e in client.get('/schedules/1/entries').json()['entries']]==[9,10]
    generated=client.post('/schedules/generate',json={'term_id':1,'config_id':1,'solver_time_limit_s':30})
    assert generated.status_code==202
    sid=generated.json()['schedule_id'];view=client.get(f'/schedules/{sid}/entries').json()
    assert view['status']=='Generated' and [e['slot_id'] for e in view['entries']]==[9,10]
    assert all(e['is_locked'] for e in view['entries'])


def test_exam_locks_preserve_exact_seat_allocations_on_regeneration(env):
    client,factory,_=env;freeze(factory,2)
    assert client.put('/schedules/2/entries/1',json={'is_locked':True}).status_code==200
    before=client.get('/schedules/2/entries').json()['exam_entries'][0]
    response=client.post('/schedules/generate',json={'term_id':1,'config_id':2,'solver_time_limit_s':30})
    sid=response.json()['schedule_id']
    after=client.get(f'/schedules/{sid}/entries').json()['exam_entries']
    pinned=next(e for e in after if e['course_id']==before['course_id'])
    assert pinned['is_locked'] and pinned['exam_slot_id']==before['exam_slot_id']
    assert sorted((r['room_id'],r['seats_allocated']) for r in pinned['room_allocations'])==sorted((r['room_id'],r['seats_allocated']) for r in before['room_allocations'])


def test_concurrent_manual_edits_use_revision_preconditions(env):
    from threading import Barrier,Thread
    client,factory,_=env;freeze(factory,1);barrier=Barrier(2);responses=[]
    def edit(eid):
        barrier.wait();responses.append(client.put(f'/schedules/1/entries/{eid}',json={'is_locked':True,'expected_revision':0}))
    threads=[Thread(target=edit,args=(eid,)) for eid in (1,2)]
    for t in threads:t.start()
    for t in threads:t.join(10)
    assert sorted(r.status_code for r in responses)==[200,409]


def test_manual_database_failure_rolls_back_output_history_and_audit(env):
    from unittest.mock import patch
    from sqlalchemy.exc import IntegrityError
    from backend import manual_edits
    client,factory,_=env;freeze(factory,1)
    before=client.get('/schedules/1/entries').json()
    original=manual_edits.write_state
    def fail_after_write(db,schedule,state):
        original(db,schedule,state)
        raise IntegrityError('private SQL',{},Exception('forced disposable failure'))
    with factory() as s:count=s.scalar(select(func.count()).select_from(m.AuditLog))
    with patch('backend.manual_edits.write_state',side_effect=fail_after_write):
        response=client.put('/schedules/1/entries/1',json={'is_locked':True})
    assert response.status_code==409 and 'private SQL' not in response.text
    assert client.get('/schedules/1/entries').json()==before
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(m.ScheduleEditRevision))==0
        assert s.scalar(select(func.count()).select_from(m.AuditLog))==count


def test_untracked_output_changes_block_edit_and_undo(env):
    client,factory,_=env;freeze(factory,1)
    assert client.put('/schedules/1/entries/1',json={'is_locked':True}).status_code==200
    with factory.begin() as s:s.get(m.TimetableEntry,1).is_manual_override=False
    assert client.put('/schedules/1/entries/1',json={'is_locked':False}).status_code==409
    assert client.post('/schedules/1/undo',json={}).status_code==409


@pytest.mark.parametrize('payload',[{'slot_id':0},{'room_id':-1},{'entry_id':2},{'exam_slot_id':'bad'}])
def test_malformed_manual_identity_cannot_be_silently_ignored(env,payload):
    client,_,_=env
    before=client.get('/schedules/1/entries').json()
    assert client.put('/schedules/1/entries/1',json=payload).status_code==422
    assert client.get('/schedules/1/entries').json()==before
