"""FastAPI dependencies for database sessions and role-based access control readiness.

Conforms to:
- `docs/SRS.pdf` Section 3.1.4 & Section 3.2.2 `FR-1.5`, `SEC-3` (Role-based access checks on routes).
- Milestone 5b specification: No authentication required yet, while keeping all routes
  wired with role dependencies ready for JWT enforcement in Milestone 6.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session, sessionmaker

from backend.database import create_db_engine, create_session_factory

VALID_ROLES: frozenset[str] = frozenset(
    {"Administrator", "Coordinator", "Approver", "Faculty", "Student"}
)


@dataclass
class CurrentUser:
    """Represents the active request user context for RBAC checks (`FR-1.5`, `SEC-3`)."""

    user_id: int = 1
    username: str = "coordinator"
    role: str = "Coordinator"
    instructor_id: int | None = None
    batch_id: int | None = None
    explicit_role: bool = False


def get_session_factory_from_request(request: Request) -> sessionmaker[Session]:
    """Retrieve or lazily initialize the SQLAlchemy `sessionmaker` on `app.state`."""
    factory: sessionmaker[Session] | None = getattr(
        request.app.state, "session_factory", None
    )
    if factory is None:
        engine = getattr(request.app.state, "engine", None)
        if engine is None:
            engine = create_db_engine()
            request.app.state.engine = engine
        factory = create_session_factory(engine)
        request.app.state.session_factory = factory
    return factory


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI dependency yielding a SQLAlchemy `Session` per request."""
    factory = get_session_factory_from_request(request)
    with factory() as session:
        yield session


def get_current_user(
    x_user_id: int | None = Header(default=None, alias="X-User-Id"),
    x_user_role: str | None = Header(default=None, alias="X-User-Role"),
    x_instructor_id: int | None = Header(default=None, alias="X-Instructor-Id"),
    x_batch_id: int | None = Header(default=None, alias="X-Batch-Id"),
) -> CurrentUser:
    """Resolve the current user context (no authentication required in Milestone 5b).

    When `X-User-Role` is supplied (or when `get_current_user` is overridden in tests or
    replaced with JWT decoding in Milestone 6), explicit RBAC role checks are enforced.
    """
    if x_user_role is not None:
        normalized_role = x_user_role.strip()
        return CurrentUser(
            user_id=x_user_id or 1,
            username=normalized_role.lower(),
            role=normalized_role,
            instructor_id=x_instructor_id,
            batch_id=x_batch_id,
            explicit_role=True,
        )
    return CurrentUser(
        user_id=x_user_id or 1,
        username="coordinator",
        role="Coordinator",
        instructor_id=x_instructor_id,
        batch_id=x_batch_id,
        explicit_role=False,
    )


def require_roles(*allowed_roles: str) -> Callable[[CurrentUser], CurrentUser]:
    """Route dependency factory enforcing RBAC role permissions (`FR-1.5`, `SEC-3`).

    - In Milestone 5b (unauthenticated requests without `X-User-Role`), allows the call
      and defaults the user context to the primary allowed role.
    - When an explicit role is provided (via `X-User-Role` or dependency override),
      rejects unauthorized roles with HTTP `403 Forbidden`.
    """
    allowed_set = frozenset(allowed_roles)

    def _check_role(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.explicit_role and user.role == "Coordinator" and "Coordinator" not in allowed_set:
            # In unauthenticated Milestone 5b mode, adapt default role to route's primary role
            primary_role = allowed_roles[0] if allowed_roles else "Coordinator"
            return CurrentUser(
                user_id=user.user_id,
                username=primary_role.lower(),
                role=primary_role,
                instructor_id=user.instructor_id,
                batch_id=user.batch_id,
                explicit_role=False,
            )
        if user.role not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Role '{user.role}' is not permitted to perform this action. "
                    f"Allowed roles: {', '.join(allowed_roles)}."
                ),
            )
        return user

    return _check_role
