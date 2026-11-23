"""B006/B007 server-side visibility and ownership, with real frozen schedules."""
import pytest
from backend import models as m
from tests.test_batch1_generation import batch_template, env
from tests.test_schedule_integrity import freeze


@pytest.mark.parametrize('username',['cs24a_9002','fakhra','admin'])
@pytest.mark.parametrize('status',['Draft','Generated','Infeasible','Archived'])
def test_non_review_roles_cannot_read_unpublished_versions(env,login_as,username,status):
    client,factory,_=env
    if status=='Archived':
        freeze(factory,1,True)
    with factory.begin() as session:session.get(m.Schedule,1).status=status
    headers=login_as(client,factory,username)
    listed=client.get('/schedules',headers=headers).json()
    assert not any(row['schedule_id']==1 for row in listed)
    for suffix in ('','/status','/entries','/conflicts'):
        assert client.get('/schedules/1'+suffix,headers=headers).status_code==403


@pytest.mark.parametrize('sid',[1,2])
@pytest.mark.parametrize('username,scope,expected',[('cs24a_9002','batch_id',1),('fakhra','instructor_id',1)])
def test_published_entries_and_counts_use_trusted_scope(env,login_as,sid,username,scope,expected):
    client,factory,_=env;freeze(factory,sid,True)
    headers=login_as(client,factory,username)
    response=client.get(f'/schedules/{sid}/entries',headers={**headers,'X-Batch-Id':'2','X-Instructor-Id':'2'})
    assert response.status_code==200,response.text
    view=response.json()
    if sid==1:
        assert view['entries'] and all(row[scope]==expected for row in view['entries'])
    else:
        offers=view['context']['course_offerings']
        assert offers and all(row[scope]==expected for row in offers)
        assert all(any(o['course_id']==entry['course_id'] for o in offers) for entry in view['entries'])
    metadata=client.get(f'/schedules/{sid}',headers=headers).json()
    assert metadata['entry_count']==len(view['entries'])
    assert client.get(f'/schedules/{sid}/entries',headers=headers,params={scope:2}).status_code==403


@pytest.mark.parametrize('username',['coordinator','approver'])
def test_review_roles_can_read_generated_history(env,login_as,username):
    client,factory,_=env;headers=login_as(client,factory,username)
    assert len(client.get('/schedules',headers=headers).json())==2
    assert client.get('/schedules/1/entries',headers=headers).status_code==200


def test_faculty_availability_ownership_applies_to_get_and_put(env,login_as):
    client,factory,_=env;headers=login_as(client,factory,'fakhra')
    for method,body in [('GET',None),('PUT',{'slots':[]})]:
        assert client.request(method,'/instructors/1/availability',headers=headers,json=body).status_code==200
        assert client.request(method,'/instructors/2/availability',headers={**headers,'X-Instructor-Id':'2'},json=body).status_code==403
    coordinator=login_as(client,factory)
    assert client.get('/instructors/2/availability',headers=coordinator).status_code==200


@pytest.mark.parametrize('username,column',[('fakhra','instructor_id'),('cs24a_9002','batch_id')])
def test_accounts_missing_trusted_links_are_rejected(env,login_as,username,column):
    client,factory,engine=env;headers=login_as(client,factory,username)
    # Deliberately simulate corrupt legacy storage, never relax application guards.
    with engine.begin() as conn:
        conn.exec_driver_sql('PRAGMA ignore_check_constraints=ON')
        conn.exec_driver_sql(f'UPDATE users SET {column}=NULL WHERE username=?',(username,))
        conn.exec_driver_sql('PRAGMA ignore_check_constraints=OFF')
    assert client.get('/schedules',headers=headers).status_code==403
    assert client.get('/instructors/1/availability',headers=headers).status_code==403


@pytest.mark.parametrize('username',['fakhra','cs24a_9002'])
def test_published_schedules_with_no_permitted_identity_are_not_listed(env,login_as,username):
    from sqlalchemy import select
    client,factory,_=env;freeze(factory,1,True);freeze(factory,2,True)
    headers=login_as(client,factory,username)
    with factory.begin() as s:
        user=s.scalar(select(m.User).where(m.User.username==username))
        if user.role=='Faculty':
            s.add(m.Instructor(instructor_id=999,department_id=1,full_name='Unassigned',email='unused@example.test'))
            s.flush();user.instructor_id=999
        else:
            s.add(m.Batch(batch_id=999,department_id=1,program_code='OTHER',batch_year=2026,section='Z',strength=20))
            s.flush();user.batch_id=999
    assert client.get('/schedules',headers=headers).json()==[]
    for sid in (1,2):
        assert client.get(f'/schedules/{sid}/entries',headers=headers).status_code==403
        assert client.get(f'/schedules/{sid}/export?format=csv',headers=headers).status_code==403
