"""Audit-only regression probes. Uses fresh in-memory SQLite; never loads .env."""
from datetime import datetime
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from backend.database import create_db_engine, create_session_factory, init_db
from backend.main import create_app
from backend.seed import seed_database
from backend.models import Schedule, Room, AuditLog, ExamEntry
from backend.adapter import load_term_dataset
from engine.models import load_dataset_from_json, Enrollment
from engine.validator import TimetableValidator, ExamValidator
from engine.exam_scheduler import build_conflict_graph
ROOT = Path(__file__).resolve().parents[1]
@pytest.fixture
def env(test_auth_settings):
    engine=create_db_engine('sqlite:///:memory:')
    init_db(engine)
    factory=create_session_factory(engine)
    seed_database(factory)
    client=TestClient(create_app(engine=engine,session_factory=factory,auth_settings=test_auth_settings),raise_server_exceptions=False)
    yield client,factory
    client.close()
    engine.dispose()

@pytest.fixture
def authorized_env(env, login_as):
    client, factory = env
    client.headers.update(login_as(client, factory))
    return client, factory

def test_unauthenticated_read_requires_login(env):
    c,_=env
    r=c.get('/courses')
    assert r.status_code==401, f'Unauthenticated GET /courses returned {r.status_code}'

def test_unauthenticated_write_requires_login(env):
    c,_=env
    r=c.post('/rooms',json=dict(room_code='AUDIT',building='X',capacity=30,room_type='Lecture'))
    assert r.status_code==401, f'Unauthenticated room creation returned {r.status_code}'

def test_forged_role_is_not_authentication(env):
    c,_=env
    r=c.post('/rooms',headers={'X-User-Role':'Administrator'},json=dict(room_code='FORGED',building='X',capacity=30,room_type='Lecture'))
    assert r.status_code==401, f'Forged Administrator header returned {r.status_code}'

def test_student_cannot_read_generated_schedule(env, login_as):
    c,f=env
    r=c.get('/schedules/1/entries',headers={**login_as(c,f,'cs24a_9002'),'X-User-Role':'Student','X-Batch-Id':'1'})
    assert r.status_code in (401,403,404), f'Student read {r.json().get("status")} schedule with {len(r.json().get("timetable_entries",[]))} entries'

def test_student_list_contains_published_only(env, login_as):
    c,f=env
    r=c.get('/schedules',headers={**login_as(c,f,'cs24a_9002'),'X-User-Role':'Student','X-Batch-Id':'1'})
    assert r.status_code in (401,403) or all(x['status']=='Published' for x in r.json()), str(r.json())[:500]

def test_faculty_without_identity_cannot_edit_any_instructor(env):
    c,_=env
    r=c.put('/instructors/2/availability',headers={'X-User-Role':'Faculty'},json={'slots':[{'slot_id':1,'is_available':False}]})
    assert r.status_code in (401,403), f'Unlinked Faculty edit returned {r.status_code}'

def test_administrator_cannot_generate(env, login_as):
    c,f=env
    with patch('backend.routers.schedules.run_schedule_generation_worker'):
        r=c.post('/schedules/generate',headers={**login_as(c,f,'admin'),'X-User-Role':'Administrator'},json={'term_id':1,'config_id':1})
    assert r.status_code==403, f'Administrator generation returned {r.status_code}'

@pytest.mark.parametrize('method,path,payload',[
 ('post','/auth/login',{'username':'x','password':'12345678'}),
 ('post','/auth/logout',{}),
 ('get','/users',None),
 ('get','/audit',None),
 ('post','/import/courses',{}),
 ('post','/schedules/1/publish',{}),
 ('get','/schedules/1/export?format=csv',None),
 ('get','/schedules/1/export?format=pdf',None),
])
def test_required_endpoint_exists(env,method,path,payload):
    c,_=env
    r=getattr(c,method)(path,**({'json':payload} if payload is not None else {}))
    assert r.status_code not in (404,405), f'{method.upper()} {path}: {r.status_code}'

def test_weekly_slot_overlap_rejected(authorized_env):
    c,_=authorized_env
    r=c.post('/terms/1/slots',json={'day_of_week':1,'slot_index':99,'start_time':'08:30','end_time':'09:30'})
    assert r.status_code in (409,422), f'Overlapping slot accepted: {r.status_code}'

def test_unequal_slot_length_rejected(authorized_env):
    c,_=authorized_env
    r=c.post('/terms/1/slots',json={'day_of_week':7,'slot_index':1,'start_time':'08:00','end_time':'08:30'})
    assert r.status_code in (409,422), f'Unequal length accepted: {r.status_code}'

def test_bad_time_returns_validation_error(authorized_env):
    c,_=authorized_env
    r=c.post('/terms/1/slots',json={'day_of_week':1,'slot_index':99,'start_time':'not-a-time','end_time':'10:00'})
    assert r.status_code==422, f'Malformed time returned {r.status_code}'

def test_grid_over_midnight_returns_validation_error(authorized_env):
    c,_=authorized_env
    r=c.post('/terms/1/slots/generate',json={'working_days':[7],'first_start_time':'23:00','slot_length_min':60,'slots_per_day':2})
    assert r.status_code==422, f'Cross-midnight grid returned {r.status_code}'

def test_invalid_day_returns_validation_error(authorized_env):
    c,_=authorized_env
    r=c.post('/terms/1/slots/generate',json={'working_days':[8],'slots_per_day':1})
    assert r.status_code==422, f'Invalid day returned {r.status_code}'

def test_generated_schedule_immutable_through_master_data(authorized_env):
    c,f=authorized_env
    with f() as s:
        sch=s.get(Schedule,1); sch.status='Published'; sch.approved_by=1; sch.published_at=datetime(2026,11,21); s.commit()
    r=c.put('/rooms/1',json={'capacity':1})
    with f() as s:
        ds=load_term_dataset(s,term_id=1,config_id=1,schedule_id=1)
        violations=TimetableValidator().validate(ds,config_id=1)
    assert r.status_code in (409,422) or not violations, f'Published metadata mutated: HTTP {r.status_code}; violations={sorted(set(v.rule_code for v in violations))}'

def test_lab_contiguity_uses_clock_time():
    ds=load_dataset_from_json(ROOT/'data/seed_timetable.json')
    labs=[e for e in ds.timetable_entries if e.session_type=='Lab']
    off=labs[0].offering_id
    ids=[e.slot_id for e in labs if e.offering_id==off]
    last=max((s for s in ds.time_slots if s.slot_id in ids),key=lambda s:s.slot_index)
    ds.time_slots=[replace(s,start_time='18:00',end_time='19:00') if s.slot_id==last.slot_id else s for s in ds.time_slots]
    violations=TimetableValidator().validate(ds,config_id=1)
    assert any(v.rule_code=='H09' for v in violations), f'Nonadjacent clock-time lab accepted; violations={[v.rule_code for v in violations]}'

def test_mixed_enrollment_fallback_has_cohort_conflict():
    ds=load_dataset_from_json(ROOT/'data/seed_exam.json')
    a=ds.course_offerings[0]
    b=next(o for o in ds.course_offerings if o.batch_id==a.batch_id and o.course_id!=a.course_id)
    ds.course_offerings=[a,b]
    ds.enrollments=[Enrollment(enrollment_id=i+1,offering_id=a.offering_id,student_id=10000+i) for i in range(a.enrolled_count)]
    graph=build_conflict_graph(ds,term_id=a.term_id)
    assert graph.has_edge(a.course_id,b.course_id), 'Fully enumerated course and missing-enrollment course in same batch have no edge'

def test_exam_manual_override_persisted(authorized_env):
    c,f=authorized_env
    r=c.put('/schedules/2/entries/1',json={'is_locked':True})
    assert r.status_code==200, str(r.text)
    assert 'is_manual_override' in r.json(), 'Exam response/model cannot preserve manual override flag'

def test_published_direct_edit_rejected(authorized_env):
    c,f=authorized_env
    with f() as s:
        sch=s.get(Schedule,1); sch.status='Published'; sch.approved_by=1; sch.published_at=datetime(2026,11,21); s.commit()
    r=c.put('/schedules/1/entries/1',json={'is_locked':True})
    assert r.status_code==409

def test_mutation_audit_written(authorized_env):
    c,f=authorized_env
    r=c.post('/rooms',json=dict(room_code='LOGTEST',building='X',capacity=30,room_type='Lecture'))
    assert r.status_code==201
    with f() as s:
        logs=s.scalars(select(AuditLog).where(AuditLog.entity_type=='rooms')).all()
    assert logs, 'Room creation has no persistent audit event'
