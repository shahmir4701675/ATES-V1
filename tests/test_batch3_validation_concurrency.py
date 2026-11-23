"""B017/B018 malformed domains, active references and real competing requests."""
from threading import Barrier,Thread
from unittest.mock import patch
import pytest
from sqlalchemy import select,func
from backend import models as m
from tests.test_batch1_generation import batch_template,env


@pytest.mark.parametrize('start,end',[('bad','12:00'),('23:00','01:00'),('10:00','10:00'),('24:00','25:00')])
def test_bad_exam_clock_is_422_and_atomic(env,start,end):
    client,factory,_=env
    with factory() as s:before=s.scalar(select(func.count()).select_from(m.ExamSlot))
    response=client.post('/terms/1/exam-slots',json={'exam_date':'2026-12-20','start_time':start,'end_time':end})
    assert response.status_code==422,response.text
    with factory() as s:assert s.scalar(select(func.count()).select_from(m.ExamSlot))==before


@pytest.mark.parametrize('rule',[{'rule_code':'H99'},{'rule_code':'H01','rule_type':'Soft'},{'rule_code':'E02'},{'rule_code':'S03','param_value':0},{'rule_code':'S04','param_value':-1},{'rule_code':'S05','param_value':2},{'rule_code':'S03','param_value':13}])
def test_config_domains_rejected_before_any_mutation(env,rule):
    client,factory,_=env
    response=client.put('/configs/1/rules',json={'rules':[{'rule_code':'S01','weight':8},rule]})
    assert response.status_code==422,response.text
    with factory() as s:assert s.scalar(select(m.ConstraintRule.weight).where(m.ConstraintRule.config_id==1,m.ConstraintRule.rule_code=='S01'))!=8


def test_active_references_and_cross_term_validation(env):
    client,factory,_=env
    assert client.put('/instructors/1',json={'is_active':False}).status_code==200
    assert client.put('/offerings/1',json={'enrolled_count':50}).status_code==422
    assert client.post('/terms/1/slots',json={'term_id':2,'day_of_week':7,'slot_index':1,'start_time':'08:00','end_time':'09:00'}).status_code==422
    with patch('backend.routers.schedules.run_schedule_generation_worker') as worker:
        assert client.post('/schedules/generate',json={'term_id':1,'config_id':2,'schedule_type':'Timetable'}).status_code==422
        worker.assert_not_called()


def test_concurrent_real_exam_generations_allocate_distinct_versions(env):
    client,factory,_=env;barrier=Barrier(2);responses=[]
    def generate():
        barrier.wait()
        responses.append(client.post('/schedules/generate',json={'term_id':1,'config_id':2,'solver_time_limit_s':30}))
    threads=[Thread(target=generate) for _ in range(2)]
    for t in threads:t.start()
    for t in threads:t.join(40)
    assert len(responses)==2 and all(r.status_code==202 for r in responses),[r.text for r in responses]
    ids=[r.json()['schedule_id'] for r in responses]
    assert len(set(ids))==2
    with factory() as s:
        rows=[s.get(m.Schedule,sid) for sid in ids]
        assert sorted(row.version_no for row in rows)==[2,3]
        assert all(row.status=='Generated' and s.get(m.ScheduleSnapshot,row.schedule_id) is not None for row in rows)
        assert s.get(m.Schedule,2).status=='Generated'


def test_controlled_database_lock_error(env):
    from sqlalchemy.exc import OperationalError
    client,_,_=env
    with patch('backend.routers.schedules._next_schedule_version',side_effect=OperationalError('redacted',{},Exception('database is locked'))):
        response=client.post('/schedules/generate',json={'term_id':1,'config_id':1})
    assert response.status_code==409 and 'redacted' not in response.text


def test_oversized_integer_and_invalid_exam_updates_are_atomic(env):
    client,factory,_=env
    assert client.put('/offerings/1',json={'instructor_id':10**100}).status_code==422
    with factory() as s:
        slot=s.get(m.ExamSlot,1);original=(slot.exam_date,slot.start_time,slot.end_time)
    assert client.put('/terms/1/exam-slots/1',json={'start_time':'23:00','end_time':'01:00'}).status_code==422
    assert client.put('/terms/1/exam-slots/1',json={'exam_date':'2000-01-01'}).status_code==422
    with factory() as s:
        slot=s.get(m.ExamSlot,1);assert (slot.exam_date,slot.start_time,slot.end_time)==original


@pytest.mark.parametrize('seed',[-1,2147483648,'bad'])
def test_solver_seed_domain_is_checked_before_queueing(env,seed):
    client,factory,_=env
    with factory() as s:before=s.scalar(select(func.count()).select_from(m.Schedule))
    assert client.put('/configs/1',json={'random_seed':seed}).status_code==422
    with patch('backend.routers.schedules.run_schedule_generation_worker') as worker:
        assert client.post('/schedules/generate',json={'term_id':1,'random_seed':seed}).status_code==422
        worker.assert_not_called()
    with factory() as s:assert s.scalar(select(func.count()).select_from(m.Schedule))==before
