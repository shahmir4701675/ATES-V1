"""FastAPI application factory and entrypoint for ATES (Milestone 5b).

Conforms to:
- `docs/SRS.pdf` Table 9 & Section 3.1.4 (REST JSON API, CORS restricted to React dev server)
- `docs/SRS.pdf` Section 4.3.2 (Startup recovery marking orphaned `'Generating'` runs as
  `'Infeasible'` with `solver_status='interrupted'`).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import os
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.database import create_session_factory, session_scope
from backend.models import ConflictLog, Schedule
from backend.routers import master_data, schedules

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
    with session_scope(session_or_factory) as session:
        stuck = session.scalars(
            select(Schedule).where(Schedule.status == "Generating")
        ).all()
        for sch in stuck:
            sch.status = "Infeasible"
            sch.solver_status = "interrupted"
            session.add(
                ConflictLog(
                    schedule_id=sch.schedule_id,
                    conflict_type="ServerRestart",
                    severity="Hard",
                    description="Generation run interrupted by server restart (SRS 4.3.2).",
                    entity_ref=f"schedule_id={sch.schedule_id}",
                    is_resolved=False,
                )
            )
        return len(stuck)


def create_app(
    engine: Engine | None = None,
    *,
    session_factory: sessionmaker[Session] | None = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """Create and configure the ATES FastAPI application."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        factory = getattr(application.state, "session_factory", None)
        if factory is not None:
            recover_interrupted_generations(factory)
        yield

    application = FastAPI(
        title="Auto Timetable / Exam Scheduler (ATES) API",
        version="1.0.0",
        description="REST API for university timetable and examination scheduling (SRS Table 9).",
        lifespan=lifespan,
    )

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
    )

    # SRS Table 9 root routes
    application.include_router(master_data.router)
    application.include_router(schedules.router)

    # Optional `/api` prefix alias for convenience
    application.include_router(master_data.router, prefix="/api", include_in_schema=False)
    application.include_router(schedules.router, prefix="/api", include_in_schema=False)

    @application.get("/health", tags=["System"])
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    return application


app: FastAPI = create_app()
