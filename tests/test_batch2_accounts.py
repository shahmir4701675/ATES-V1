"""B011 real account lifecycle and read-only authoritative audit regressions."""
from sqlalchemy import select
import pytest
from backend import models as m
from backend.auth import verify_password
from tests.test_batch1_generation import batch_template, env


@pytest.mark.parametrize("username",["coordinator","approver","fakhra","cs24a_9002"])
def test_account_administration_is_admin_only(env,login_as,username):
    client,factory,_=env;headers=login_as(client,factory,username)
    for method,path,body in [("GET","/users",None),("GET","/audit",None),("POST","/users",{}),("PUT","/users/1",{}),("POST","/users/1/password",{})]:
        assert client.request(method,path,headers=headers,json=body).status_code==403


def test_real_account_create_update_reset_and_deactivate(env,login_as,test_password):
    client,factory,_=env;admin=login_as(client,factory,"admin")
    payload=dict(username="new_user",full_name="New User",email="new@example.test",role="Student",batch_id=1,password=test_password)
    response=client.post("/users",headers=admin,json=payload)
    assert response.status_code==201,response.text
    user=response.json();uid=user['user_id'];assert 'password_hash' not in user and 'password' not in user
    with factory() as session: assert verify_password(test_password,session.get(m.User,uid).password_hash)
    token=client.post('/auth/login',json=dict(username='new_user',password=test_password)).json()['access_token']
    assert client.put(f'/users/{uid}',headers=admin,json={'account_status':'Deactivated'}).status_code==200
    assert client.get('/auth/me',headers={'Authorization':'Bearer '+token}).status_code in (401,403)
    assert client.post('/auth/login',json=dict(username='new_user',password=test_password)).status_code==401
    assert client.put(f'/users/{uid}',headers=admin,json={'account_status':'Active'}).status_code==200
    new_password=test_password+'x'
    assert client.post(f'/users/{uid}/password',headers=admin,json={'password':new_password}).status_code==204
    assert client.post('/auth/login',json=dict(username='new_user',password=test_password)).status_code==401
    assert client.post('/auth/login',json=dict(username='new_user',password=new_password)).status_code==200
    assert client.delete(f'/users/{uid}',headers=admin).status_code in (405,404)
    logs=client.get('/audit',headers=admin,params={'user_id':2,'action':'RESET_PASSWORD'}).json()
    assert any(row['entity_id']==uid for row in logs)
    assert new_password not in str(logs)


@pytest.mark.parametrize('change',[{'role':'Faculty','instructor_id':None},{'role':'Student','batch_id':None},{'role':'Faculty','instructor_id':9999},{'role':'Student','batch_id':9999},{'role':'Unknown'},{'password':'short'},{'password':'é'*37},{'password_hash':'forged'}])
def test_invalid_account_changes_are_rejected_without_mutation(env,login_as,change):
    client,factory,_=env;admin=login_as(client,factory,'admin')
    response=client.put('/users/1',headers=admin,json=change)
    assert response.status_code in (422,409),response.text
    with factory() as session: assert session.get(m.User,1).role=='Coordinator'


def test_self_password_change_checks_current_password_and_revokes_all_sessions(env,login_as,test_password):
    client,factory,_=env;headers=login_as(client,factory)
    assert client.post('/auth/password',headers=headers,json={'current_password':'wrong-password','new_password':test_password+'x'}).status_code==403
    assert client.post('/auth/password',headers=headers,json={'current_password':test_password,'new_password':test_password+'x'}).status_code==204
    assert client.get('/auth/me',headers=headers).status_code==401
    assert client.post('/auth/login',json={'username':'coordinator','password':test_password+'x'}).status_code==200


def test_duplicate_accounts_and_last_admin_guard(env,login_as,test_password):
    client,factory,_=env;admin=login_as(client,factory,'admin')
    body=dict(username='admin',full_name='Duplicate',email='unique@example.test',role='Coordinator',password=test_password)
    assert client.post('/users',headers=admin,json=body).status_code==409
    assert client.put('/users/2',headers=admin,json={'account_status':'Deactivated'}).status_code==409


def test_audit_filtering_and_no_mutation_routes(env,login_as):
    client,factory,_=env;admin=login_as(client,factory,'admin')
    response=client.get('/audit',headers=admin,params={'action':'LOGIN','from':'2000-01-01','to':'2100-01-01'})
    assert response.status_code==200
    assert response.json() and all(row['action']=='LOGIN' for row in response.json())
    for method in ('PUT','DELETE'):
        assert client.request(method,'/audit/1',headers=admin,json={}).status_code in (404,405)
    assert client.get('/audit',headers=admin,params={'from':'2026-02-02','to':'2026-01-01'}).status_code==422


def test_anonymous_and_forged_account_administration(env):
    client,_,_=env;client.headers.clear()
    for path in ('/users','/audit'):
        assert client.get(path,headers={'X-User-Role':'Administrator','X-User-Id':'2'}).status_code==401
    assert client.post('/auth/password',headers={'X-User-Id':'1'},json={'current_password':'ignored','new_password':'ignored'}).status_code==401
