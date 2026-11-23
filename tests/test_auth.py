"""B001 regression suite: real bcrypt/JWT/database sessions, isolated SQLite only."""
from datetime import timedelta
from pathlib import Path
import secrets
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select

from backend.auth import (
    AuthSettings, JWT_AUDIENCE, JWT_ISSUER, SESSION_IDLE_TIMEOUT,
    hash_password, utc_now, verify_password,
)
from backend.database import create_db_engine, create_session_factory, init_db
from backend.main import create_app
from backend.models import AuditLog, AuthSession, Room, Schedule, SchedulingConfig, User
from backend.seed import seed_database


@pytest.fixture
def auth_env(test_auth_settings):
    engine = create_db_engine("sqlite:///:memory:")
    init_db(engine)
    factory = create_session_factory(engine)
    seed_database(factory)
    with TestClient(create_app(engine=engine, session_factory=factory, auth_settings=test_auth_settings)) as client:
        yield client, factory
    engine.dispose()


def test_all_business_routes_and_api_aliases_reject_anonymous(auth_env):
    client, _ = auth_env
    checked = 0
    for path, operations in client.app.openapi()["paths"].items():
        if path.startswith("/auth") or path == "/health":
            continue
        for name in path.split("{")[1:]:
            path = path.replace("{" + name.split("}")[0] + "}", "1")
        for method in operations:
            for prefix in ("", "/api"):
                response = client.request(method, prefix + path, json={} if method in ("put", "post") else None)
                assert response.status_code == 401, (method, prefix + path, response.text)
                assert response.headers["www-authenticate"] == "Bearer"
                checked += 1
    assert checked >= 100


@pytest.mark.parametrize("headers", [
    {}, {"X-User-Role": "Administrator"}, {"X-User-Role": "Coordinator", "X-User-Id": "1"},
    {"X-User-Id": "not-an-integer", "X-Instructor-Id": "1", "X-Batch-Id": "1"},
    {"Authorization": "Basic dXNlcjpwYXNz"}, {"Authorization": "Bearer broken.token"},
])
def test_anonymous_or_forged_identity_cannot_write(auth_env, headers):
    client, factory = auth_env
    response = client.post("/rooms", headers=headers, json={"room_code": "FORGED", "building": "A", "capacity": 30, "room_type": "Lecture"})
    assert response.status_code == 401
    with factory() as session:
        assert session.scalar(select(Room).where(Room.room_code == "FORGED")) is None


def test_real_login_and_current_identity_ignore_headers(auth_env, login_as):
    client, factory = auth_env
    headers = {**login_as(client, factory, "cs24a_9002"), "X-User-Role": "Coordinator", "X-User-Id": "1", "X-Batch-Id": "2"}
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["user_id"] == 9002
    assert response.json()["role"] == "Student"
    assert response.json()["batch_id"] == 1
    assert "password_hash" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert client.post("/rooms", headers=headers, json={"room_code": "FORBIDDEN", "building": "A", "capacity": 30, "room_type": "Lecture"}).status_code == 403


@pytest.mark.parametrize("username", ["admin", "approver", "fakhra", "cs24a_9002"])
def test_only_coordinator_can_generate_or_change_master_data(auth_env, login_as, username):
    client, factory = auth_env
    headers = login_as(client, factory, username)
    with patch("backend.routers.schedules.run_schedule_generation_worker") as worker:
        assert client.post("/schedules/generate", headers=headers, json={"term_id": 1}).status_code == 403
        worker.assert_not_called()
    assert client.post("/rooms", headers=headers, json={"room_code": "DENIED", "building": "A", "capacity": 30, "room_type": "Lecture"}).status_code == 403


def test_coordinator_retains_legitimate_write_access(auth_env, login_as):
    client, factory = auth_env
    response = client.post("/rooms", headers=login_as(client, factory), json={"room_code": "AUTH-OK", "building": "A", "capacity": 30, "room_type": "Lecture"})
    assert response.status_code == 201
    assert response.json()["room_code"] == "AUTH-OK"


def test_role_and_identity_changes_take_effect_from_storage(auth_env, login_as):
    client, factory = auth_env
    headers = login_as(client, factory)
    with factory() as session:
        session.get(User, 1).role = "Approver"
        session.commit()
    assert client.get("/auth/me", headers=headers).json()["role"] == "Approver"
    assert client.post("/schedules/generate", headers=headers, json={"term_id": 1}).status_code == 403


def test_faculty_link_is_trusted_not_spoofed(auth_env, login_as):
    client, factory = auth_env
    headers = {**login_as(client, factory, "fakhra"), "X-Instructor-Id": "2", "X-User-Role": "Coordinator"}
    assert client.get("/auth/me", headers=headers).json()["instructor_id"] == 1
    assert client.put("/instructors/2/availability", headers=headers, json={"slots": []}).status_code == 403
    assert client.put("/instructors/1/availability", headers=headers, json={"slots": []}).status_code == 200


@pytest.mark.parametrize("state", ["Deactivated", "Locked"])
def test_inactive_account_denied_even_with_previously_valid_token(auth_env, login_as, state):
    client, factory = auth_env
    headers = login_as(client, factory)
    with factory() as session:
        user = session.get(User, 1)
        user.account_status = state
        user.locked_until = utc_now() + timedelta(minutes=15) if state == "Locked" else None
        session.commit()
    assert client.get("/rooms", headers=headers).status_code == 403


@pytest.mark.parametrize("state", ["Deactivated", "Locked"])
def test_inactive_account_cannot_login(auth_env, test_password, test_password_hash, state):
    client, factory = auth_env
    with factory() as session:
        user = session.get(User, 1)
        user.password_hash = test_password_hash
        user.account_status = state
        user.locked_until = utc_now() + timedelta(minutes=15) if state == "Locked" else None
        session.commit()
    assert client.post("/auth/login", json={"username": "coordinator", "password": test_password}).status_code == 401
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AuthSession)) == 0


def test_unknown_wrong_and_placeholder_passwords_fail_closed(auth_env, login_as, test_password):
    client, factory = auth_env
    assert client.post("/auth/login", json={"username": "missing", "password": test_password}).status_code == 401
    assert client.post("/auth/login", json={"username": "coordinator", "password": test_password}).status_code == 401
    login_as(client, factory)
    assert client.post("/auth/login", json={"username": "coordinator", "password": "wrong-password"}).status_code == 401


def test_logout_revokes_only_current_session(auth_env, login_as):
    client, factory = auth_env
    first, second = login_as(client, factory), login_as(client, factory)
    assert client.post("/auth/logout", headers=first).status_code == 204
    assert client.get("/rooms", headers=first).status_code == 401
    assert client.get("/rooms", headers=second).status_code == 200
    assert client.post("/auth/logout").status_code == 401


def test_idle_expiry_and_sliding_activity(auth_env, login_as):
    client, factory = auth_env
    headers = login_as(client, factory)
    now = utc_now()
    with factory() as session:
        stored = session.scalar(select(AuthSession))
        stored.expires_at = now + timedelta(minutes=1)
        session.commit()
    with patch("backend.dependencies.utc_now", return_value=now):
        assert client.get("/rooms", headers=headers).status_code == 200
    with factory() as session:
        stored = session.scalar(select(AuthSession))
        assert stored.last_seen_at == now
        assert stored.expires_at == now + SESSION_IDLE_TIMEOUT
    with patch("backend.dependencies.utc_now", return_value=now + SESSION_IDLE_TIMEOUT):
        assert client.get("/rooms", headers=headers).status_code == 401


@pytest.mark.parametrize("mutation", ["signature", "expired", "none", "issuer", "audience", "subject", "session", "missing-exp"])
def test_forged_expired_and_malformed_jwts_rejected(auth_env, login_as, test_auth_settings, mutation):
    client, factory = auth_env
    token = login_as(client, factory)["Authorization"].split()[1]
    claims = jwt.decode(token, options={"verify_signature": False})
    signing_key, algorithm = test_auth_settings.secret_key, "HS256"
    if mutation == "signature":
        signing_key = secrets.token_hex(32)
    elif mutation == "expired":
        claims["exp"] = 1
    elif mutation == "none":
        algorithm, signing_key = "none", ""
    elif mutation == "issuer":
        claims["iss"] = "untrusted"
    elif mutation == "audience":
        claims["aud"] = "untrusted"
    elif mutation == "subject":
        claims["sub"] = "2"  # Does not own the session.
    elif mutation == "session":
        claims["jti"] = secrets.token_hex(32)  # Correct signature is insufficient.
    elif mutation == "missing-exp":
        del claims["exp"]
    forged = jwt.encode(claims, signing_key, algorithm=algorithm)
    assert client.get("/rooms", headers={"Authorization": "Bearer " + forged}).status_code == 401


def test_password_change_invalidates_existing_session(auth_env, login_as):
    client, factory = auth_env
    headers = login_as(client, factory)
    with factory() as session:
        session.get(User, 1).password_hash = hash_password(secrets.token_urlsafe(24))
        session.commit()
    assert client.get("/rooms", headers=headers).status_code == 401


def test_five_failed_logins_lock_for_fifteen_minutes_and_audit(auth_env, login_as, test_password):
    client, factory = auth_env
    headers = login_as(client, factory)
    now = utc_now()
    with patch("backend.routers.auth.utc_now", return_value=now):
        for _ in range(5):
            assert client.post("/auth/login", json={"username": "coordinator", "password": "wrong-password"}).status_code == 401
    with factory() as session:
        user = session.get(User, 1)
        assert user.account_status == "Locked"
        assert user.failed_attempts == 5
        assert user.locked_until == now + timedelta(minutes=15)
        actions = session.scalars(select(AuditLog.action)).all()
        assert actions.count("LOGIN_FAILED") == 5
        assert actions.count("ACCOUNT_LOCKED") == 1
        assert not any(test_password in (line or "") for line in session.scalars(select(AuditLog.details)))
    assert client.get("/rooms", headers=headers).status_code == 401  # Lockout revokes sessions.
    assert client.post("/auth/login", json={"username": "coordinator", "password": test_password}).status_code == 401
    with patch("backend.routers.auth.utc_now", return_value=now + timedelta(minutes=15)):
        assert client.post("/auth/login", json={"username": "coordinator", "password": test_password}).status_code == 200
    with factory() as session:
        assert session.get(User, 1).failed_attempts == 0
        assert session.get(User, 1).account_status == "Active"


def test_request_body_cannot_forge_creator_or_generator(auth_env, login_as):
    client, factory = auth_env
    headers = {**login_as(client, factory), "X-User-Id": "2"}
    response = client.post("/configs", headers=headers, json={"term_id": 1, "schedule_type": "Timetable", "name": "AUTH-CREATOR", "created_by": 2})
    assert response.status_code == 201
    assert response.json()["created_by"] == 1
    with patch("backend.routers.schedules.run_schedule_generation_worker"):
        generated = client.post("/schedules/generate", headers=headers, json={"term_id": 1, "generated_by": 2})
    assert generated.status_code == 202
    with factory() as session:
        assert session.get(Schedule, generated.json()["schedule_id"]).generated_by == 1


def test_no_fallback_secret_and_no_database_access_for_anonymous():
    client = TestClient(create_app())
    with patch("backend.dependencies.create_db_engine", side_effect=AssertionError("Must not resolve database")):
        assert client.get("/rooms").status_code == 401
        with patch("backend.auth.AuthSettings.from_environment", side_effect=ValueError("missing key")):
            assert client.post("/auth/login", json={"username": "x", "password": "password"}).status_code == 503
    for value in ("", "short", "replace-with-a-cryptographically-random-256-bit-hex-secret"):
        with pytest.raises(ValueError):
            AuthSettings(value)


def test_bcrypt_cost_salt_and_password_bounds():
    password = secrets.token_urlsafe(24)
    first, second = hash_password(password), hash_password(password)
    assert first.startswith("$2b$12$") and first != second
    assert verify_password(password, first)
    assert not verify_password("wrong-password", first)
    assert not verify_password(password, "invalid")
    for value in ("short", "x" * 73, "پ" * 40):
        with pytest.raises(ValueError):
            hash_password(value)
    assert not verify_password("x" * 73, first)


def test_sessions_survive_app_restart_and_logout_across_instances(auth_env, login_as, test_auth_settings):
    client, factory = auth_env
    headers = login_as(client, factory)
    with TestClient(create_app(session_factory=factory, auth_settings=test_auth_settings)) as other:
        assert other.get("/auth/me", headers=headers).status_code == 200
        assert other.post("/auth/logout", headers=headers).status_code == 204
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_sqlite_auth_migration_matches_orm_without_changing_business_tables():
    engine = create_db_engine("sqlite:///:memory:")
    # This tests migration 001 against its original 21-table business baseline,
    # independently of the later additive B004 integrity migration.
    from backend.models import Base
    prior_tables = [table for table in Base.metadata.sorted_tables if table.name not in {
        "schedule_input_state", "schedule_snapshots", "schedule_validation_receipts", "generation_runs", "import_stages", "schedule_edit_revisions"
    }]
    Base.metadata.create_all(engine, tables=prior_tables)
    AuthSession.__table__.drop(engine)  # Disposable in-memory database only.
    before = set(inspect(engine).get_table_names())
    assert len(before) == 21
    raw = engine.raw_connection()
    try:
        raw.driver_connection.executescript((Path(__file__).parents[1] / "db/migrations/001_auth_sessions.sqlite.sql").read_text())
    finally:
        raw.close()
    assert set(inspect(engine).get_table_names()) == before | {"auth_sessions"}
    assert {c["name"] for c in inspect(engine).get_columns("auth_sessions")} == set(AuthSession.__table__.columns.keys())
    assert {i["name"] for i in inspect(engine).get_indexes("auth_sessions")} >= {"idx_auth_sessions_user_id", "idx_auth_sessions_expires_at"}
    engine.dispose()
