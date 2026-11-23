"""Password hashing and JWT configuration for the trusted authentication boundary."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import os
import re
import secrets

import bcrypt
import jwt
from dotenv import load_dotenv
from fastapi import HTTPException
from backend.database import DEFAULT_ENV_PATH

SESSION_IDLE_TIMEOUT = timedelta(minutes=30)
TOKEN_MAX_AGE = timedelta(hours=8)
LOCKOUT_DURATION = timedelta(minutes=15)
MAX_FAILED_LOGINS = 5
JWT_ISSUER = "ates"
JWT_AUDIENCE = "ates-web"


def utc_now() -> datetime:
    """Naive UTC matches the existing database timestamp columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class AuthSettings:
    """An external deployment secret, never an insecure default signing key."""
    secret_key: str = field(repr=False)

    def __post_init__(self) -> None:
        if len(self.secret_key.encode("utf-8")) < 32 or self.secret_key.lower().startswith(
            ("replace-", "change-me", "changeme")
        ):
            raise ValueError("JWT_SECRET_KEY must be a randomly generated secret of at least 32 bytes.")

    @classmethod
    def from_environment(cls) -> AuthSettings:
        load_dotenv(DEFAULT_ENV_PATH, override=False)
        if os.environ.get("JWT_ALGORITHM", "HS256") != "HS256":
            raise ValueError("Only the server algorithm HS256 is supported.")
        return cls(os.environ.get("JWT_SECRET_KEY", ""))


def authentication_error() -> HTTPException:
    return HTTPException(401, "Authentication required or session expired. Sign in again.",
                         headers={"WWW-Authenticate": "Bearer"})


def hash_password(password: str) -> str:
    """Use a unique bcrypt cost-12 salt and never silently truncate password bytes."""
    if len(password) < 8 or len(password.encode("utf-8")) > 72:
        raise ValueError("Passwords must have at least 8 characters and at most 72 UTF-8 bytes.")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """Fail closed for malformed/placeholder hashes and invalid passwords."""
    match = re.fullmatch(r"\$2[aby]\$(\d{2})\$[./A-Za-z0-9]{53}", password_hash)
    if not match or int(match[1]) < 12 or len(password) < 8:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, UnicodeError):
        return False


@lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    """Unknown accounts still perform a bcrypt check; this is not an account password."""
    return hash_password(secrets.token_urlsafe(32))


def password_fingerprint(password_hash: str) -> str:
    """Invalidate sessions if an operator changes the stored password."""
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()


def issue_token(user_id: int, token_id: str, settings: AuthSettings, now: datetime) -> str:
    """JWTs identify a session; they never confer a role or caller-controlled identity."""
    issued = now.replace(tzinfo=timezone.utc)
    return jwt.encode(
        {"sub": str(user_id), "jti": token_id, "iat": issued, "exp": issued + TOKEN_MAX_AGE,
         "iss": JWT_ISSUER, "aud": JWT_AUDIENCE}, settings.secret_key, algorithm="HS256",
    )


def decode_token(token: str, settings: AuthSettings) -> dict:
    """Require a signed unexpired token with fixed algorithm, issuer and audience."""
    try:
        claims = jwt.decode(
            token, settings.secret_key, algorithms=["HS256"], issuer=JWT_ISSUER,
            audience=JWT_AUDIENCE, options={"require": ["sub", "jti", "iat", "exp", "iss", "aud"]},
        )
        if not claims["sub"].isdigit() or int(claims["sub"]) <= 0:
            raise ValueError("Invalid subject")
        if not isinstance(claims["jti"], str) or len(claims["jti"]) != 64:
            raise ValueError("Invalid session identifier")
        return claims
    except (jwt.PyJWTError, ValueError, TypeError, AttributeError):
        raise authentication_error() from None
