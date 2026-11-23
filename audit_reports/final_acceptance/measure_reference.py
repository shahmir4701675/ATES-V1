"""Audit-only real HTTP/API measurements and independent reference oracles.

Run after reference_server.py announces readiness. Credentials stay in disposable
storage; headers, tokens, passwords and returned account hashes are never logged.
"""
from pathlib import Path
import concurrent.futures as cf
import csv,io,json,math,os,sqlite3,statistics,threading,time,urllib.request,urllib.error
from independent_oracle import timetable,exams,witness

ROOT=Path(__file__).resolve().parent
ENV=json.loads((ROOT/'reference_environment.json').read_text(encoding='utf-8'))
FOLDER=Path(ENV['folder']);BASE=f"http://127.0.0.1:{ENV['port']}"
PASSWORD=json.loads((FOLDER/'credentials.json').read_text(encoding='utf-8'))['password']
RESULT={'environment':ENV,'measurements':{},'checks':{},'notes':['Local Windows/SQLite instrumented API; no browser interaction or PostgreSQL claims. Times are measured, not inferred from baseline tests.']}


def save():
    (ROOT/'reference_results.json').write_text(json.dumps(RESULT,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def call(path,token=None,method='GET',body=None,content_type=None,timeout=160):
    headers={}
    if token:headers['Authorization']='Bearer '+token
    if isinstance(body,(dict,list)):
        body=json.dumps(body).encode();headers['Content-Type']='application/json'
    elif content_type:headers['Content-Type']=content_type
    req=urllib.request.Request(BASE+path,data=body,headers=headers,method=method)
    start=time.perf_counter()
    try:
        with urllib.request.urlopen(req,timeout=timeout) as response:
            raw=response.read();status=response.status;mime=response.headers.get('Content-Type','')
    except urllib.error.HTTPError as exc:raw=exc.read();status=exc.code;mime=exc.headers.get('Content-Type','')
    seconds=time.perf_counter()-start
    value=json.loads(raw) if 'json' in mime else raw
    return status,value,seconds,mime


def login(username):
    status,value,_,_=call('/auth/login',method='POST',body={'username':username,'password':PASSWORD})
    if status!=200:raise AssertionError(f'Login failed: HTTP {status}')
    return value['access_token']


def dataset():
    connection=sqlite3.connect(FOLDER/'reference.sqlite');connection.row_factory=sqlite3.Row
    tables=['courses','instructors','rooms','batches','time_slots','course_offerings','instructor_availability','exam_slots','enrollments']
    value={t:[dict(r) for r in connection.execute('SELECT * FROM '+t)] for t in tables}
    connection.close();return value


def summary(values):
    values=sorted(values)
    return dict(count=len(values),mean_s=statistics.mean(values),p95_s=values[max(0,math.ceil(.95*len(values))-1)],max_s=max(values))


def wait(sid,token,limit=150):
    end=time.monotonic()+limit
    while time.monotonic()<end:
        status,value,_,_=call(f'/schedules/{sid}/status',token)
        if status!=200:raise AssertionError(f'Status request HTTP {status}')
        if value['status']!='Generating':return value
        time.sleep(.15)
    raise AssertionError('Acceptance observation deadline exceeded')


def export(sid,token,fmt,query=''):
    status,value,seconds,mime=call(f'/schedules/{sid}/export?format={fmt}'+query,token)
    RESULT['measurements'][f'export_{sid}_{fmt}{query}']=dict(http=status,seconds=seconds,bytes=len(value) if isinstance(value,bytes) else 0,content_type=mime,threshold_s=30 if query else 5)
    if status==200:(ROOT/f'reference_{sid}{"_grouped" if query else ""}.{fmt}').write_bytes(value)
    save()


def run():
    coord=login('qa_coordinator');approver=login('qa_approver');admin=login('qa_admin');faculty=login('qa_faculty');student=login('qa_student_0')
    data=dataset();(ROOT/'reference_inputs.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    start=time.perf_counter();proof=witness(data)
    (ROOT/'independent_feasibility_witness.json').write_text(json.dumps(proof),encoding='utf-8')
    RESULT['checks']['independent_feasibility_witness']=dict(timetable_violations=timetable(data,proof['timetable_entries']),exam_violations=exams(data,proof['exam_entries'],proof['exam_room_allocations']),construction_s=time.perf_counter()-start,notes='External first-fit/modular witness only, never used as an application result.')
    save();print('Independent feasibility witness checked.',flush=True)
    schedules={}
    for kind,cid,limit in [('Timetable',1,120),('Exam',2,30)]:
        start=time.perf_counter();status,response,enqueue,_=call('/schedules/generate',coord,'POST',{'term_id':1,'config_id':cid,'schedule_type':kind,'solver_time_limit_s':limit,'random_seed':42})
        if status!=202:raise AssertionError(f'Generation request {kind}: HTTP {status}')
        sid=response['schedule_id'];state=wait(sid,coord,limit+30);elapsed=time.perf_counter()-start
        RESULT['measurements']['generation_'+kind]=dict(seconds=elapsed,enqueue_http_s=enqueue,limit_s=limit,schedule_id=sid,status=state['status'],solver_status=state.get('solver_status'),generation_state=state.get('generation_state'),reported_run_s=state.get('run_seconds'))
        schedules[kind]=sid
        if state['status']=='Generated':
            _,view,_,_=call(f'/schedules/{sid}/entries',coord)
            (ROOT/f'reference_{sid}_entries.json').write_text(json.dumps(view,ensure_ascii=False),encoding='utf-8')
            if kind=='Timetable':violations=timetable(data,view['timetable_entries'])
            else:
                entries=view['exam_entries'];allocations=[dict(a,exam_entry_id=e['exam_entry_id']) for e in entries for a in e['room_allocations']]
                violations=exams(data,entries,allocations)
            RESULT['checks']['oracle_'+kind]=dict(violations=violations,entries=len(view['entries']),independent=True)
            for fmt in ['csv','pdf']:export(sid,coord,fmt)
            if kind=='Timetable':
                export(sid,coord,'pdf','&group_by=batch')
                first=view['timetable_entries'][0]
                start=time.perf_counter();code,adjust,_,_=call(f"/schedules/{sid}/entries/{first['entry_id']}",coord,'PUT',{'is_locked':True,'expected_revision':0});elapsed=time.perf_counter()-start
                RESULT['measurements']['manual_lock_validation']=dict(seconds=elapsed,http=code,threshold_s=1)
                code,locked,_,_=call(f'/schedules/{sid}/entries',coord)
                RESULT['checks']['manual_lock_override']=dict(locked=any(e['entry_id']==first['entry_id'] and e['is_locked'] and e['is_manual_override'] for e in locked['timetable_entries']),violations=timetable(data,locked['timetable_entries']))
                code,_,_,_=call(f'/schedules/{sid}/undo',coord,'POST',{'expected_revision':1})
                _,restored,_,_=call(f'/schedules/{sid}/entries',coord)
                RESULT['checks']['undo']=dict(http=code,original_entries_restored=restored['timetable_entries']==view['timetable_entries'])
            code,_,_,_=call(f'/schedules/{sid}/publish',approver,'POST')
            RESULT['checks']['publish_'+kind]=dict(http=code)
        save();print(kind+' reference run measured.',flush=True)
    sid=schedules['Timetable'];_,state,_,_=call(f'/schedules/{sid}/status',coord)
    if state['status']=='Published':
        RESULT['checks']['role_scope']={}
        for label,token,query in [('student',student,''),('student_other_batch',student,'?batch_id=2'),('faculty',faculty,''),('faculty_other',faculty,'?instructor_id=2'),('admin',admin,'')]:
            code,value,_,_=call(f'/schedules/{sid}/entries'+query,token)
            RESULT['checks']['role_scope'][label]=dict(http=code,batches=sorted({e['batch_id'] for e in value.get('timetable_entries',[])}) if isinstance(value,dict) else [],instructors=sorted({e['instructor_id'] for e in value.get('timetable_entries',[])}) if isinstance(value,dict) else [])
        tokens=[login(f'qa_student_{i}') for i in range(50)]
        def read(i):return call(f'/schedules/{sid}/entries',tokens[i%50])[0:3:2]
        values=[];codes=[]
        for _ in range(4):
            with cf.ThreadPoolExecutor(max_workers=50) as pool:
                for code,elapsed in pool.map(read,range(50)):codes.append(code);values.append(elapsed)
        RESULT['measurements']['api_50_concurrent_users']=dict(**summary(values),http_status_counts={str(c):codes.count(c) for c in set(codes)},threshold_p95_s=2)
        baseline=[]
        for i in range(30):baseline.append(call(f'/schedules/{sid}/entries',tokens[i%50])[2])
        code,new,_,_=call('/schedules/generate',coord,'POST',{'term_id':1,'config_id':1,'solver_time_limit_s':120})
        running=[]
        if code==202:
            for i in range(30):running.append(call(f'/schedules/{sid}/entries',tokens[i%50])[2])
            start=time.perf_counter();cancelcode,cancel,_,_=call(f"/schedules/{new['schedule_id']}/cancel",coord,'POST');cancel_s=time.perf_counter()-start
            terminal=wait(new['schedule_id'],coord,20)
            RESULT['measurements']['cancellation']=dict(http=cancelcode,seconds=cancel_s,state=terminal.get('generation_state'),status=terminal['status'],worker_stopped=terminal.get('worker_stopped'))
            RESULT['measurements']['api_during_generation']=dict(baseline=summary(baseline),during=summary(running),mean_slowdown_percent=(statistics.mean(running)/statistics.mean(baseline)-1)*100,threshold_percent=20,notes='Sequential local API comparison; separate 50-user load result above. Not a distributed production-load guarantee.')
        # Independent exact SQL query measurement, separate from full API latency.
        conn=sqlite3.connect(FOLDER/'reference.sqlite');times=[]
        for _ in range(100):
            t=time.perf_counter();list(conn.execute('SELECT * FROM timetable_entries WHERE schedule_id=?',(sid,)));times.append(time.perf_counter()-t)
        plan=[list(r) for r in conn.execute('EXPLAIN QUERY PLAN SELECT * FROM timetable_entries WHERE schedule_id=?',(sid,))];conn.close()
        RESULT['measurements']['entry_lookup_sql']=dict(**summary(times),threshold_s=.5,plan=plan,notes='Entry lookup query only; complete view timings include authentication/snapshot decoding/serialization.')
        # Freeze original inputs, then change current capacity; official history must retain original meaning.
        _,before,_,_=call(f'/schedules/{sid}/entries',coord);room=before['timetable_entries'][0]['room_id']
        code,_,_,_=call(f'/rooms/{room}',coord,'PUT',{'capacity':1})
        _,historical,_,_=call(f'/schedules/{sid}/entries',coord)
        RESULT['checks']['published_snapshot_after_capacity_edit']=dict(edit_http=code,original_entries_unchanged=historical['timetable_entries']==before['timetable_entries'],violations_against_original_inputs=timetable(data,historical['timetable_entries']),frozen_capacity=next(r['capacity'] for r in historical['context']['rooms'] if r['room_id']==room))
    # Real 5,000-row create/import: separate term-independent courses so it cannot alter existing offering semantics.
    text='course_code,title,department_code,credit_hours,lecture_hours,lab_hours\r\n'+''.join(f'IMPORT{i:04},Imported course {i},QA,1,1,0\r\n' for i in range(5000))
    boundary='AcceptanceBoundary';body=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="reference5000.csv"\r\nContent-Type: text/csv\r\n\r\n'+text+f'\r\n--{boundary}--\r\n').encode()
    start=time.perf_counter();code,report,preview_s,_=call('/import/courses',coord,'POST',body,'multipart/form-data; boundary='+boundary)
    imported=None;confirm_s=None
    if code==200:
        cc,imported,confirm_s,_=call(f"/import/preview/{report['import_id']}/confirm",coord,'POST',{'mode':'valid_only'})
    else:cc=None
    RESULT['measurements']['csv_5000_rows']=dict(preview_http=code,confirm_http=cc,preview_s=preview_s,confirm_s=confirm_s,total_s=time.perf_counter()-start,accepted=report.get('rows_valid') if isinstance(report,dict) else None,rejected=report.get('rows_rejected') if isinstance(report,dict) else None,persisted=imported,threshold_s=15,kind='courses')
    for kind,sid in schedules.items():
        code,_,_,_=call(f'/schedules/{sid}/archive',approver,'POST')
        RESULT['checks']['archive_'+kind]=dict(http=code)
    RESULT['checks']['anonymous_rooms']=dict(http=call('/rooms',method='POST',body={'room_code':'forged','building':'QA','capacity':1,'room_type':'Lecture'})[0])
    # Probe email validation in isolated data only; record accepted incorrect values without modifying code.
    code,value,_,_=call('/instructors',coord,'POST',{'department_id':1,'full_name':'Malformed email probe','email':'not-an-email','max_daily_hours':4,'max_weekly_hours':18})
    RESULT['checks']['malformed_instructor_email']=dict(http=code,accepted=code==201)
    save();print('Reference API/performance/oracle measurements finished.',flush=True)


if __name__=='__main__':
    try:run()
    except Exception as exc:
        RESULT['error']=dict(type=type(exc).__name__,message=str(exc)[:250]);save();raise
