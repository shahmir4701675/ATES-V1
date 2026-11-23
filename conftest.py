"""Shared real-authentication fixtures for project tests and audit regressions.

All accounts/credentials below exist only in caller-supplied isolated test databases.
No deployment environment file, production database or dependency override is used.
"""
import secrets
import pytest
from sqlalchemy import select
from backend.auth import AuthSettings, hash_password
from backend.models import User


@pytest.fixture(scope="session")
def test_auth_settings():
    return AuthSettings(secrets.token_hex(32))


@pytest.fixture(scope="session")
def test_password():
    return secrets.token_urlsafe(24)


@pytest.fixture(scope="session")
def test_password_hash(test_password):
    return hash_password(test_password)


@pytest.fixture
def login_as(test_password, test_password_hash):
    def authenticate(client, factory, username="coordinator"):
        with factory() as session:
            user = session.scalar(select(User).where(User.username == username))
            assert user is not None, "Unknown isolated fixture account"
            user.password_hash = test_password_hash
            session.commit()
        response = client.post("/auth/login", json={"username": username, "password": test_password})
        assert response.status_code == 200, response.text
        return {"Authorization": "Bearer " + response.json()["access_token"]}
    return authenticate
