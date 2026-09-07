"""The MCPServer instance and its lifespan.

Everything the handlers share for the life of the process (HTTP client, dossier store,
settings) is built here once and reaches handlers through `ctx.request_context.lifespan_context`.
Handlers live in tools/, resources.py and prompts.py; they import `mcp` from this module.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast

from mcp.server import MCPServer
from mcp.server.mcpserver import Context, RequestStateSecurity

from kyb_mcp import __version__
from kyb_mcp.api.client import CompanyApiClient
from kyb_mcp.db.repo import DossierRepo, InMemoryDossierRepo, PostgresDossierRepo
from kyb_mcp.settings import Settings

log = logging.getLogger(__name__)


@dataclass
class AppContext:
    settings: Settings
    api: CompanyApiClient
    dossiers: DossierRepo


# The completion handler has no Context parameter, so it reads the live client from here.
current: AppContext | None = None


@asynccontextmanager
async def app_lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
    global current
    settings = Settings.from_env()
    api = CompanyApiClient(
        base_url=settings.api_base_url,
        rate_per_second=settings.api_rate_per_second,
        timeout_seconds=settings.api_timeout_seconds,
        cache_ttl_seconds=settings.api_cache_ttl_seconds,
    )
    if settings.database_url:
        dossiers: DossierRepo = await PostgresDossierRepo.connect(settings.database_url)
        log.info("dossier store: postgres")
    else:
        dossiers = InMemoryDossierRepo()
        log.warning("dossier store: in-memory (set DATABASE_URL for persistence)")
    app = AppContext(settings=settings, api=api, dossiers=dossiers)
    current = app
    try:
        yield app
    finally:
        current = None
        await dossiers.aclose()
        await api.aclose()


def app_of(ctx: Context) -> AppContext:
    """Typed access to the lifespan object from resources and prompts (which take a bare Context)."""
    return cast(AppContext, ctx.request_context.lifespan_context)


INSTRUCTIONS = """\
KYB (Know Your Business) workbench over the French company registry.

Start with `search_companies` (name, address, director) or `get_company` when you have a SIREN
(9 digits). Open a `create_dossier` for a company under review, add findings with `add_note`,
move it with `set_status`, and read `company://{siren}` / `dossier://{id}` for the full records.
The `kyb_review` prompt runs a structured review. Registry data is public; do not infer identity
from name matches alone.
"""


def _request_state_security() -> RequestStateSecurity | None:
    # Multi-round-trip tools (elicitation, sampling) seal state in a per-process key by default.
    # Behind a load balancer every instance must share one key: KYB_REQUEST_STATE_KEY.
    key = os.environ.get("KYB_REQUEST_STATE_KEY")
    return RequestStateSecurity(keys=[key]) if key else None


mcp = MCPServer(
    "kyb-mcp",
    title="KYB Workbench",
    instructions=INSTRUCTIONS,
    version=__version__,
    website_url="https://github.com/iGitScor/kyb-mcp",
    lifespan=app_lifespan,
    request_state_security=_request_state_security(),
)
