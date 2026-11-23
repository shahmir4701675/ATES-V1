"""Database sessions and trusted authentication/role dependencies for business routes."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Iterator
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker
from backend.auth import AuthSettings, SESSION_IDLE_TIMEOUT, authentication_error, decode_token, password_fingerprint, utc_now
from backend.database import create_db_engine, create_session_factory
from backend.models import AuthSession, User

VALID_ROLES = frozenset({'Administrator', 'Coordinator', 'Approver', 'Faculty', 'Student'})
bearer = HTTPBearer(auto_error=False)

@dataclass(frozen=True)
class CurrentUser:
    """Identity loaded from the active database account, never request identity headers."""
    user_id: int
    username: str
    role: str
    instructor_id: int | None
    batch_id: int | None
    auth_session_id: int

def get_session_factory_from_request(request: Request) -> sessionmaker[Session]:
    factory = getattr(request.app.state, 'session_factory', None)
    if factory is None:
        engine = getattr(request.app.state, 'engine', None)
        if engine is None:
            engine = create_db_engine()
            request.app.state.engine = engine
        factory = create_session_factory(engine)
        request.app.state.session_factory = factory
    return factory

def get_db(request: Request) -> Iterator[Session]:
    with get_session_factory_from_request(request)() as session:
        yield session

def get_auth_settings(request: Request) -> AuthSettings:
    settings = getattr(request.app.state, 'auth_settings', None)
    if settings is None:
        try:
            settings = AuthSettings.from_environment()
        except ValueError:
            raise HTTPException(503, 'Authentication is not configured. Contact the administrator.') from None
        request.app.state.auth_settings = settings
    return settings

def get_token_claims(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    # Anonymous requests fail before resolving the deployment database or settings.
    if credentials is None or credentials.scheme.lower() != 'bearer':
        raise authentication_error()
    return decode_token(credentials.credentials, get_auth_settings(request))

def get_current_user(claims: dict = Depends(get_token_claims), db: Session = Depends(get_db)) -> CurrentUser:
    now = utc_now()
    auth_session = db.scalar(select(AuthSession).where(AuthSession.token_id == claims['jti']))
    if auth_session is None or auth_session.user_id != int(claims['sub']) or auth_session.expires_at <= now:
        raise authentication_error()
    user = db.get(User, auth_session.user_id)
    if user is None or auth_session.credential_fingerprint != password_fingerprint(user.password_hash):
        raise authentication_error()
    if user.account_status != 'Active' or (user.locked_until is not None and user.locked_until > now):
        raise HTTPException(403, 'This account is not active. Contact the administrator.')
    if user.role not in VALID_ROLES or (user.role == 'Faculty' and user.instructor_id is None) or (user.role == 'Student' and user.batch_id is None):
        raise HTTPException(403, 'This account has no valid role or identity link.')
    identity = CurrentUser(user.user_id, user.username, user.role, user.instructor_id, user.batch_id, auth_session.auth_session_id)
    # This update cannot resurrect a session concurrently deleted by logout.
    touched = db.execute(update(AuthSession).where(
        AuthSession.auth_session_id == auth_session.auth_session_id,
        AuthSession.expires_at > now,
    ).values(last_seen_at=now, expires_at=now + SESSION_IDLE_TIMEOUT))
    if touched.rowcount != 1:
        db.rollback()
        raise authentication_error()
    db.commit()
    db.info['authenticated_actor']=identity.user_id
    return identity

def require_roles(*allowed_roles: str) -> Callable[[CurrentUser], CurrentUser]:
    """An authenticated but unauthorized caller gets 403; no default/adapted roles."""
    allowed = frozenset(allowed_roles)
    def check_role(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(403, 'Your role is not permitted to perform this action.')
        return user
    return check_role
