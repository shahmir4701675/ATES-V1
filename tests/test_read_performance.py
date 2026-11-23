"""Read performance changes must preserve live authorization and immutable context."""
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.pool import StaticPool

from backend import database, schedule_integrity as integrity
from backend.main import create_app
from backend.models import User, AuditLog, Schedule, ScheduleSnapshot, TimetableEntry
from backend.seed import seed_database


@pytest.fixture
def env(tmp_path, test_auth_settings, login_as):
    engine = database.create_db_engine(f"sqlite:///{(tmp_path / 'performance.sqlite').as_posix()}")
    factory = database.create_session_factory(engine)
    seed_database(factory)
    integrity._cached_snapshot.cache_clear()
    with TestClient(create_app(engine=engine, session_factory=factory, auth_settings=test_auth_settings)) as client:
        client.headers.update(login_as(client, factory, 'admin'))
        yield client, factory, engine
    integrity._cached_snapshot.cache_clear()
    engine.dispose()


def test_users_are_filtered_sorted_and_paged_in_database(env):
    client, factory, _ = env
    with factory.begin() as db:
        password_hash = db.get(User, 2).password_hash
        db.add_all(User(username=f'page_user_{i:03}',full_name=f'Paged account {i}',email=f'page{i}@example.invalid',role='Coordinator',account_status='Active',password_hash=password_hash) for i in range(61))
    first = client.get('/users', params=dict(q='page_user_',page=1,page_size=25,sort='username',direction='desc'))
    second = client.get('/users', params=dict(q='page_user_',page=2,page_size=25,sort='username',direction='desc'))
    last = client.get('/users', params=dict(q='page_user_',page=3,page_size=25,sort='username',direction='desc'))
    assert first.headers['X-Total-Count'] == '61'
    assert [len(r.json()) for r in (first,second,last)] == [25,25,11]
    rows = first.json()+second.json()+last.json()
    assert len({r['user_id'] for r in rows}) == 61
    assert rows[0]['username'] == 'page_user_060'
    assert rows[-1]['username'] == 'page_user_000'
    assert all('password_hash' not in r for r in rows)
    # Search treats SQL wildcards as literal characters; identifiers never become SQL.
    assert client.get('/users',params={'q':'%'}).json() == []
    assert client.get('/users',params={'sort':'password_hash'}).status_code == 422


def test_audit_pagination_filters_and_action_catalogue_are_global(env):
    client, factory, _ = env
    with factory.begin() as db:
        db.add_all(AuditLog(user_id=2,action='PAGED_AUDIT',entity_type='qa',details=f'row {i}') for i in range(61))
        db.add(AuditLog(user_id=2,action='OTHER_PAGE_ACTION',entity_type='qa',details='outside current filter'))
    pages = [client.get('/audit',params={'action':'PAGED_AUDIT','page':p,'page_size':25}) for p in (1,2,3)]
    assert [len(r.json()) for r in pages] == [25,25,11]
    assert all(r.headers['X-Total-Count']=='61' for r in pages)
    assert len({r['log_id'] for response in pages for r in response.json()}) == 61
    assert 'OTHER_PAGE_ACTION' in client.get('/audit/actions').json()
    assert client.get('/audit',params={'q':'outside current filter'}).headers['X-Total-Count'] == '1'


def test_transport_gzip_and_cache_headers_do_not_change_data_or_security(env, login_as):
    client, factory, _ = env
    compressed = client.get('/users',headers={'Accept-Encoding':'gzip'})
    plain = client.get('/users',headers={'Accept-Encoding':'identity'})
    assert compressed.headers['Content-Encoding']=='gzip'
    assert int(compressed.headers['Content-Length']) < len(compressed.content)
    assert compressed.json() == plain.json()
    assert 'Content-Encoding' not in plain.headers
    assert 'no-store' in compressed.headers['Cache-Control']
    assert 'Accept-Encoding' in compressed.headers['Vary']
    cors=client.get('/users',headers={'Origin':'http://localhost:3000'})
    assert 'X-Total-Count' in cors.headers['Access-Control-Expose-Headers']
    client.headers.clear()
    assert client.get('/audit/actions',headers={'X-User-Role':'Administrator'}).status_code==401
    faculty=login_as(client,factory,'fakhra')
    assert client.get('/users',headers=faculty).status_code==403
    assert client.get('/audit/actions',headers=faculty).status_code==403


def snapshot_rows(factory):
    with factory.begin() as db:
        integrity.publication_eligibility(db,1)
    with factory() as db:
        return db.get(ScheduleSnapshot,1),db.get(Schedule,1)


def test_verified_snapshot_cache_reuses_work_but_returns_isolated_copies(env, monkeypatch):
    _,factory,_=env
    row,schedule=snapshot_rows(factory)
    original=integrity._decode_snapshot_uncached
    calls=[]
    def counted(*args):
        calls.append(1);return original(*args)
    monkeypatch.setattr(integrity,'_decode_snapshot_uncached',counted)
    with ThreadPoolExecutor(max_workers=8) as pool:
        copies=list(pool.map(lambda _:integrity.decode_snapshot(row,schedule),range(8)))
    assert len(calls)==1
    original_capacity=copies[1].rooms[0].capacity
    copies[0].rooms[0].capacity=1
    assert integrity.decode_snapshot(row,schedule).rooms[0].capacity==original_capacity
    assert copies[1].rooms[0].capacity==original_capacity


@pytest.mark.parametrize('change',['checksum','scope','json','reader'])
def test_warm_cache_does_not_accept_corruption_or_a_different_reader(env,monkeypatch,change):
    _,factory,_=env
    row,schedule=snapshot_rows(factory)
    integrity.decode_snapshot(row,schedule)
    if change=='checksum':row.input_hash='0'*64
    elif change=='scope':schedule.config_id=999
    elif change=='json':row.inputs_json='{corrupt'
    else:
        identity=integrity.implementation_identity()
        identity['engine']['validator.py']='unreviewed-reader'
        monkeypatch.setattr(integrity,'implementation_identity',lambda:identity)
    with pytest.raises(integrity.SnapshotIntegrityError):integrity.decode_snapshot(row,schedule)


def test_warm_snapshot_cache_never_skips_live_output_validation(env):
    _,factory,_=env
    with factory.begin() as db:integrity.publication_eligibility(db,1)
    with factory() as db:
        integrity.hydrate_snapshot(db,db.get(ScheduleSnapshot,1),db.get(Schedule,1))
    # Generated entries are editable, so corrupt one in the disposable fixture.
    with factory.begin() as db:
        row=db.scalar(select(TimetableEntry).where(TimetableEntry.schedule_id==1))
        row.session_type='Lab' if row.session_type=='Lecture' else 'Lecture'
    with factory() as db:
        with pytest.raises(integrity.SnapshotIntegrityError):
            integrity.hydrate_snapshot(db,db.get(ScheduleSnapshot,1),db.get(Schedule,1))


def test_warm_read_cache_does_not_bypass_account_deactivation(env,login_as):
    client,factory,_=env
    assert client.get('/users').status_code==200
    with factory.begin() as db:db.get(User,2).account_status='Deactivated'
    assert client.get('/users').status_code==403


def test_postgresql_pool_options_are_bounded_without_connecting(monkeypatch):
    monkeypatch.setattr(database,'create_engine',lambda url,**kw:SimpleNamespace(options=kw))
    monkeypatch.setenv('ATES_DB_POOL_SIZE','7')
    engine=database.create_db_engine('postgresql://localhost/disposable_not_connected')
    assert engine.options['pool_size']==7
    assert engine.options['pool_pre_ping'] is True
    monkeypatch.setenv('ATES_DB_POOL_SIZE','0')
    with pytest.raises(ValueError,match='ATES_DB_POOL_SIZE'):database.create_db_engine('postgresql://localhost/disposable_not_connected')


def test_sqlite_memory_pool_is_unchanged(monkeypatch):
    monkeypatch.setenv('ATES_DB_POOL_SIZE','not-used-for-sqlite')
    engine=database.create_db_engine('sqlite:///:memory:')
    assert isinstance(engine.pool,StaticPool)
    engine.dispose()


def test_006_migration_is_additive_repeatable_and_used_by_query_planner(tmp_path):
    path=tmp_path/'indexes.sqlite'
    db=sqlite3.connect(path)
    db.execute('CREATE TABLE audit_logs(log_id INTEGER PRIMARY KEY,user_id INTEGER,created_at TIMESTAMP,action TEXT)')
    db.execute("INSERT INTO audit_logs VALUES(1,2,'2030-01-01','LOGIN')");db.commit()
    script=(Path(__file__).parents[1]/'db/migrations/006_read_performance.sqlite.sql').read_text()
    db.executescript(script);db.executescript(script)
    assert db.execute('SELECT COUNT(*) FROM audit_logs').fetchone()[0]==1
    for column,value,index in [('action','LOGIN','action'),('user_id',2,'user')]:
        plan=str(db.execute(f'EXPLAIN QUERY PLAN SELECT * FROM audit_logs WHERE {column}=? ORDER BY created_at DESC, log_id DESC',(value,)).fetchall())
        assert f'idx_audit_logs_{index}_time_id' in plan
    db.close()
