"""Alias module re-exporting `app` and `create_app` from `backend.main`."""

from backend.main import (
    DEFAULT_REACT_DEV_ORIGINS,
    app,
    create_app,
    get_cors_allowed_origins,
    recover_interrupted_generations,
)

__all__ = [
    "DEFAULT_REACT_DEV_ORIGINS",
    "app",
    "create_app",
    "get_cors_allowed_origins",
    "recover_interrupted_generations",
]
