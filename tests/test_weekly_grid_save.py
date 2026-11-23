"""Frontend weekly-grid save contract; disposable databases and real authentication."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from backend.database import create_db_engine, create_session_factory
from backend.main import create_app
from backend.models import Schedule, ScheduleSnapshot, TimeSlot, InstructorAvailability
from backend.schedule_integrity import publication_eligibility
from backend.seed import seed_database


GRID = dict(working_days=[1, 2, 3, 4, 5], first_start_time="08:00",
            slot_length_min=60, slots_per_day=6)


@pytest.fixture
def env(tmp_path, test_auth_settings, login_as):
    engine = create_db_engine(f"sqlite:///{(tmp_path / 'grid.sqlite').as_posix()}")
    factory = create_session_factory(engine)
    seed_database(factory)
    with TestClient(create_app(engine=engine, session_factory=factory, auth_settings=test_auth_settings)) as client:
        client.headers.update(login_as(client, factory))
        yield client, factory
    engine.dispose()


def test_create_grid_then_save_twice_keeps_exactly_thirty_ids(env):
    client, _ = env
    term = client.post('/terms', json=dict(name='New grid', start_date='2030-01-01', end_date='2030-06-01')).json()['term_id']
    url = f'/terms/{term}/slots/generate'
    first = client.put(url, json=GRID)
    assert first.status_code == 200, first.text
    original = first.json()
    assert len(original) == 30
    for _ in range(2):
        response = client.put(url, json=GRID)
        assert response.status_code == 200, response.text
        assert response.json() == original
    assert client.get(f'/terms/{term}/slots').json() == original


def test_save_existing_grid_is_noop_and_preserves_blocks_and_availability(env):
    client, factory = env
    original = client.get('/terms/1/slots').json()
    with factory() as db:
        availability = [(r.instructor_id, r.slot_id, r.is_available) for r in db.scalars(select(InstructorAvailability))]
    response = client.put('/terms/1/slots/generate', json=GRID)
    assert response.status_code == 200, response.text
    assert response.json() == original
    assert len(original) == 30
    with factory() as db:
        assert [(r.instructor_id, r.slot_id, r.is_available) for r in db.scalars(select(InstructorAvailability))] == availability


def test_edit_whole_grid_atomically_updates_same_ids_and_resaves(env):
    client, _ = env
    original = client.get('/terms/1/slots').json()
    payload = GRID | {'first_start_time': '09:00'}
    response = client.put('/terms/1/slots/generate', json=payload)
    assert response.status_code == 200, response.text
    edited = response.json()
    assert [s['slot_id'] for s in edited] == [s['slot_id'] for s in original]
    assert len(edited) == 30
    for slot in edited:
        assert slot['start_time'] == f"{8 + slot['slot_index']:02}:00"
        assert slot['end_time'] == f"{9 + slot['slot_index']:02}:00"
    assert client.put('/terms/1/slots/generate', json=payload).json() == edited


@pytest.mark.parametrize('patch,code', [
    ({'working_days': [1, 1]}, 422),
    ({'working_days': [0]}, 422),
    ({'first_start_time': '23:00'}, 422),
    ({'slot_length_min': 30}, 422),
    ({'slots_per_day': 5}, 409),
    ({'working_days': [1, 2, 3, 4]}, 409),
])
def test_invalid_or_removing_grid_save_rolls_back(env, patch, code):
    client, _ = env
    original = client.get('/terms/1/slots').json()
    response = client.put('/terms/1/slots/generate', json=GRID | patch)
    assert response.status_code == code, response.text
    assert client.get('/terms/1/slots').json() == original


def test_save_can_add_slots_without_replacing_existing_records(env):
    client, _ = env
    before = client.get('/terms/1/slots').json()
    response = client.put('/terms/1/slots/generate', json=GRID | {'slots_per_day': 7})
    assert response.status_code == 200, response.text
    assert len(response.json()) == 35
    assert {s['slot_id'] for s in before} <= {s['slot_id'] for s in response.json()}
    assert len(client.put('/terms/1/slots/generate', json=GRID | {'slots_per_day': 7}).json()) == 35


def test_actual_duplicate_creates_and_overlaps_still_rejected(env):
    client, _ = env
    before = client.get('/terms/1/slots').json()
    assert client.post('/terms/1/slots/generate', json=GRID).status_code == 409
    assert client.post('/terms/1/slots', json=dict(day_of_week=1, slot_index=1, start_time='08:00', end_time='09:00')).status_code == 409
    assert client.post('/terms/1/slots', json=dict(day_of_week=1, slot_index=99, start_time='08:30', end_time='09:30')).status_code == 409
    assert client.get('/terms/1/slots').json() == before


@pytest.mark.parametrize('state', ['Generated', 'Published', 'Archived'])
def test_grid_edit_preserves_schedule_references_and_original_snapshot(env, state):
    client, factory = env
    with factory.begin() as db:
        publication_eligibility(db, 1)
        if state != 'Generated':
            schedule = db.get(Schedule, 1)
            schedule.status, schedule.approved_by, schedule.published_at = 'Published', 3, datetime(2026, 11, 21)
    if state == 'Archived':
        with factory.begin() as db:
            db.get(Schedule, 1).status = 'Archived'
    before = client.get('/schedules/1/entries').json()
    with factory() as db:
        snapshot = db.get(ScheduleSnapshot, 1).inputs_json
    response = client.put('/terms/1/slots/generate', json=GRID | {'first_start_time': '09:00'})
    assert response.status_code == 200, response.text
    assert client.get('/schedules/1/entries').json() == before
    with factory() as db:
        assert db.get(ScheduleSnapshot, 1).inputs_json == snapshot
        assert db.get(Schedule, 1).status == state
        assert all(db.get(TimeSlot, s['slot_id']) is not None for s in response.json())


def test_grid_save_keeps_authenticated_coordinator_permissions(env, login_as):
    client, factory = env
    client.headers.clear()
    assert client.put('/terms/1/slots/generate', json=GRID, headers={'X-User-Role': 'Coordinator'}).status_code == 401
    for username in ['admin', 'approver', 'fakhra', 'cs24a_9002']:
        headers = login_as(client, factory, username)
        assert client.put('/terms/1/slots/generate', json=GRID, headers=headers).status_code == 403


def test_grid_change_makes_generated_publication_stale(env, login_as):
    client, factory = env
    with factory.begin() as db:
        publication_eligibility(db, 1)
    assert client.put('/terms/1/slots/generate', json=GRID | {'first_start_time': '09:00'}).status_code == 200
    approver = login_as(client, factory, 'approver')
    assert client.post('/schedules/1/publish', headers=approver).status_code == 409
    with factory() as db:
        assert db.get(Schedule, 1).status == 'Generated'


def test_database_failure_rolls_back_entire_grid_edit(env):
    client, factory = env
    before = client.get('/terms/1/slots').json()
    with factory.begin() as db:
        db.execute(text("CREATE TRIGGER fail_grid_save BEFORE UPDATE ON time_slots "
                        "WHEN OLD.term_id=1 AND OLD.day_of_week=5 AND OLD.slot_index=6 "
                        "BEGIN SELECT RAISE(ABORT, 'disposable failure test'); END"))
    response = client.put('/terms/1/slots/generate', json=GRID | {'first_start_time': '09:00'})
    assert response.status_code == 409, response.text
    assert client.get('/terms/1/slots').json() == before
