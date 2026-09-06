"""Read-only tools over the company registry."""

from __future__ import annotations

from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from kyb_mcp.api.models import Company, SearchResult
from kyb_mcp.core import AppContext, Context, mcp
from kyb_mcp.tools._errors import tool_errors

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True)

Siren = Annotated[str, Field(description="9-digit SIREN, spaces allowed", examples=["752791061"])]


@mcp.tool(title="Search companies", annotations=READ_ONLY)
@tool_errors
async def search_companies(
    query: Annotated[
        str, Field(min_length=2, description="Company name, brand, SIREN/SIRET or address words")
    ],
    postal_code: Annotated[
        str | None, Field(pattern=r"^\d{5}$", description="Filter on a 5-digit postal code")
    ] = None,
    department: Annotated[str | None, Field(description="Département code, e.g. '75' or '2A'")] = None,
    naf_code: Annotated[str | None, Field(description="Main activity code, e.g. '62.01Z'")] = None,
    only_active: Annotated[bool, Field(description="Exclude ceased companies")] = True,
    page: Annotated[int, Field(ge=1)] = 1,
    per_page: Annotated[int, Field(ge=1, le=25)] = 10,
    *,
    ctx: Context[AppContext],
) -> SearchResult:
    """Search French companies, associations and public bodies in the official registry (SIRENE/RNE).

    Returns a page of summaries with SIREN, status, activity, head office and headcount band.
    Use `get_company` on a SIREN for directors and financials.
    """
    api = ctx.request_context.lifespan_context.api
    return await api.search(
        page=page,
        per_page=per_page,
        q=query,
        code_postal=postal_code,
        departement=department,
        activite_principale=naf_code,
        etat_administratif="A" if only_active else None,
    )


@mcp.tool(title="Get company", annotations=READ_ONLY)
@tool_errors
async def get_company(siren: Siren, *, ctx: Context[AppContext]) -> Company:
    """Full registry record for one company: identity, head office, directors, latest financials."""
    return await ctx.request_context.lifespan_context.api.get_company(siren)


@mcp.tool(title="Find companies by person", annotations=READ_ONLY)
@tool_errors
async def find_by_person(
    last_name: Annotated[str, Field(min_length=2, description="Director's family name")],
    first_names: Annotated[str | None, Field(description="Given name(s) to narrow the match")] = None,
    only_active: bool = True,
    page: Annotated[int, Field(ge=1)] = 1,
    *,
    ctx: Context[AppContext],
) -> SearchResult:
    """Companies where a person is listed as a director or elected official (dirigeant / élu).

    Registry matching is by name only; a common name returns homonyms. Treat hits as leads to
    confirm, never as proof of identity.
    """
    api = ctx.request_context.lifespan_context.api
    return await api.search(
        page=page,
        per_page=10,
        nom_personne=last_name,
        prenoms_personne=first_names,
        etat_administratif="A" if only_active else None,
    )
