"""Shared test fixtures + helpers."""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from starlette.routing import Mount, Route

from abicus.server import app as fastapi_app


def _flatten_paths(routes, prefix: str = "") -> set[str]:
    """Walk nested routers (FastAPI 0.138 wraps `include_router` calls in
    `_IncludedRouter`) and return the full set of leaf paths, applying
    accumulated prefixes from any wrapper layer."""
    paths: set[str] = set()
    for r in routes:
        # Plain leaf route
        if isinstance(r, (APIRoute, Route)):
            paths.add(prefix + r.path)
            continue
        # Static mount — keep just for completeness
        if isinstance(r, Mount):
            paths.add(prefix + r.path)
            continue
        # _IncludedRouter wrapper or plain APIRouter
        ctx = getattr(r, "include_context", None)
        child_prefix = prefix
        if ctx is not None:
            child_prefix = prefix + (ctx.prefix or "")
        nested = (
            getattr(r, "original_router", None)
            or getattr(r, "router", None)
        )
        if nested is not None and hasattr(nested, "routes"):
            paths |= _flatten_paths(nested.routes, child_prefix)
        elif hasattr(r, "routes"):
            paths |= _flatten_paths(r.routes, child_prefix)
    return paths


@pytest.fixture(scope="session")
def app():
    return fastapi_app


@pytest.fixture(scope="session")
def all_paths(app):
    return _flatten_paths(app.routes)
