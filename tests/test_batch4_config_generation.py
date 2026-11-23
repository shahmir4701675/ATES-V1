"""Real configuration persistence and process/import regression boundaries."""
import json
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from backend import models as m
from backend.main import create_app
from tests.test_batch1_generation import batch_template,env
from tests.test_schedule_integrity import freeze


def create(client,**changes):
    body=dict(term_id=1,schedule_type='Timetable',name='B4 اردو configuration',solver_time_limit_s=10,random_seed=3)
    body.update(changes)
    response=client.post('/configs',json=body)
    assert response.status_code==201,response.text
    return response.json()


def test_worker_import_does_not_construct_web_app_and_public_exports_remain():
    code="""import sys,json
import backend.generation_execution
assert 'backend.main' not in sys.modules
assert 'backend.routers.exports' not in sys.modules
assert 'backend.seed' not in sys.modules
from backend import create_app
assert callable(create_app)
print(json.dumps({'passed':True}))
"""
    result=subprocess.run([sys.executable,'-B','-c',code],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)=={'passed':True}


def test_delete_is_persistent_cascades_rules_and_audits_real_actor(env,test_auth_settings,login_as):
    client,factory,engine=env;cfg=create(client)
    cid=cfg['config_id'];assert len(cfg['rules'])==16
    assert client.delete(f'/configs/{cid}',headers={'X-User-Id':'3'}).status_code==204
    with TestClient(create_app(engine=engine,session_factory=factory,auth_settings=test_auth_settings)) as second:
        second.headers.update(login_as(second,factory))
        assert second.get(f'/configs/{cid}').status_code==404
        assert cid not in [r['config_id'] for r in second.get('/configs').json()]
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(m.ConstraintRule).where(m.ConstraintRule.config_id==cid))==0
        logs=s.scalars(select(m.AuditLog).where(m.AuditLog.entity_type=='scheduling_configs',m.AuditLog.entity_id==cid,m.AuditLog.action=='DELETE')).all()
        assert len(logs)==1 and logs[0].user_id==1


@pytest.mark.parametrize('username',['admin','approver','fakhra','cs24a_9002'])
def test_config_mutations_are_coordinator_only(env,login_as,username):
    client,factory,_=env;cfg=create(client);headers=login_as(client,factory,username)
    for method,path,body in [('delete',f"/configs/{cfg['config_id']}",None),('put','/configs/1',{'name':'forged'}),('post','/configs',{'term_id':1,'schedule_type':'Timetable','name':'forged'})]:
        options={'headers':headers}
        if body is not None:options['json']=body
        assert getattr(client,method)(path,**options).status_code==403


def test_anonymous_forged_header_does_not_authorize_config_deletion(env):
    client,_,_=env
    client.headers.clear()
    assert client.delete('/configs/1',headers={'X-User-Role':'Coordinator','X-User-Id':'1'}).status_code==401


@pytest.mark.parametrize('state',['Generated','Generating','Published','Archived'])
def test_referenced_config_cannot_be_deleted_at_any_lifecycle_stage(env,state):
    client,factory,_=env
    if state in {'Published','Archived'}:freeze(factory,1,True)
    with factory.begin() as s:s.get(m.Schedule,1).status=state
    assert client.delete('/configs/1').status_code==409
    assert client.get('/configs/1').status_code==200
    with factory() as s:assert s.get(m.Schedule,1).status==state


def test_rule_and_solver_settings_save_atomically_and_clone_is_independent(env):
    client,factory,_=env;cfg=create(client,rules=[{'rule_code':'S01','weight':8}]);cid=cfg['config_id']
    assert len(cfg['rules'])==16 and next(r for r in cfg['rules'] if r['rule_code']=='H01')['is_enabled']
    invalid=client.put(f'/configs/{cid}',json={'random_seed':9,'rules':[{'rule_code':'S01','weight':2},{'rule_code':'H99'}]})
    assert invalid.status_code==422
    assert client.get(f'/configs/{cid}').json()['random_seed']==3
    saved=client.put(f'/configs/{cid}',json={'solver_time_limit_s':30,'random_seed':7,'rules':[{'rule_code':'S01','weight':2}]}).json()
    assert saved['random_seed']==7 and next(r for r in saved['rules'] if r['rule_code']=='S01')['weight']==2
    cloned=create(client,name='Independent clone',rules=saved['rules'],solver_time_limit_s=30,random_seed=7)
    assert client.put(f'/configs/{cid}',json={'rules':[{'rule_code':'S01','weight':9}]}).status_code==200
    assert next(r for r in client.get(f"/configs/{cloned['config_id']}").json()['rules'] if r['rule_code']=='S01')['weight']==2


@pytest.mark.parametrize('kind,rule',[
    ('Timetable',{'rule_code':'H99'}),('Timetable',{'rule_code':'E02'}),
    ('Timetable',{'rule_code':'H01','rule_type':'Soft'}),('Timetable',{'rule_code':'H01','is_enabled':False}),
    ('Timetable',{'rule_code':'S05','rule_type':'Hard'}),('Timetable',{'rule_code':'S03','param_value':13}),
    ('Timetable',{'rule_code':'S04','param_value':-1}),('Exam',{'rule_code':'E02','param_value':6}),
    ('Exam',{'rule_code':'E05','weight':2}),('Timetable',{'rule_code':'S01','param_value':1})])
def test_invalid_catalogue_operations_do_not_persist(env,kind,rule):
    client,factory,_=env
    with factory() as s:before=s.scalar(select(func.count()).select_from(m.SchedulingConfig))
    response=client.post('/configs',json={'term_id':1,'schedule_type':kind,'name':'Invalid','rules':[rule]})
    assert response.status_code==422,response.text
    with factory() as s:assert s.scalar(select(func.count()).select_from(m.SchedulingConfig))==before


def test_generation_preflight_rejects_invalid_stored_rules_before_queuing(env):
    client,factory,_=env
    with factory.begin() as s:
        s.add(m.ConstraintRule(config_id=1,rule_code='H99',rule_type='Hard',is_enabled=True,weight=0))
    assert client.post('/schedules/generate',json={'term_id':1,'config_id':1}).status_code==422
    with factory() as s:assert s.scalar(select(func.count()).select_from(m.GenerationRun))==0


def test_exam_requires_a_session_before_queueing(env):
    from datetime import date
    client,factory,_=env
    with factory.begin() as s:
        term=m.AcademicTerm(name='B4 no sessions',start_date=date(2027,1,1),end_date=date(2027,5,1),status='Planned');s.add(term);s.flush();tid=term.term_id
    cfg=create(client,term_id=tid,schedule_type='Exam')
    assert client.post('/schedules/generate',json={'term_id':tid,'config_id':cfg['config_id']}).status_code==422
    with factory() as s:assert s.scalar(select(func.count()).select_from(m.GenerationRun))==0


def test_config_deletion_and_generation_are_serialized(env):
    from threading import Barrier,Thread
    client,factory,_=env;cfg=create(client,schedule_type='Exam',solver_time_limit_s=30)
    cid=cfg['config_id'];barrier=Barrier(2);responses={}
    def remove():
        barrier.wait();responses['delete']=client.delete(f'/configs/{cid}')
    def generate():
        barrier.wait();responses['generate']=client.post('/schedules/generate',json={'term_id':1,'config_id':cid,'solver_time_limit_s':30})
    threads=[Thread(target=f) for f in [remove,generate]]
    for thread in threads:thread.start()
    for thread in threads:thread.join(45)
    assert all(not t.is_alive() for t in threads)
    pair=(responses['delete'].status_code,responses['generate'].status_code)
    assert pair in {(204,404),(409,202)},[r.text for r in responses.values()]
    with factory() as s:
        if pair==(204,404):
            assert s.get(m.SchedulingConfig,cid) is None
            assert s.scalar(select(func.count()).select_from(m.Schedule).where(m.Schedule.config_id==cid))==0
        else:
            schedule=s.get(m.Schedule,responses['generate'].json()['schedule_id'])
            assert schedule.status=='Generated' and s.get(m.ScheduleSnapshot,schedule.schedule_id) is not None
            assert s.get(m.SchedulingConfig,cid) is not None
