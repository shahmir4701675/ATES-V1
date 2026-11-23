"""Reproducible operator-enrollment smoke check using a disposable SQLite file only."""
from datetime import timedelta
from pathlib import Path
import secrets
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from backend.auth import AuthSettings, password_fingerprint, utc_now, verify_password
from backend.auth_password import main
from backend.database import create_db_engine, create_session_factory, init_db
from backend.main import create_app
from backend.models import AuthSession, User
from backend.seed import seed_database


def run():
    with TemporaryDirectory(prefix="ates-b001-auth-") as directory:
        url = "sqlite:///" + (Path(directory) / "auth-smoke.sqlite").as_posix()
        engine = create_db_engine(url)
        try:
            init_db(engine)
            factory = create_session_factory(engine)
            seed_database(factory)
            now = utc_now()
            with factory() as session:
                user = session.get(User, 1)
                session.add(AuthSession(
                    token_id=secrets.token_hex(32), user_id=user.user_id,
                    credential_fingerprint=password_fingerprint(user.password_hash),
                    created_at=now, last_seen_at=now, expires_at=now + timedelta(minutes=30),
                ))
                session.commit()
            password = secrets.token_urlsafe(24)
            with patch.object(sys, "argv", ["auth-password", "coordinator", "--database-url", url]), patch(
                "backend.auth_password.getpass", side_effect=[password, password]
            ):
                main()
            with factory() as session:
                assert verify_password(password, session.get(User, 1).password_hash)
                assert session.scalar(select(func.count()).select_from(AuthSession)) == 0
            with TestClient(create_app(engine=engine, session_factory=factory, auth_settings=AuthSettings(secrets.token_hex(32)))) as client:
                login = client.post("/auth/login", json={"username": "coordinator", "password": password})
                assert login.status_code == 200
                assert client.get("/rooms", headers={"Authorization": "Bearer " + login.json()["access_token"]}).status_code == 200
            print("Operator enrollment, session revocation and real authenticated access: PASS")
        finally:
            engine.dispose()


if __name__ == "__main__":
    run()
