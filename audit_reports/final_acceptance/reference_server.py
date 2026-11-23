"""Audit-only instrumented localhost server; all data lives in a new disposable directory.

Heavy imports are inside main so spawn does not re-import the HTTP application.
No production environment database/key is read and no application source is changed.
"""
from pathlib import Path
import json,os,secrets,tempfile,threading,time,sys


def main():
    from datetime import date,time as clock,timedelta
    from sqlalchemy import insert,event
    from backend import models as m
    from backend.database import create_db_engine,create_session_factory,init_db
    from backend.auth import AuthSettings,hash_password
    from backend.main import create_app
    from backend.routers.master_data import DEFAULT_TIMETABLE_CATALOGUE,DEFAULT_EXAM_CATALOGUE
    import uvicorn
    zero_soft='--zero-soft' in sys.argv
    folder=Path(tempfile.mkdtemp(prefix='ates_acceptance_'))
    url='sqlite:///'+(folder/'reference.sqlite').as_posix()
    engine=create_db_engine(url);factory=create_session_factory(engine);init_db(engine)
    password=secrets.token_urlsafe(20);hashed=hash_password(password)
    with factory.begin() as s:
        s.add(m.Department(department_id=1,code='QA',name='Acceptance reference department'))
        s.add(m.AcademicTerm(term_id=1,name='Acceptance reference 2030',start_date=date(2030,9,1),end_date=date(2030,12,31),status='Active'))
    with factory.begin() as s:
        s.execute(insert(m.Course),[dict(course_id=i,course_code=f'C{i:03}',title=f'Acceptance course {i}',department_id=1,credit_hours=3,lecture_hours=1,lab_hours=2 if i%5==0 else 0,is_active=True) for i in range(1,81)])
        s.execute(insert(m.Instructor),[dict(instructor_id=i,department_id=1,full_name=f'Instructor {i}',email=f'i{i}@acceptance.invalid',max_daily_hours=6,max_weekly_hours=24,is_active=True) for i in range(1,41)])
        s.execute(insert(m.Batch),[dict(batch_id=i,department_id=1,program_code=f'QA{i:02}',batch_year=2030,section='A',strength=100,is_active=True) for i in range(1,31)])
        s.execute(insert(m.Room),[dict(room_id=i,room_code=f'R{i:02}',building='QA',capacity=300 if i>40 else 150,room_type='Lecture' if i<=20 else 'Lab' if i<=40 else 'Exam Hall',is_active=True) for i in range(1,61)])
    with factory.begin() as s:
        actors=[dict(user_id=i,username=name,password_hash=hashed,full_name=name,email=f'{name}@acceptance.invalid',role=role,account_status='Active',instructor_id=1 if role=='Faculty' else None,batch_id=None) for i,name,role in [(1,'qa_admin','Administrator'),(2,'qa_coordinator','Coordinator'),(3,'qa_approver','Approver'),(4,'qa_faculty','Faculty')]]
        s.execute(insert(m.User),actors)
        s.execute(insert(m.User),[dict(user_id=1000+i,username=f'qa_student_{i}',password_hash=hashed,full_name=f'Test student {i}',email=f's{i}@acceptance.invalid',role='Student',account_status='Active',batch_id=i//100+1) for i in range(3000)])
    with factory.begin() as s:
        s.execute(insert(m.TimeSlot),[dict(slot_id=(d-1)*8+k,term_id=1,day_of_week=d,slot_index=k,start_time=clock(7+k),end_time=clock(8+k),is_blocked=k==5,block_reason='Lunch' if k==5 else None) for d in range(1,7) for k in range(1,9)])
        s.execute(insert(m.CourseOffering),[dict(offering_id=i,term_id=1,course_id=(i-1)%80+1,batch_id=(i-1)//5+1,instructor_id=(i-1)%40+1,enrolled_count=100) for i in range(1,151)])
        s.execute(insert(m.SchedulingConfig),[dict(config_id=i,term_id=1,schedule_type=kind,name='Reference '+kind,solver_time_limit_s=limit,random_seed=42,created_by=2) for i,kind,limit in [(1,'Timetable',120),(2,'Exam',30)]])
    with factory.begin() as s:
        s.execute(insert(m.InstructorAvailability),[dict(instructor_id=i,slot_id=(i-1)%48+1,is_available=False) for i in range(1,41)])
        enrollments=[dict(offering_id=(i//100)*5+j+1,student_id=1000+i) for i in range(3000) for j in range(5)]
        enrollments += [dict(offering_id=6,student_id=1000+i) for i in range(10)]
        s.execute(insert(m.Enrollment),enrollments)
        s.execute(insert(m.ExamSlot),[dict(exam_slot_id=d*2+k+1,term_id=1,exam_date=date(2030,12,20)+timedelta(days=d),start_time=clock(9 if k==0 else 14),end_time=clock(12 if k==0 else 17),label='Morning' if k==0 else 'Afternoon') for d in range(5) for k in range(2)])
        for cid,catalogue in [(1,DEFAULT_TIMETABLE_CATALOGUE),(2,DEFAULT_EXAM_CATALOGUE)]:
            s.execute(insert(m.ConstraintRule),[dict(config_id=cid,rule_code=c,rule_type=t,is_enabled=True,weight=0 if zero_soft and t=='Soft' else w,param_value=p) for c,t,_,w,p in catalogue])
    (folder/'credentials.json').write_text(json.dumps({'password':password}),encoding='utf-8')
    metadata=dict(folder=str(folder),database_url=url,port=8769,pid=os.getpid(),dataset=dict(offerings=150,rooms=60,weekly_slots=48,courses=80,exam_courses=80,students=3000,instructors=40,batches=30,enrollments=15010,exam_sessions=10),logical_cpus=os.cpu_count(),configuration='All hard enabled; soft weights zero' if zero_soft else 'All hard enabled; default soft weights',notes='Deterministic synthetic reference data; random disposable credentials never logged. SQLite/local loopback; not a production benchmark.')
    root=Path(__file__).resolve().parent
    (root/'reference_environment.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    loglock=threading.Lock();pending=[]
    @event.listens_for(engine,'before_cursor_execute')
    def before(conn,cursor,statement,parameters,context,many):context.qa_started=time.perf_counter()
    @event.listens_for(engine,'after_cursor_execute')
    def after(conn,cursor,statement,parameters,context,many):
        value=dict(ms=(time.perf_counter()-context.qa_started)*1000,operation=statement.split()[0])
        with loglock:pending.append(value)
    app=create_app(engine=engine,session_factory=factory,auth_settings=AuthSettings(secrets.token_urlsafe(48)))
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=8769,log_level='warning',access_log=False))
    def monitor():
        while not (folder/'stop').exists():
            time.sleep(.25)
            with loglock:
                batch=list(pending);pending.clear()
            if batch:
                with (folder/'query_times.jsonl').open('a',encoding='utf-8') as f:f.write(''.join(json.dumps(v)+'\n' for v in batch))
        server.should_exit=True
    threading.Thread(target=monitor,daemon=True).start()
    print('Disposable reference server ready; metadata contains no credentials.',flush=True)
    server.run()
    engine.dispose()


if __name__=='__main__':main()
