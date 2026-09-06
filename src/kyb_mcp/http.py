"""Streamable HTTP ASGI app: `uvicorn kyb_mcp.http:app`, Docker, and the Vercel entrypoint.

Transport security: without an allowlist the SDK only answers requests addressed to localhost
(DNS-rebinding protection). Set KYB_ALLOWED_HOSTS=mcp.example.com for a real hostname, or run
behind a proxy that owns the Host header (Vercel sets VERCEL=1) and the check is switched off.
"""

from __future__ import annotations

from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from kyb_mcp import __version__
from kyb_mcp.server import configure_logging, mcp
from kyb_mcp.settings import Settings

configure_logging()
_settings = Settings.from_env()


def transport_security(settings: Settings) -> TransportSecuritySettings | None:
    if settings.allowed_hosts:
        hosts = [h for host in settings.allowed_hosts for h in (host, f"{host}:*")]
        return TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=settings.allowed_origins)
    if settings.behind_trusted_proxy:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return None  # localhost-only default


@mcp.custom_route("/healthz", methods=["GET"], include_in_schema=False)
async def healthz(request: Request) -> Response:
    return JSONResponse({"status": "ok", "server": "kyb-mcp", "version": __version__})


# stateless_http only affects pre-2026 clients; the 2026-07-28 path is sessionless by design.
# Stateless is the right setting for serverless hosts where instances come and go.
app = mcp.streamable_http_app(stateless_http=True, transport_security=transport_security(_settings))
