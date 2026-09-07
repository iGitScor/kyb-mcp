"""Shared fixtures: a mocked registry API and an in-process MCP client.

`respx` intercepts every httpx call the server makes, so tests are offline and deterministic.
`Client(mcp)` connects in memory; each test gets a fresh lifespan (and a fresh in-memory store).
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from mcp import Client

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "companies.json").read_text(encoding="utf-8"))
HERO = FIXTURES["hero"]
QONTO = FIXTURES["qonto"]
BY_SIREN = {HERO["siren"]: HERO, QONTO["siren"]: QONTO}
API = "https://recherche-entreprises.api.gouv.fr"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _page(results: list[dict[str, Any]], *, page: int = 1, per_page: int = 10) -> dict[str, Any]:
    return {
        "results": results,
        "total_results": len(results),
        "page": page,
        "per_page": per_page,
        "total_pages": 1,
    }


def registry(request: httpx.Request) -> httpx.Response:
    params = dict(request.url.params)
    q = params.get("q", "")
    if params.get("nom_personne"):
        return httpx.Response(200, json=_page([HERO]))
    if q == "boom":
        return httpx.Response(500, text="upstream exploded")
    if q == "throttle":
        return httpx.Response(429, json={"erreur": "too many requests"})
    if q == "nothing":
        return httpx.Response(200, json=_page([]))
    if q.isdigit() and len(q) == 9:
        hit = BY_SIREN.get(q)
        return httpx.Response(200, json=_page([hit] if hit else []))
    return httpx.Response(200, json=_page([HERO, QONTO]))


@pytest.fixture(autouse=True)
def api_mock() -> Iterator[respx.MockRouter]:
    os.environ.pop("DATABASE_URL", None)  # tool tests always use the in-memory store
    with respx.mock(base_url=API, assert_all_called=False) as router:
        router.get("/search").mock(side_effect=registry)
        yield router


@pytest.fixture
async def client() -> AsyncIterator[Client]:
    from kyb_mcp.server import mcp

    async with Client(mcp, raise_exceptions=True) as c:
        yield c
