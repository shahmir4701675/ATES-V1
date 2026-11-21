"""Database connection, engine factory, and transactional session utilities for ATES.

Conforms to:
- `docs/SRS.pdf` Section 3.1.4 (Database Interface: PostgreSQL 15+ on Supabase via SQLAlchemy ORM
  over TLS; local SQLite for unit/integration tests; no Supabase client library or API keys).
- `docs/SRS.pdf` Section 4.2 `SAF-2` & Section 5.1 `DB-3`, `DB-6` (single-transaction persistence
  with automatic rollback on failure, and strict foreign-key enforcement).
- `docs/SRS.pdf` Section 4.3 `SEC-8` (`DATABASE_URL` loaded from `.env`).
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

DEFAULT_ENV_PATH: Path = Path(__file__).resolve().parent.parent / ".env"

_FORBIDDEN_SUPABASE_ENV_VARS: tuple[str, ...] = (
    "SUPABASE_KEY",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
)


def normalize_database_url(database_url: str) -> str:
    """Normalize a database connection URL for SQLAlchemy 2.x.

    Converts legacy `postgres://` or bare `postgresql://` schemes into
    `postgresql+psycopg2://` so standard Supabase PostgreSQL connection strings
    work directly with SQLAlchemy and `psycopg2`.
    """
    cleaned = database_url.strip()
    if not cleaned:
        raise ValueError("DATABASE_URL must not be empty.")
    if cleaned.startswith("postgres://"):
        cleaned = "postgresql+psycopg2://" + cleaned[len("postgres://") :]
    elif cleaned.startswith("postgresql://"):
        cleaned = "postgresql+psycopg2://" + cleaned[len("postgresql://") :]
    return cleaned


def get_database_url(
    env_file: str | Path | None = None,
    *,
    override_env: bool = False,
) -> str:
    """Read `DATABASE_URL` from `.env` (or process environment) per `SEC-8` and Section 3.1.4.

    Raises:
        RuntimeError: If `DATABASE_URL` is not configured.
    """
    target_env = Path(env_file) if env_file is not None else DEFAULT_ENV_PATH
    if target_env.is_file():
        load_dotenv(dotenv_path=target_env, override=override_env)
    else:
        load_dotenv(override=override_env)

    raw_url = os.environ.get("DATABASE_URL", "").strip()
    if not raw_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Configure DATABASE_URL in your .env file "
            "(see .env.example) to connect to Supabase PostgreSQL or local SQLite."
        )
    return normalize_database_url(raw_url)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
    """Enforce `PRAGMA foreign_keys = ON` on every SQLite connection (SRS `DB-3`)."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
        finally:
            cursor.close()


def create_db_engine(
    database_url: str | None = None,
    *,
    env_file: str | Path | None = None,
    echo: bool = False,
    **engine_kwargs: Any,
) -> Engine:
    """Create a SQLAlchemy `Engine` for Supabase PostgreSQL or local SQLite.

    When connecting to PostgreSQL (e.g. Supabase `db.<ref>.supabase.co`), `pool_pre_ping=True`
    is enabled by default for resilient pooled connections over TLS (SRS Section 3.1.4).
    """
    resolved_url = (
        normalize_database_url(database_url)
        if database_url is not None
        else get_database_url(env_file=env_file)
    )
    kwargs: dict[str, Any] = dict(engine_kwargs)
    if resolved_url.startswith("postgresql"):
        kwargs.setdefault("pool_pre_ping", True)
    elif resolved_url.startswith("sqlite"):
        connect_args = dict(kwargs.get("connect_args") or {})
        connect_args.setdefault("check_same_thread", False)
        kwargs["connect_args"] = connect_args
        if resolved_url in {"sqlite:///:memory:", "sqlite://"}:
            kwargs.setdefault("poolclass", StaticPool)

    return create_engine(resolved_url, echo=echo, **kwargs)


def create_session_factory(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
) -> sessionmaker[Session]:
    """Create a SQLAlchemy `sessionmaker` bound to the given engine (with `expire_on_commit=False`)."""
    bound_engine = engine if engine is not None else create_db_engine(database_url=database_url)
    return sessionmaker(bind=bound_engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(
    session_or_factory: Session | sessionmaker[Session] | Engine,
) -> Iterator[Session]:
    """Provide a transactional scope around a series of database operations (`DB-6`, `SAF-2`).

    - If passed a `sessionmaker` or `Engine`, opens a new `Session`, commits on clean exit,
      rolls back on any exception, and closes the session.
    - If passed an existing `Session`:
      - If the session is not yet in a transaction, runs inside `with session.begin():`.
      - If already in a transaction, flushes on exit and rolls back on exception.
    """
    if isinstance(session_or_factory, Engine):
        factory = create_session_factory(session_or_factory)
        with factory() as session:
            with session.begin():
                yield session
        return

    if isinstance(session_or_factory, sessionmaker):
        with session_or_factory() as session:
            with session.begin():
                yield session
        return

    session = session_or_factory
    if not session.in_transaction():
        with session.begin():
            yield session
    else:
        try:
            yield session
            session.flush()
        except Exception:
            session.rollback()
            raise


def init_db(engine: Engine) -> None:
    """Create all 21 ATES schema tables on the target engine (`Base.metadata.create_all`)."""
    from backend.models import Base

    Base.metadata.create_all(bind=engine)
