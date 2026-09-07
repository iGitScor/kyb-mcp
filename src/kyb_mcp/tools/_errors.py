"""Map client-layer failures to `ToolError` so the model reads a message it can act on."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps

from mcp.server.mcpserver.exceptions import ToolError

from kyb_mcp.api.client import ApiError


def tool_errors[**P, R](fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    @wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await fn(*args, **kwargs)
        except ValueError as exc:  # e.g. malformed SIREN
            raise ToolError(str(exc)) from exc
        except ApiError as exc:
            hint = " You can retry." if exc.retryable else ""
            raise ToolError(f"{exc}{hint}") from exc

    return wrapper
