"""ntopng → Copilot Studio gateway.

A read-only HTTP facade over ntopng's REST v2 API, shaped for an agent rather
than for a dashboard: flat models, plain-language field names, small payloads,
and an OpenAPI document Power Platform can import as a custom connector.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from . import __version__
from .config import get_settings
from .ntopng import NtopngClient
from .routers import flows, hosts, overview
from .security import require_api_key


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.ntopng = NtopngClient(settings)
    try:
        yield
    finally:
        await app.state.ntopng.aclose()


app = FastAPI(
    title="ntopng Network Analyzer",
    version=__version__,
    description=(
        "Read-only network visibility over ntopng: active hosts, live flows, "
        "protocol breakdown and alerts. Built to back a Microsoft Copilot Studio "
        "agent, but usable by any HTTP client."
    ),
    lifespan=lifespan,
    # Every route is authenticated; the docs and the OpenAPI document stay open
    # so the connector can be imported without a key.
    dependencies=[Depends(require_api_key)],
)

app.include_router(overview.router)
app.include_router(hosts.router)
app.include_router(flows.router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "service": "ntopng-copilot-gateway",
        "version": __version__,
        "openapi": "/openapi.json",
        "docs": "/docs",
    }
