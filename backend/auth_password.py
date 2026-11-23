"""Operator-only password enrollment for an existing account; never run at startup."""
from __future__ import annotations

import argparse
from getpass import getpass
from sqlalchemy import delete, select
from backend.auth import hash_password
from backend.database import create_db_engine, session_scope
from backend.models import AuditLog, AuthSession, User


def main() -> None:
    parser = argparse.ArgumentParser(description="Set an existing ATES account password in the explicitly selected database.")
    parser.add_argument("username")
    parser.add_argument("--database-url", required=True, help="Operator-selected database; no implicit production/.env target.")
    args = parser.parse_args()
    password = getpass("New password (minimum 8 characters): ")
    if password != getpass("Confirm password: "):
        parser.error("Passwords do not match.")
    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        parser.error(str(exc))
    engine = create_db_engine(args.database_url)
    try:
        with session_scope(engine) as session:
            user = session.scalar(select(User).where(User.username == args.username))
            if user is None:
                parser.error("Account not found; create accounts through the administrator's provisioning workflow.")
            user.password_hash = password_hash
            user.failed_attempts = 0
            user.locked_until = None
            if user.account_status == "Locked":
                user.account_status = "Active"
            session.execute(delete(AuthSession).where(AuthSession.user_id == user.user_id))
            session.add(AuditLog(
                user_id=None, action="PASSWORD_ENROLLED", entity_type="users",
                entity_id=user.user_id, details="Operator password enrollment; sessions revoked.",
            ))
        print("Password updated; existing sessions revoked. Account roles/status otherwise preserved.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
