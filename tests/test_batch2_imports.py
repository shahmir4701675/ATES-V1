"""B009: six real imports, staged ownership, revalidation and atomic rollback."""
import csv,io
from fastapi.testclient import TestClient
from sqlalchemy import select,func
import pytest
from backend import models as m
from backend.main import create_app
from tests.test_batch1_generation import batch_template,env


def sample(factory,kind):
    with factory() as s:
        dept=s.get(m.Department,1).code
        basic={'courses':dict(course_code='NEW900',title='Réseaux, avancés',department_code=dept,credit_hours=3,lecture_hours=3,lab_hours=0),
               'instructors':dict(full_name='Import Faculty',email='import@example.test',department_code=dept,max_daily_hours=4,max_weekly_hours=16),
               'rooms':dict(room_code='IMPORT-ROOM',building='Block A',capacity=55,room_type='Lecture'),
               'batches':dict(program_code='NEW',batch_year=2026,section='C',strength=50,department_code=dept)}
        if kind in basic:return basic[kind]
        offers=s.scalars(select(m.CourseOffering)).all();batches=s.scalars(select(m.Batch)).all()
        term=s.get(m.AcademicTerm,1).name
        if kind=='offerings':
            course,batch=next((c,b) for c in s.scalars(select(m.Course)) for b in batches if not any(o.course_id==c.course_id and o.batch_id==b.batch_id for o in offers))
            instructor=s.get(m.Instructor,1)
            return dict(term_name=term,course_code=course.course_code,program_code=batch.program_code,batch_year=batch.batch_year,section=batch.section,instructor_email=instructor.email,enrolled_count=30)
        enroll={(e.offering_id,e.student_id) for e in s.scalars(select(m.Enrollment))}
        off,student=next((o,u) for o in offers for u in s.scalars(select(m.User).where(m.User.role=='Student')) if (o.offering_id,u.user_id) not in enroll)
        batch=s.get(m.Batch,off.batch_id)
        return dict(term_name=term,course_code=s.get(m.Course,off.course_id).course_code,program_code=batch.program_code,batch_year=batch.batch_year,section=batch.section,student_username=student.username)


def encode(rows):
    stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return stream.getvalue().encode('utf-8')


def upload(client,kind,content):return client.post(f'/import/{kind}',files={'file':('data.csv',content,'text/csv')})


@pytest.mark.parametrize('kind,model',[('courses',m.Course),('instructors',m.Instructor),('rooms',m.Room),('batches',m.Batch),('offerings',m.CourseOffering),('enrollments',m.Enrollment)])
def test_every_import_type_stages_validates_and_persists_accurate_counts(env,kind,model):
    client,factory,_=env;row=sample(factory,kind);bad={**row,next(iter(row)):''}
    with factory() as s:before=s.scalar(select(func.count()).select_from(model))
    preview=upload(client,kind,encode([row,bad]));assert preview.status_code==200,preview.text
    report=preview.json();assert report['rows_total']==2 and report['rows_valid']==1
    assert report['rejected'] and report['rejected'][0]['line']==3
    with factory() as s:assert s.scalar(select(func.count()).select_from(model))==before
    result=client.post(f"/import/preview/{report['import_id']}/confirm",json={'mode':'valid_only'})
    assert result.status_code==200,result.text
    assert result.json()=={'rows_imported':1,'rows_rejected':1}
    assert client.post(f"/import/preview/{report['import_id']}/confirm",json={'mode':'valid_only'}).json()==result.json()
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(model))==before+1
        if kind=='courses':assert s.scalar(select(m.Course.title).where(m.Course.course_code=='NEW900'))=='Réseaux, avancés'
        log=s.scalar(select(m.ImportLog).order_by(m.ImportLog.import_id.desc()))
        assert (log.rows_total,log.rows_imported,log.rows_rejected)==(2,1,1)
        assert s.scalar(select(m.AuditLog).where(m.AuditLog.action=='IMPORT',m.AuditLog.entity_id==log.import_id)) is not None


@pytest.mark.parametrize('content',[b'room_code,room_code\nA,B\n',b'wrong\nx\n',b'\xff',b'room_code,building,capacity,room_type\n"broken'])
def test_malformed_csv_rejected_before_staging(env,content):
    client,_,_=env;assert upload(client,'rooms',content).status_code==422


def test_size_extension_and_utf8_validation(env):
    client,_,_=env
    assert upload(client,'rooms',b'x'*(10*1024*1024+1)).status_code==413
    assert client.post('/import/rooms',files={'file':('data.exe',b'x','text/csv')}).status_code==422


def test_duplicate_rows_and_missing_foreign_keys_are_reported(env):
    client,factory,_=env;row=sample(factory,'courses')
    report=upload(client,'courses',encode([row,row,{**row,'course_code':'BAD900','department_code':'MISSING'}])).json()
    assert report['rows_valid']==1
    assert {r['line'] for r in report['rejected']}=={3,4}
    assert all(r['column'] and r['reason'] for r in report['rejected'])


def test_stale_preview_and_database_failure_roll_back_every_row(env):
    client,factory,engine=env;row=sample(factory,'rooms')
    report=upload(client,'rooms',encode([row])).json()
    assert client.post('/rooms',json=row).status_code==201
    assert client.post(f"/import/preview/{report['import_id']}/confirm",json={'mode':'valid_only'}).status_code==409
    course=sample(factory,'courses');report=upload(client,'courses',encode([course,{**course,'course_code':'FAIL900'}])).json()
    with engine.begin() as conn:conn.exec_driver_sql("CREATE TRIGGER reject_import BEFORE INSERT ON courses WHEN NEW.course_code='FAIL900' BEGIN SELECT RAISE(ABORT,'test rollback'); END")
    assert client.post(f"/import/preview/{report['import_id']}/confirm",json={'mode':'valid_only'}).status_code==409
    with factory() as s:
        assert s.scalar(select(m.Course).where(m.Course.course_code=='NEW900')) is None
        assert s.get(m.ImportStage,report['import_id']).state=='Preview'


def test_preview_survives_restart_and_cancel_writes_no_master_rows(env,login_as,test_auth_settings):
    client,factory,engine=env;row=sample(factory,'rooms');report=upload(client,'rooms',encode([row])).json()
    with TestClient(create_app(engine=engine,session_factory=factory,auth_settings=test_auth_settings)) as second:
        second.headers.update(login_as(second,factory))
        assert second.get(f"/import/preview/{report['import_id']}").json()==report
        assert second.post(f"/import/preview/{report['import_id']}/confirm",json={'mode':'cancel'}).json()['rows_imported']==0
    with factory() as s:assert s.scalar(select(m.Room).where(m.Room.room_code==row['room_code'])) is None


@pytest.mark.parametrize('username',['admin','approver','fakhra','cs24a_9002'])
def test_imports_are_coordinator_only(env,login_as,username):
    client,factory,_=env;headers=login_as(client,factory,username)
    assert client.post('/import/courses',headers=headers,files={'file':('data.csv',b'x','text/csv')}).status_code==403
    assert client.get('/import/courses/template',headers=headers).status_code==403


@pytest.mark.parametrize('kind',['courses','instructors','rooms','batches','offerings','enrollments'])
def test_downloadable_templates_match_supported_headers(env,kind):
    client,_,_=env;response=client.get(f'/import/{kind}/template')
    assert response.status_code==200 and 'text/csv' in response.headers['content-type']
    assert '.csv' in response.headers['content-disposition']
    assert next(csv.reader(io.StringIO(response.text)))


def test_preview_owner_expiry_and_stream_limit(env,login_as,test_password_hash):
    from backend.auth import utc_now
    from datetime import timedelta
    client,factory,_=env;report=upload(client,'rooms',encode([sample(factory,'rooms')])).json();stage=report['import_id']
    with factory.begin() as s:s.add(m.User(user_id=999,username='second-coordinator',full_name='Second',email='second@example.test',role='Coordinator',password_hash=test_password_hash))
    other=login_as(client,factory,'second-coordinator')
    assert client.get(f'/import/preview/{stage}',headers=other).status_code==403
    assert client.post(f'/import/preview/{stage}/confirm',headers=other,json={'mode':'valid_only'}).status_code==403
    with factory.begin() as s:s.get(m.ImportStage,stage).expires_at=utc_now()-timedelta(seconds=1)
    assert client.post(f'/import/preview/{stage}/confirm',json={'mode':'valid_only'}).status_code==409
    assert upload(client,'rooms',b'x'*(10*1024*1024+70000)).status_code==413


def test_multiline_csv_reports_physical_line_numbers(env):
    client,factory,_=env;row=sample(factory,'courses');row['title']='A multiline\ntitle'
    report=upload(client,'courses',encode([row,{**row,'course_code':''}])).json()
    assert report['rows_valid']==1
    assert report['rejected'][0]['line']==4


def test_empty_data_records_are_rejected_and_counted(env):
    client,factory,_=env;row={key:'' for key in sample(factory,'rooms')}
    report=upload(client,'rooms',encode([row])).json()
    assert report['rows_total']==1 and report['rows_valid']==0 and report['rows_rejected']==1
    assert {error['line'] for error in report['rejected']}=={2}


def test_sqlite_stage_migration_is_additive_and_repeatable(env):
    from pathlib import Path
    client,factory,engine=env
    with engine.begin() as conn:conn.exec_driver_sql('DROP TABLE import_stages')
    raw=engine.raw_connection()
    try:
        sql=(Path(__file__).resolve().parents[1]/'db/migrations/004_import_staging.sqlite.sql').read_text()
        raw.driver_connection.executescript(sql);raw.driver_connection.executescript(sql)
    finally:raw.close()
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(m.Schedule))==2
        assert s.scalar(select(func.count()).select_from(m.Course))==5
    assert upload(client,'rooms',encode([sample(factory,'rooms')])).status_code==200
