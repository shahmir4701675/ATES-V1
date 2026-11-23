"""FastAPI application factory and entrypoint for ATES (Milestone 5b).

Conforms to:
- `docs/SRS.pdf` Table 9 & Section 3.1.4 (REST JSON API, CORS restricted to React dev server)
- `docs/SRS.pdf` Section 4.3.2 (Startup recovery marking orphaned `'Generating'` runs as
  `'Infeasible'` with `solver_status='interrupted'`).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import os
import threading
from types import SimpleNamespace
from typing import AsyncIterator

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.database import create_session_factory, session_scope
from backend.models import ConflictLog, Schedule
from backend.routers import auth, accounts, imports, master_data, schedules, exports
from backend.auth import AuthSettings
from backend.dependencies import get_current_user
import backend.mutation_audit

DEFAULT_REACT_DEV_ORIGINS: tuple[str, ...] = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)


def get_cors_allowed_origins() -> list[str]:
    """Return allowed CORS origins restricted strictly to the React dev server (SRS 3.1.4)."""
    raw = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
    if raw:
        origins = [o.strip() for o in raw.split(",") if o.strip() and o.strip() != "*"]
        if origins:
            return origins
    return list(DEFAULT_REACT_DEV_ORIGINS)


def recover_interrupted_generations(
    session_or_factory: Session | sessionmaker[Session] | Engine,
) -> int:
    """Mark any schedules stuck in `'Generating'` as `'Infeasible'` (`solver_status='interrupted'`).

    Implements SRS Section 4.3.2 reliability requirement on server startup.
    """
    from backend.generation import recover_runs
    return recover_runs(session_or_factory)


def create_app(
    engine: Engine | None = None,
    *,
    session_factory: sessionmaker[Session] | None = None,
    cors_origins: list[str] | None = None,
    auth_settings: AuthSettings | None = None,
) -> FastAPI:
    """Create and configure the ATES FastAPI application."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        from backend.dependencies import get_session_factory_from_request
        # Use the same initialization path as requests, before recovery runs.
        factory = get_session_factory_from_request(SimpleNamespace(app=application))
        recover_interrupted_generations(factory)
        stopped=threading.Event()
        def reap():
            while not stopped.wait(1):
                try: recover_interrupted_generations(factory)
                except Exception: pass  # No unsafe fallback; workers retain their own deadlines.
        engine=factory.kw['bind']
        reaper=None
        if not (engine.dialect.name=="sqlite" and engine.url.database in (None,"",":memory:")):
            reaper=threading.Thread(target=reap,daemon=True); reaper.start()
        try:
            yield
        finally:
            stopped.set()
            if reaper: reaper.join(2)

    application = FastAPI(
        title="Auto Timetable / Exam Scheduler (ATES) API",
        version="1.0.0",
        description="REST API for university timetable and examination scheduling (SRS Table 9).",
        lifespan=lifespan,
    )

    from backend.schedule_integrity import SnapshotIntegrityError
    @application.exception_handler(SnapshotIntegrityError)
    async def snapshot_error(_request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc), "code": "VERSION_CONTEXT_INVALID"})
    from sqlalchemy.exc import IntegrityError
    @application.exception_handler(IntegrityError)
    async def integrity_error(_request, exc):
        return JSONResponse(status_code=409, content={"detail": "Database integrity guard rejected this change."})
    from sqlalchemy.exc import OperationalError,DataError
    @application.exception_handler(OperationalError)
    async def database_operational_error(_request,exc):
        code=getattr(exc.orig,'pgcode',None)
        conflict=code in {'40001','40P01','55P03'} or 'locked' in str(exc.orig).lower() or 'busy' in str(exc.orig).lower()
        return JSONResponse(status_code=409 if conflict else 503,content={'detail':'Concurrent database operation; reload and retry.' if conflict else 'Database temporarily unavailable. Reload before retrying.','code':'DB_CONFLICT' if conflict else 'DB_UNAVAILABLE'})
    @application.exception_handler(DataError)
    async def database_data_error(_request,exc):
        return JSONResponse(status_code=422,content={'detail':'A value is outside the database field domain.'})
    @application.exception_handler(OverflowError)
    async def database_integer_error(_request,exc):
        return JSONResponse(status_code=422,content={'detail':'Integer value is outside the supported database range.'})

    if auth_settings is not None:
        application.state.auth_settings = auth_settings

    if engine is not None:
        application.state.engine = engine
        application.state.session_factory = (
            session_factory or create_session_factory(engine)
        )
    elif session_factory is not None:
        application.state.session_factory = session_factory

    allowed_origins = (
        list(cors_origins) if cors_origins is not None else get_cors_allowed_origins()
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition", "X-Total-Count"],
    )

    # SRS Table 9 root routes
    # Resolve identity before route-level DB dependencies or business validation.
    # Individual handlers additionally enforce their permitted roles.
    protected = [Depends(get_current_user)]
    application.include_router(master_data.router, dependencies=protected)
    application.include_router(schedules.router, dependencies=protected)
    application.include_router(auth.router)
    application.include_router(accounts.router, dependencies=protected)
    application.include_router(imports.router, dependencies=protected)
    application.include_router(exports.router, dependencies=protected)

    # Optional `/api` prefix alias for convenience
    application.include_router(master_data.router, prefix="/api", include_in_schema=False, dependencies=protected)
    application.include_router(schedules.router, prefix="/api", include_in_schema=False, dependencies=protected)
    application.include_router(auth.router, prefix="/api", include_in_schema=False)
    application.include_router(accounts.router, prefix="/api", include_in_schema=False, dependencies=protected)
    application.include_router(imports.router, prefix="/api", include_in_schema=False, dependencies=protected)
    application.include_router(exports.router, prefix="/api", include_in_schema=False, dependencies=protected)
    application.add_middleware(imports.ImportBodyLimit)
    from backend.performance import APITransport
    application.add_middleware(APITransport)

    @application.get("/health", tags=["System"])
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    return application


app: FastAPI = create_app()
