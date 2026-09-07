from __future__ import annotations

import time

import pytest
from mcp import Client

from kyb_mcp.api.client import RateLimiter, normalize_siren
from tests.conftest import HERO, QONTO

pytestmark = pytest.mark.anyio


async def test_tool_catalogue_and_annotations(client: Client) -> None:
    tools = {t.name: t for t in (await client.list_tools()).tools}
    assert {"search_companies", "get_company", "find_by_person", "create_dossier", "archive_dossier"} <= set(
        tools
    )
    search = tools["search_companies"]
    assert search.annotations is not None and search.annotations.read_only_hint is True
    assert "ctx" not in search.input_schema["properties"], "Context must never leak into the schema"
    assert search.output_schema is not None and "results" in search.output_schema["properties"]
    archive = tools["archive_dossier"]
    assert archive.annotations is not None and archive.annotations.destructive_hint is True
    assert list(archive.input_schema["properties"]) == ["dossier_id"], "resolved params are invisible"


async def test_get_company_structured(client: Client) -> None:
    result = await client.call_tool("get_company", {"siren": "819 489 626"})
    assert result.is_error is False
    body = result.structured_content or {}
    assert body["siren"] == QONTO["siren"]
    assert body["status"] == "active"
    assert body["financials"][0]["year"] == "2023", "most recent year first"
    assert all("birth" not in k for k in body["directors"][0]), "no birth dates leave the server"


async def test_get_company_errors_are_tool_errors(client: Client) -> None:
    bad = await client.call_tool("get_company", {"siren": "12"})
    assert bad.is_error is True and "9 digits" in bad.content[0].text  # type: ignore[union-attr]
    missing = await client.call_tool("get_company", {"siren": "000000000"})
    assert missing.is_error is True and "No company" in missing.content[0].text  # type: ignore[union-attr]


async def test_upstream_failures_are_readable(client: Client) -> None:
    down = await client.call_tool("search_companies", {"query": "boom"})
    assert down.is_error is True and "retry" in down.content[0].text.lower()  # type: ignore[union-attr]
    throttled = await client.call_tool("search_companies", {"query": "throttle"})
    assert throttled.is_error is True and "rate limit" in throttled.content[0].text  # type: ignore[union-attr]


async def test_search_and_filters(client: Client, api_mock) -> None:
    result = await client.call_tool(
        "search_companies", {"query": "hero", "postal_code": "75010", "per_page": 5}
    )
    body = result.structured_content or {}
    assert body["total"] == 2 and [r["siren"] for r in body["results"]] == [HERO["siren"], QONTO["siren"]]
    sent = api_mock.calls.last.request.url.params
    assert sent["code_postal"] == "75010" and sent["etat_administratif"] == "A" and sent["minimal"] == "true"


async def test_schema_rejects_bad_arguments_before_the_handler(client: Client, api_mock) -> None:
    result = await client.call_tool("search_companies", {"query": "hero", "per_page": 999})
    assert result.is_error is True
    assert not api_mock.calls, "validation failed before any HTTP call"


async def test_find_by_person(client: Client) -> None:
    result = await client.call_tool("find_by_person", {"last_name": "Brisset", "first_names": "Morgane"})
    assert (result.structured_content or {})["results"][0]["siren"] == HERO["siren"]


def test_normalize_siren() -> None:
    assert normalize_siren(" 752 791 061 ") == "752791061"
    with pytest.raises(ValueError):
        normalize_siren("75279106")


async def test_rate_limiter_spaces_calls() -> None:
    limiter = RateLimiter(rate=100)
    start = time.monotonic()
    for _ in range(4):
        await limiter.acquire()
    assert time.monotonic() - start >= 0.025, "4 calls at 100/s need at least 30 ms"
