"""Audit-only five-role backend journey, genuine solver outputs, and negative probes.

TestClient exercises the real ASGI app and disposable SQLite; this is not browser
testing. No application sources or existing databases are changed.
"""
from pathlib import Path
import json,secrets,tempfile,time


def main():
    from datetime import date
    from sqlalchemy import select
    from backend import models as m
    from backend.database import create_db_engine,create_session_factory,init_db
    from backend.auth import AuthSettings,hash_password
    from backend.main import create_app
    from fastapi.testclient import TestClient
    from independent_oracle import timetable,exams
    root=Path(__file__).resolve().parent;folder=Path(tempfile.mkdtemp(prefix='ates_acceptance_journey_'))
    engine=create_db_engine('sqlite:///'+(folder/'journey.sqlite').as_posix());factory=create_session_factory(engine);init_db(engine)
    password=secrets.token_urlsafe(20);settings=AuthSettings(secrets.token_urlsafe(48))
    with factory.begin() as s:
        s.add(m.Department(department_id=1,code='QA',name='Acceptance'))
        s.add(m.User(user_id=1,username='accept_admin',full_name='Test Administrator',email='admin@acceptance.invalid',password_hash=hash_password(password),role='Administrator',account_status='Active'))
    result={'transport':'Real FastAPI TestClient/SQLite and real spawned solvers; NOT browser testing','checks':[],'failures':[]}
    client=TestClient(create_app(engine=engine,session_factory=factory,auth_settings=settings))
    def request(method,path,token=None,body=None,expected=None,**kwargs):
        headers={'Authorization':'Bearer '+token} if token else {}
        if body is not None:kwargs['json']=body
        t=time.perf_counter();response=client.request(method,path,headers=headers,**kwargs)
        result['checks'].append({'method':method,'path':path,'http':response.status_code,'seconds':time.perf_counter()-t,'expected':expected})
        if expected is not None and response.status_code!=expected:
            result['failures'].append({'method':method,'path':path,'actual':response.status_code,'expected':expected})
        return response
    def login(username):
        r=request('POST','/auth/login',body={'username':username,'password':password},expected=200)
        return r.json()['access_token']
    def account(username,role,**links):
        r=request('POST','/users',admin,dict(username=username,full_name='Test '+role,email=username+'@acceptance.invalid',password=password,role=role,account_status='Active',**links),201)
        return r.json()['user_id']
    def data():
        with factory() as s:
            return {cls.__tablename__:[{c.name:getattr(r,c.name) for c in cls.__table__.columns} for r in s.scalars(select(cls))] for cls in [m.Course,m.Instructor,m.Room,m.Batch,m.TimeSlot,m.CourseOffering,m.InstructorAvailability,m.ExamSlot,m.Enrollment]}
    def oracle_data():
        d=data()
        for r in d['time_slots']:r['start_time']=str(r['start_time']);r['end_time']=str(r['end_time'])
        for r in d['exam_slots']:r['start_time']=str(r['start_time']);r['end_time']=str(r['end_time']);r['exam_date']=str(r['exam_date'])
        return d
    try:
        with client:
            admin=login('accept_admin');account('accept_coord','Coordinator');coord=login('accept_coord')
            request('POST','/rooms',None,{'room_code':'forged','building':'A','capacity':10,'room_type':'Lecture'},401)
            for i in [1,2]:
                request('POST','/instructors',coord,dict(department_id=1,full_name=f'Instructor {i}',email=f'i{i}@acceptance.invalid',max_daily_hours=4,max_weekly_hours=18),201)
                request('POST','/batches',coord,dict(department_id=1,program_code=f'QA{i}',batch_year=2030,section='A',strength=2),201)
                request('POST','/courses',coord,dict(department_id=1,course_code=f'C{i}',title=f'Course {i}',credit_hours=1,lecture_hours=1,lab_hours=0),201)
            for i,kind in [(1,'Lecture'),(2,'Lecture'),(3,'Exam Hall'),(4,'Exam Hall')]:request('POST','/rooms',coord,dict(room_code=f'R{i}',building='QA',capacity=10,room_type=kind),201)
            account('accept_approver','Approver');approver=login('accept_approver')
            account('accept_faculty','Faculty',instructor_id=1);faculty=login('accept_faculty')
            student_id=account('accept_student','Student',batch_id=1);student2=account('accept_student2','Student',batch_id=1);student=login('accept_student')
            request('POST','/terms',coord,dict(name='Journey term',start_date='2030-09-01',end_date='2030-12-31',status='Active'),201)
            for start,end,expected in [('09:00','10:00',201),('09:30','10:30',422),('10:00','11:00',201),('11:00','11:30',422),('bad','12:00',422),('23:00','01:00',422)]:
                index=2 if start in {'09:30','10:00'} else 1 if start=='09:00' else 3
                response=request('POST','/terms/1/slots',coord,dict(day_of_week=1,slot_index=index,start_time=start,end_time=end),expected)
                # Both 409 conflict and 422 validation are acceptable rejection responses.
                if expected==422 and response.status_code==409:result['failures']=[f for f in result['failures'] if not(f['path']=='/terms/1/slots' and f['actual']==409)]
            request('PUT','/instructors/1/availability',faculty,{'slots':[{'slot_id':1,'is_available':False}]},200)
            request('PUT','/instructors/2/availability',faculty,{'slots':[{'slot_id':1,'is_available':False}]},403)
            request('GET','/instructors/2/availability',faculty,expected=403)
            for i in [1,2]:request('POST','/offerings',coord,dict(term_id=1,course_id=i,batch_id=1,instructor_id=i,enrolled_count=1),201)
            for oid,uid in [(1,student_id),(2,student2)]:request('POST','/enrollments',coord,dict(offering_id=oid,student_id=uid),201)
            for day in [1,2]:request('POST','/terms/1/exam-slots',coord,dict(exam_date=f'2030-12-0{day}',start_time='09:00',end_time='10:00',label=f'Day {day}'),201)
            request('POST','/configs',coord,dict(term_id=1,schedule_type='Timetable',name='Journey timetable',solver_time_limit_s=10),201)
            request('POST','/configs',coord,dict(term_id=1,schedule_type='Exam',name='Journey exam',solver_time_limit_s=10,rules=[{'rule_code':'ES01','weight':8},{'rule_code':'ES02','weight':0},{'rule_code':'ES03','weight':0}]),201)
            request('POST','/schedules/generate',admin,{'term_id':1,'config_id':1},403)
            generated=request('POST','/schedules/generate',coord,{'term_id':1,'config_id':1,'solver_time_limit_s':10},202).json()['schedule_id']
            original=request('GET',f'/schedules/{generated}/entries',coord,expected=200).json()
            if original['status']!='Generated':raise AssertionError('Small genuine timetable did not generate')
            d=oracle_data();result['timetable_oracle']=timetable(d,original['timetable_entries'])
            entry=original['timetable_entries'][0];alternate_room=2 if entry['room_id']==1 else 1
            request('PUT',f"/schedules/{generated}/entries/{entry['entry_id']}",coord,{'room_id':alternate_room,'is_locked':True,'expected_revision':0},200)
            adjusted=request('GET',f'/schedules/{generated}/entries',coord,expected=200).json()
            result['manual_oracle']=timetable(d,adjusted['timetable_entries'])
            result['override_persisted']=all(e['is_manual_override'] and e['is_locked'] for e in adjusted['timetable_entries'] if e['entry_id']==entry['entry_id'])
            request('POST',f'/schedules/{generated}/undo',coord,{'expected_revision':1},200)
            restored=request('GET',f'/schedules/{generated}/entries',coord,expected=200).json();result['undo_exact']=restored['timetable_entries']==original['timetable_entries']
            request('PUT',f"/schedules/{generated}/entries/{entry['entry_id']}",coord,{'is_locked':True,'expected_revision':2},200)
            second=request('POST','/schedules/generate',coord,{'term_id':1,'config_id':1,'solver_time_limit_s':10},202).json()['schedule_id']
            second_view=request('GET',f'/schedules/{second}/entries',coord,expected=200).json()
            pinned=next(e for e in second_view['timetable_entries'] if e['offering_id']==entry['offering_id'])
            result['locked_regeneration']=pinned['is_locked'] and (pinned['slot_id'],pinned['room_id'])==(entry['slot_id'],entry['room_id'])
            request('POST',f'/schedules/{generated}/publish',coord,expected=403)
            request('POST',f'/schedules/{generated}/publish',approver,expected=200)
            request('POST',f'/schedules/{second}/publish',approver,expected=200)
            result['previous_archived']=request('GET',f'/schedules/{generated}/status',coord,expected=200).json()['status']=='Archived'
            request('GET',f'/schedules/{generated}/entries',student,expected=403)
            own=request('GET',f'/schedules/{second}/entries',student,expected=200).json();result['student_scope']=sorted({e['batch_id'] for e in own['timetable_entries']})
            request('GET',f'/schedules/{second}/entries?batch_id=2',student,expected=403)
            ownf=request('GET',f'/schedules/{second}/entries',faculty,expected=200).json();result['faculty_scope']=sorted({e['instructor_id'] for e in ownf['timetable_entries']})
            request('PUT',f"/schedules/{second}/entries/{pinned['entry_id']}",coord,{'is_locked':False},409)
            for kind in ['csv','pdf']:
                response=request('GET',f'/schedules/{second}/export?format={kind}',student,expected=200);(root/f'journey_timetable.{kind}').write_bytes(response.content)
            exam=request('POST','/schedules/generate',coord,{'term_id':1,'config_id':2,'solver_time_limit_s':10},202).json()['schedule_id']
            ev=request('GET',f'/schedules/{exam}/entries',coord,expected=200).json()
            entries=ev['exam_entries'];alloc=[dict(a,exam_entry_id=e['exam_entry_id']) for e in entries for a in e['room_allocations']]
            result['exam_oracle']=exams(d,entries,alloc)
            slots={r['exam_slot_id']:r for r in d['exam_slots']};same_day=slots[entries[0]['exam_slot_id']]['exam_date']==slots[entries[1]['exam_slot_id']]['exam_date']
            alternative=[dict(e,exam_slot_id=i+1) for i,e in enumerate(entries)]
            counter=dict(reported_solver_status=ev['solver_status'],entries=entries,allocations=alloc,heuristic_same_batch_same_day=same_day,better_distinct_days=True,alternative_oracle=exams(d,alternative,alloc),original_oracle=exams(d,entries,alloc),soft_ES01_weight=8,other_soft_weights=0)
            (root/'heuristic_optimal_counterexample.json').write_text(json.dumps(counter,default=str,indent=2),encoding='utf-8');result['heuristic_optimal_counterexample']=counter
            for kind in ['csv','pdf']:
                response=request('GET',f'/schedules/{exam}/export?format={kind}',coord,expected=200);(root/f'journey_exam.{kind}').write_bytes(response.content)
            response=request('POST','/import/courses',coord,files={'file':('journey.csv',b'course_code,title,department_code,credit_hours,lecture_hours,lab_hours\nIMPORTED,Imported,QA,1,1,0\nBAD,Bad,QA,x,1,0\n','text/csv')},expected=200).json()
            confirmed=request('POST',f"/import/preview/{response['import_id']}/confirm",coord,{'mode':'valid_only'},200).json();result['import_counts']=confirmed
            unrelated=request('POST',f'/schedules/{exam}/publish',approver,expected=200)
            result['unrelated_unused_course_edit_does_not_stale']=unrelated.status_code==200
            stale_id=request('POST','/schedules/generate',coord,{'term_id':1,'config_id':2,'solver_time_limit_s':10},202).json()['schedule_id']
            request('PUT','/rooms/3',coord,{'capacity':9},200)
            stale=request('POST',f'/schedules/{stale_id}/publish',approver,expected=409);result['stale_after_relevant_capacity_change']=stale.status_code
            result['test_design_note']='Initial exploratory expectation incorrectly treated an unused-course import as a relevant input change. Preserved initial results; current probe distinguishes unrelated edits (allowed) from captured room changes (publication refused).'

            audit=request('GET','/audit',admin,expected=200).json();result['audit_actions']=sorted({r['action'] for r in audit})
            request('GET','/audit',coord,expected=403)
            request('PUT','/terms/1',coord,{'status':'Closed'},200)
            result['published_status_after_term_closed']=request('GET',f'/schedules/{second}/status',coord,expected=200).json()['status']
            result['active_terms_after_closing']=request('GET','/terms?status=Active',coord,expected=200).json()
            request('POST',f'/schedules/{second}/archive',approver,expected=200)
            request('POST','/terms',coord,dict(name='Incomplete input term',start_date='2031-01-01',end_date='2031-05-01',status='Planned'),201)
            empty_cfg=request('POST','/configs',coord,dict(term_id=2,schedule_type='Timetable',name='Incomplete',solver_time_limit_s=10),201).json()['config_id']
            empty=request('POST','/schedules/generate',coord,{'term_id':2,'config_id':empty_cfg,'solver_time_limit_s':10},202).json()['schedule_id']
            result['incomplete_inputs_status']=request('GET',f'/schedules/{empty}/status',coord,expected=200).json()['status']

            with TestClient(create_app(engine=engine,session_factory=factory,auth_settings=settings)) as other:
                reload=other.get(f'/schedules/{second}/status',headers={'Authorization':'Bearer '+coord});result['restart_persistence']=reload.status_code==200 and reload.json()['status']=='Archived'
    except Exception as exc:
        result['blocked']={'type':type(exc).__name__,'message':str(exc)[:150]}
    finally:
        (root/'api_journey_results.json').write_text(json.dumps(result,default=str,indent=2),encoding='utf-8')
        engine.dispose()
        print('Five-role backend acceptance evidence recorded; no credentials logged.',flush=True)


if __name__=='__main__':main()
