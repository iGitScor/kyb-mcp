"""Runtime configuration, read once from the environment.

Everything here has a safe local default so `uv run kyb-mcp` works with no setup:
in-memory dossier store, public company API, no auth.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _csv(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """Process-wide settings. Construct with `Settings.from_env()`."""

    api_base_url: str = "https://recherche-entreprises.api.gouv.fr"
    api_rate_per_second: float = 5.0  # public limit is 7 req/s per IP; keep headroom
    api_timeout_seconds: float = 10.0
    api_cache_ttl_seconds: float = 60.0
    database_url: str | None = None
    allowed_hosts: list[str] = field(default_factory=list)
    allowed_origins: list[str] = field(default_factory=list)
    request_state_key: str | None = None
    behind_trusted_proxy: bool = False

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            api_base_url=os.environ.get("KYB_API_BASE_URL", cls.api_base_url),
            api_rate_per_second=float(os.environ.get("KYB_API_RATE_PER_SECOND", cls.api_rate_per_second)),
            api_timeout_seconds=float(os.environ.get("KYB_API_TIMEOUT_SECONDS", cls.api_timeout_seconds)),
            api_cache_ttl_seconds=float(
                os.environ.get("KYB_API_CACHE_TTL_SECONDS", cls.api_cache_ttl_seconds)
            ),
            database_url=os.environ.get("DATABASE_URL") or None,
            allowed_hosts=_csv("KYB_ALLOWED_HOSTS"),
            allowed_origins=_csv("KYB_ALLOWED_ORIGINS"),
            request_state_key=os.environ.get("KYB_REQUEST_STATE_KEY") or None,
            # Vercel terminates TLS and owns the Host header; DNS-rebinding checks are moot there.
            behind_trusted_proxy=bool(os.environ.get("VERCEL") or os.environ.get("KYB_BEHIND_TRUSTED_PROXY")),
        )
