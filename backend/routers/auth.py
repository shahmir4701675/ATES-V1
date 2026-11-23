"""Real login/logout and current-user endpoints; passwords never leave the server."""
from __future__ import annotations

import secrets
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import and_, case, delete, or_, select, update
from sqlalchemy.orm import Session
from backend.auth import (
    AuthSettings, LOCKOUT_DURATION, MAX_FAILED_LOGINS, SESSION_IDLE_TIMEOUT,
    TOKEN_MAX_AGE, dummy_password_hash, issue_token, password_fingerprint,
    utc_now, verify_password,
    hash_password,
)
from backend.dependencies import CurrentUser, get_auth_settings, get_current_user, get_db
from backend.models import AuditLog, AuthSession, User

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=1024)


class AuthUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    username: str
    full_name: str
    email: str
    role: str
    account_status: str
    instructor_id: int | None
    batch_id: int | None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    idle_timeout_seconds: int = int(SESSION_IDLE_TIMEOUT.total_seconds())
    user: AuthUserResponse


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest, response: Response,
    settings: AuthSettings = Depends(get_auth_settings), db: Session = Depends(get_db),
) -> LoginResponse:
    now = utc_now()
    user = db.scalar(select(User).where(User.username == payload.username.strip()).with_for_update())
    password_ok = verify_password(payload.password, user.password_hash if user else dummy_password_hash())
    locked = user is not None and (
        (user.account_status == "Locked" and (user.locked_until is None or user.locked_until > now))
        or (user.locked_until is not None and user.locked_until > now)
    )
    inactive = user is not None and user.account_status == "Deactivated"
    if not user or not password_ok or locked or inactive:
        if user and not locked and not inactive:
            # Atomic increment also works where SELECT FOR UPDATE is unavailable
            # (SQLite). An expired timed lock starts a fresh attempt window.
            attempts = case(
                (and_(User.account_status == "Locked", User.locked_until <= now), 1),
                else_=User.failed_attempts + 1,
            )
            failure_count = db.scalar(update(User).where(
                User.user_id == user.user_id,
                User.account_status.in_(("Active", "Locked")),
                or_(User.locked_until.is_(None), User.locked_until <= now),
            ).values(
                failed_attempts=attempts,
                account_status=case((attempts >= MAX_FAILED_LOGINS, "Locked"), else_="Active"),
                locked_until=case((attempts >= MAX_FAILED_LOGINS, now + LOCKOUT_DURATION), else_=None),
            ).returning(User.failed_attempts).execution_options(synchronize_session=False))
            if failure_count is not None and failure_count >= MAX_FAILED_LOGINS:
                db.execute(delete(AuthSession).where(AuthSession.user_id == user.user_id))
                db.add(AuditLog(user_id=user.user_id, action="ACCOUNT_LOCKED", entity_type="users", entity_id=user.user_id))
        db.add(AuditLog(user_id=user.user_id if user else None, action="LOGIN_FAILED", entity_type="users"))
        db.commit()
        # Do not disclose which part of account/credential verification failed.
        raise HTTPException(401, "User name or password is incorrect, or the account is unavailable.", headers={"WWW-Authenticate": "Bearer"})
    if user.account_status == "Locked":
        user.account_status = "Active"  # Expired timed lock; correct password still required.
    user.failed_attempts = 0
    user.locked_until = None
    token_id = secrets.token_hex(32)
    db.add(AuthSession(
        token_id=token_id, user_id=user.user_id,
        credential_fingerprint=password_fingerprint(user.password_hash), created_at=now,
        last_seen_at=now, expires_at=now + SESSION_IDLE_TIMEOUT,
    ))
    db.add(AuditLog(user_id=user.user_id, action="LOGIN", entity_type="users", entity_id=user.user_id))
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return LoginResponse(
        access_token=issue_token(user.user_id, token_id, settings, now),
        expires_in=int(TOKEN_MAX_AGE.total_seconds()), user=AuthUserResponse.model_validate(user),
    )


@router.get("/me", response_model=AuthUserResponse)
def me(response: Response, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> AuthUserResponse:
    response.headers["Cache-Control"] = "no-store"
    return AuthUserResponse.model_validate(db.get(User, user.user_id))


@router.post("/logout", status_code=204)
def logout(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    db.execute(delete(AuthSession).where(AuthSession.auth_session_id == user.auth_session_id))
    db.add(AuditLog(user_id=user.user_id, action="LOGOUT", entity_type="users", entity_id=user.user_id))
    db.commit()
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


class ChangePasswordRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    current_password: SecretStr
    new_password: SecretStr


@router.post('/password',status_code=204)
def change_password(payload:ChangePasswordRequest,user:CurrentUser=Depends(get_current_user),db:Session=Depends(get_db)):
    row=db.get(User,user.user_id)
    if not verify_password(payload.current_password.get_secret_value(),row.password_hash):
        raise HTTPException(403,'Current password is incorrect.')
    try: row.password_hash=hash_password(payload.new_password.get_secret_value())
    except ValueError as exc: raise HTTPException(422,str(exc)) from None
    db.execute(delete(AuthSession).where(AuthSession.user_id==row.user_id))
    db.add(AuditLog(user_id=row.user_id,action='CHANGE_PASSWORD',entity_type='users',entity_id=row.user_id))
    db.commit()
    return Response(status_code=204,headers={'Cache-Control':'no-store'})
