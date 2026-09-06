"""Resources: addressed data the client application loads as context."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver.exceptions import ResourceError, ResourceNotFoundError

from kyb_mcp import naf
from kyb_mcp.api.client import ApiError, NotFound
from kyb_mcp.core import Context, app_of, mcp
from kyb_mcp.db.repo import ACTIVE_STATUSES, STATUS_VALUES


@mcp.resource("company://{siren}", title="Company record", mime_type="application/json")
async def company_resource(siren: str, ctx: Context) -> dict[str, Any]:
    """Full registry record for a company (same shape as the get_company tool)."""
    try:
        company = await app_of(ctx).api.get_company(siren)
    except NotFound as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    except ValueError as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    except ApiError as exc:
        raise ResourceError(str(exc)) from exc
    return company.model_dump(mode="json")


@mcp.resource("dossier://{dossier_id}", title="Dossier", mime_type="application/json")
async def dossier_resource(dossier_id: str, ctx: Context) -> dict[str, Any]:
    """One dossier with its notes."""
    dossier = await app_of(ctx).dossiers.get(dossier_id)
    if dossier is None:
        raise ResourceNotFoundError(f"No dossier {dossier_id!r}.")
    return dossier.model_dump(mode="json")


@mcp.resource("dossiers://{status}", title="Dossiers by status", mime_type="application/json")
async def dossiers_by_status(status: str, ctx: Context) -> list[dict[str, Any]]:
    """Dossier list without notes. `status` is active (open + in_review), all, or one status value.

    A static URI like `dossiers://active` cannot take a Context, so this is a one-variable
    template: the SDK only injects Context into templated resources.
    """
    repo = app_of(ctx).dossiers
    if status == "all":
        items = await repo.list()
    elif status == "active":
        items = [d for d in await repo.list() if d.status in ACTIVE_STATUSES]
    elif status in STATUS_VALUES:
        items = await repo.list(status=status)  # type: ignore[arg-type]
    else:
        raise ResourceNotFoundError(
            f"Unknown status {status!r}; use active, all or one of {sorted(STATUS_VALUES)}."
        )
    return [d.model_dump(mode="json", exclude={"notes"}) for d in items]


@mcp.resource("naf://sections", title="NAF sections", mime_type="application/json")
def naf_sections() -> list[dict[str, str]]:
    """The 21 NAF rév. 2 sections with their division ranges."""
    return naf.sections()


@mcp.resource("naf://{code}", title="NAF code", mime_type="application/json")
def naf_code(code: str) -> dict[str, str | bool]:
    """Section and due-diligence hint for a NAF/APE code such as 62.01Z."""
    described = naf.describe(code)
    if described is None:
        raise ResourceNotFoundError(f"{code!r} is not a NAF code (expected e.g. '62.01Z').")
    return described
