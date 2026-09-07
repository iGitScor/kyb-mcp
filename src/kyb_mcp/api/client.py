"""Async client for recherche-entreprises.api.gouv.fr.

Design notes (see docs/adr/0001-python-sdk-v2.md for the MCP side):
- One `httpx.AsyncClient` for the process, created in the MCP lifespan.
- A token bucket keeps us under the public rate limit (7 req/s per IP). Cloud hosts share
  IP ranges with other tenants, so the default is a conservative 5 req/s.
- A tiny TTL cache absorbs the "search, then open the same SIREN twice" pattern that
  models produce, without hiding registry updates for more than a minute.
- Upstream failures are raised as `ApiError`; the MCP layer maps them to `ToolError`
  so the model gets a readable message instead of a crash.
"""

from __future__ import annotations

import logging
import re
import time
from collections import OrderedDict
from typing import Any

import anyio
import httpx

from kyb_mcp.api.models import Company, CompanySummary, SearchResult

log = logging.getLogger(__name__)

SIREN_RE = re.compile(r"^\d{9}$")
INCLUDE_FIELDS = "siege,dirigeants,finances"
MAX_PER_PAGE = 25


class ApiError(Exception):
    """The registry API could not answer. `retryable` hints whether a later retry may succeed."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class NotFound(ApiError):
    """No company matches the identifier."""


class RateLimiter:
    """Token bucket: at most `rate` acquisitions per second, smoothed."""

    def __init__(self, rate: float) -> None:
        self._interval = 1.0 / rate if rate > 0 else 0.0
        self._lock = anyio.Lock()
        self._next_slot = 0.0

    async def acquire(self) -> None:
        if not self._interval:
            return
        async with self._lock:
            now = time.monotonic()
            wait = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + self._interval
        if wait > 0:
            await anyio.sleep(wait)


class TTLCache:
    """Smallest useful LRU+TTL cache; values are whatever you put in."""

    def __init__(self, ttl: float, maxsize: int = 256) -> None:
        self._ttl = ttl
        self._maxsize = maxsize
        self._items: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        hit = self._items.get(key)
        if hit is None:
            return None
        expires, value = hit
        if expires < time.monotonic():
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return value

    def put(self, key: str, value: Any) -> None:
        self._items[key] = (time.monotonic() + self._ttl, value)
        self._items.move_to_end(key)
        while len(self._items) > self._maxsize:
            self._items.popitem(last=False)


def normalize_siren(value: str) -> str:
    """Accept '752 791 061' or '752791061'; reject anything that is not 9 digits."""
    digits = re.sub(r"\s+", "", value)
    if not SIREN_RE.match(digits):
        raise ValueError(f"{value!r} is not a SIREN: expected exactly 9 digits")
    return digits


class CompanyApiClient:
    def __init__(
        self,
        *,
        base_url: str,
        rate_per_second: float,
        timeout_seconds: float,
        cache_ttl_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_seconds,
            headers={"User-Agent": "kyb-mcp/0.1 (+https://github.com/iGitScor/kyb-mcp)"},
            transport=transport,
        )
        self._limiter = RateLimiter(rate_per_second)
        self._cache = TTLCache(cache_ttl_seconds)
        # Names of companies seen recently, keyed by SIREN. Feeds argument completion.
        self.recent: OrderedDict[str, str] = OrderedDict()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        await self._limiter.acquire()
        try:
            response = await self._http.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise ApiError("The company registry API timed out; try again.", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"Could not reach the company registry API: {exc}", retryable=True) from exc

        if response.status_code == 429:
            raise ApiError("The company registry API is rate limiting us; wait a moment.", retryable=True)
        if response.status_code >= 500:
            raise ApiError(f"The company registry API failed ({response.status_code}).", retryable=True)
        if response.status_code >= 400:
            detail = _error_detail(response)
            raise ApiError(f"The company registry API rejected the request: {detail}")
        return response.json()

    def _remember(self, hits: list[CompanySummary]) -> None:
        for hit in hits:
            self.recent[hit.siren] = hit.name
            self.recent.move_to_end(hit.siren)
        while len(self.recent) > 50:
            self.recent.popitem(last=False)

    async def search(self, *, page: int = 1, per_page: int = 10, **filters: Any) -> SearchResult:
        params: dict[str, Any] = {
            "page": page,
            "per_page": min(max(per_page, 1), MAX_PER_PAGE),
            "minimal": "true",
            "include": INCLUDE_FIELDS,
        }
        params.update({k: v for k, v in filters.items() if v is not None})
        payload = await self._get("/search", params)
        result = SearchResult(
            total=payload.get("total_results", 0),
            page=payload.get("page", page),
            per_page=payload.get("per_page", per_page),
            total_pages=payload.get("total_pages", 0),
            results=[CompanySummary.from_api(r) for r in payload.get("results", [])],
        )
        self._remember(result.results)
        return result

    async def get_company(self, siren: str) -> Company:
        siren = normalize_siren(siren)
        cached = self._cache.get(siren)
        if cached is not None:
            return cached
        payload = await self._get(
            "/search", {"q": siren, "per_page": 1, "minimal": "true", "include": INCLUDE_FIELDS}
        )
        match = next((r for r in payload.get("results", []) if r.get("siren") == siren), None)
        if match is None:
            raise NotFound(f"No company with SIREN {siren} in the registry.")
        company = Company.from_api(match)
        self._cache.put(siren, company)
        self._remember([company])
        return company


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200] or f"HTTP {response.status_code}"
    if isinstance(body, dict):
        return str(body.get("erreur") or body.get("error") or body)[:200]
    return str(body)[:200]
