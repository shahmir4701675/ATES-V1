"""B016 real actor attribution, append-only enforcement and new migrations."""
import pytest
from sqlalchemy import select,text,func
from sqlalchemy.exc import IntegrityError
from backend import models as m
from tests.test_batch1_generation import batch_template,env


def test_crud_audit_has_authenticated_actor_and_rolls_back_on_failure(env):
    client,factory,_=env
    response=client.post('/rooms',headers={'X-User-Id':'2'},json={'room_code':'B3-AUDIT','building':'A','capacity':20,'room_type':'Lecture'})
    assert response.status_code==201;rid=response.json()['room_id']
    assert client.put(f'/rooms/{rid}',json={'capacity':25}).status_code==200
    assert client.delete(f'/rooms/{rid}').status_code==200
    with factory() as s:
        logs=s.scalars(select(m.AuditLog).where(m.AuditLog.entity_type=='rooms',m.AuditLog.entity_id==rid)).all()
        assert len(logs)==3 and all(log.user_id==1 for log in logs)
        count=s.scalar(select(func.count()).select_from(m.AuditLog))
    assert client.post('/rooms',json={'room_code':'B3-AUDIT','building':'A','capacity':20,'room_type':'Lecture'}).status_code==409
    with factory() as s:assert s.scalar(select(func.count()).select_from(m.AuditLog))==count


@pytest.mark.parametrize('table,pk',[('audit_logs','log_id'),('import_logs','import_id')])
@pytest.mark.parametrize('operation',['UPDATE','DELETE'])
def test_database_rejects_log_changes(env,table,pk,operation):
    _,factory,_=env
    with factory.begin() as s:
        if table=='import_logs':s.add(m.ImportLog(user_id=1,entity_type='rooms',file_name='empty.csv',rows_total=0,rows_imported=0,rows_rejected=0))
    with pytest.raises(IntegrityError):
        with factory.begin() as s:
            s.execute(text(f'UPDATE {table} SET user_id=2' if operation=='UPDATE' else f'DELETE FROM {table}'))


def test_fk_indexes_cover_srs_missing_indexes(env):
    from sqlalchemy import inspect
    _,_,engine=env;inspector=inspect(engine)
    for table,column in [('schedules','generated_by'),('schedules','approved_by'),('timetable_entries','instructor_id'),('timetable_entries','batch_id'),('timetable_entries','room_id'),('exam_entries','course_id')]:
        assert any(index['column_names'][0]==column for index in inspector.get_indexes(table))


def test_005_upgrade_preserves_existing_rows_on_disposable_database(env):
    from pathlib import Path
    _,factory,engine=env
    # Simulate the prior schema without touching any user database.
    with engine.begin() as c:
        c.exec_driver_sql('DROP TABLE schedule_edit_revisions')
        c.exec_driver_sql('ALTER TABLE exam_entries DROP COLUMN is_manual_override')
    raw=engine.raw_connection()
    try:
        raw.executescript(Path('db/migrations/005_adjustment_integrity.sqlite.sql').read_text(encoding='utf-8'))
        raw.commit()
    finally:raw.close()
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(m.Schedule))==2
        assert s.scalar(select(func.count()).select_from(m.ExamEntry))==5
        assert not any(s.scalars(select(m.ExamEntry.is_manual_override)))
    with pytest.raises(IntegrityError):
        with engine.begin() as c:c.execute(text('DELETE FROM audit_logs'))


def test_allocation_capacity_uses_snapshot_and_rejects_excess(env):
    from tests.test_batch3_adjustments import freeze
    client,factory,_=env;freeze(factory,2)
    assert client.put('/rooms/1',json={'capacity':1}).status_code==200
    count=client.get('/schedules/2/entries').json()['exam_entries'][1]['student_count']
    response=client.put('/schedules/2/entries/2',json={'room_allocations':[{'room_id':1,'seats_allocated':count}]})
    assert response.status_code==200,response.text
    with pytest.raises(IntegrityError):
        with factory.begin() as s:
            s.execute(text('UPDATE exam_room_allocations SET seats_allocated=1000 WHERE exam_entry_id=2'))


def test_sql_exam_overlap_guard_and_append_only_edit_history(env):
    from tests.test_batch3_adjustments import freeze
    client,factory,_=env;freeze(factory,1)
    assert client.put('/schedules/1/entries/1',json={'is_locked':True}).status_code==200
    for sql in ['DELETE FROM schedule_edit_revisions','UPDATE schedule_edit_revisions SET actor_id=2',
                'INSERT INTO exam_slots(term_id,exam_date,start_time,end_time) SELECT term_id,exam_date,start_time,end_time FROM exam_slots LIMIT 1']:
        with pytest.raises(IntegrityError):
            with factory.begin() as s:s.execute(text(sql))


def test_migration_005_failure_rolls_back_additive_schema(env):
    from pathlib import Path
    import sqlite3
    from sqlalchemy import inspect
    _,_,engine=env
    with engine.begin() as c:
        c.exec_driver_sql('DROP TABLE schedule_edit_revisions')
        c.exec_driver_sql('ALTER TABLE exam_entries DROP COLUMN is_manual_override')
    migration=Path('db/migrations/005_adjustment_integrity.sqlite.sql').read_text(encoding='utf-8').replace('COMMIT;','SELECT * FROM deliberately_missing_table;\nCOMMIT;')
    raw=engine.raw_connection()
    try:
        with pytest.raises(sqlite3.OperationalError):raw.executescript(migration)
        raw.rollback()
    finally:raw.close()
    inspector=inspect(engine)
    assert 'schedule_edit_revisions' not in inspector.get_table_names()
    assert 'is_manual_override' not in {c['name'] for c in inspector.get_columns('exam_entries')}
