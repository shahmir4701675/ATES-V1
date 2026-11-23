from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.database import create_db_engine,create_session_factory,init_db
from backend.seed import seed_database
from backend.main import create_app
from backend.models import Schedule
from engine.models import load_dataset_from_json
from engine.timetable_solver import solve_timetable
ROOT=Path(__file__).resolve().parents[1]

def test_solver_rejects_overlapping_clock_slots():
 ds=load_dataset_from_json(ROOT/'data/seed_timetable.json')
 off=ds.course_offerings[0]
 ds.course_offerings=[off]
 ds.courses=[replace(c,lecture_hours=2,lab_hours=0) for c in ds.courses if c.course_id==off.course_id]
 ds.time_slots=[replace(s,day_of_week=1,slot_index=i+1,start_time='08:00',end_time='09:00',is_blocked=False) for i,s in enumerate(ds.time_slots[:2])]
 ds.instructor_availability=[]
 ds.timetable_entries=[]
 ds.constraint_rules=[replace(r,is_enabled=False) if r.rule_type=='Soft' else r for r in ds.constraint_rules]
 result=solve_timetable(ds,time_limit_s=10,config_id=1)
 assert not result.is_feasible, f'Solver returned {result.solver_status}: {[(e.slot_id,e.instructor_id,e.batch_id,e.room_id) for e in result.schedule]} in identical clock windows; validator={result.violations}'

def test_default_app_recovers_orphan_on_startup(test_auth_settings, login_as):
 e=create_db_engine('sqlite:///:memory:'); init_db(e); f=create_session_factory(e); seed_database(f)
 with f() as s:
  s.get(Schedule,1).status='Generating'; s.commit()
 app=create_app(auth_settings=test_auth_settings)
 with patch('backend.dependencies.create_db_engine',return_value=e):
  with TestClient(app) as c:
   c.headers.update(login_as(c,f))
   r=c.get('/schedules/1/status')
 assert r.json()['status']=='Infeasible', f'Default lazy app left status={r.json()["status"]}'
 e.dispose()
