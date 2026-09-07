"""Dossier tools: the write side of the workbench.

Concepts on show here:
- Lifespan-held store reached through `ctx.request_context.lifespan_context.dossiers`.
- `list_changed` notifications after every mutation so clients refresh `dossier://` resources.
- Elicitation through a `Resolve(...)` dependency (`archive_dossier`).
- Sampling through a `Resolve(...)` dependency (`draft_risk_summary`).
- Progress reporting and cooperative cancellation (`bulk_check`).
"""

from __future__ import annotations

import logging
from typing import Annotated

from mcp.server.mcpserver import Elicit, ElicitationResult, Resolve, Sample
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CreateMessageResult, SamplingMessage, TextContent, ToolAnnotations
from pydantic import BaseModel, Field

from kyb_mcp.api.client import NotFound
from kyb_mcp.api.models import Company, CompanySummary
from kyb_mcp.core import AppContext, Context, mcp
from kyb_mcp.db.repo import Dossier, DossierStatus
from kyb_mcp.naf import describe
from kyb_mcp.tools._errors import tool_errors

log = logging.getLogger(__name__)

WRITES = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
)
DESTRUCTIVE = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False
)

DossierId = Annotated[
    str, Field(description="Dossier id as returned by create_dossier, e.g. 'd_3f9a1c2b7e4d'")
]


async def _notify_dossiers_changed(ctx: Context[AppContext]) -> None:
    # 2026-07-28 clients listen on a subscriptions stream; older clients get a session notification.
    # Each call is a no-op when nobody is listening.
    await ctx.notify_resources_changed()
    await ctx.session.send_resource_list_changed()


async def _require(ctx: Context[AppContext], dossier_id: str) -> Dossier:
    dossier = await ctx.request_context.lifespan_context.dossiers.get(dossier_id)
    if dossier is None:
        raise ToolError(f"No dossier {dossier_id!r}. Use list_dossiers to find the right id.")
    return dossier


@mcp.tool(title="Open a dossier", annotations=WRITES)
@tool_errors
async def create_dossier(
    siren: Annotated[str, Field(description="9-digit SIREN of the company to review")],
    note: Annotated[str | None, Field(description="Why this review was opened")] = None,
    *,
    ctx: Context[AppContext],
) -> Dossier:
    """Open a KYB dossier for a company. Verifies the SIREN exists in the registry first."""
    app = ctx.request_context.lifespan_context
    try:
        company = await app.api.get_company(siren)
    except NotFound as exc:
        raise ToolError(str(exc)) from exc
    dossier = await app.dossiers.create(siren=company.siren, company_name=company.name, note=note)
    await _notify_dossiers_changed(ctx)
    return dossier


@mcp.tool(title="List dossiers", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
async def list_dossiers(
    status: Annotated[DossierStatus | None, Field(description="Filter by status; omit for all")] = None,
    *,
    ctx: Context[AppContext],
) -> list[Dossier]:
    """Dossiers most recently updated first."""
    return await ctx.request_context.lifespan_context.dossiers.list(status=status)


@mcp.tool(title="Get dossier", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
async def get_dossier(dossier_id: DossierId, *, ctx: Context[AppContext]) -> Dossier:
    """One dossier with all its notes."""
    return await _require(ctx, dossier_id)


@mcp.tool(title="Add a note", annotations=WRITES)
async def add_note(
    dossier_id: DossierId,
    body: Annotated[str, Field(min_length=1, max_length=4000, description="Finding, question or decision")],
    *,
    ctx: Context[AppContext],
) -> Dossier:
    """Append a note to a dossier."""
    app = ctx.request_context.lifespan_context
    updated = await app.dossiers.add_note(dossier_id, body=body)
    if updated is None:
        raise ToolError(f"No dossier {dossier_id!r}.")
    await ctx.notify_resource_updated(f"dossier://{dossier_id}")
    return updated


@mcp.tool(title="Set dossier status", annotations=ToolAnnotations(read_only_hint=False, idempotent_hint=True))
async def set_status(
    dossier_id: DossierId,
    status: Annotated[
        DossierStatus,
        Field(description="open, in_review, approved or rejected (archive via archive_dossier)"),
    ],
    reason: Annotated[str | None, Field(description="Recorded as a system note")] = None,
    *,
    ctx: Context[AppContext],
) -> Dossier:
    """Move a dossier through the review workflow."""
    if status == "archived":
        raise ToolError("Use archive_dossier to archive; it asks the user to confirm.")
    app = ctx.request_context.lifespan_context
    updated = await app.dossiers.set_status(dossier_id, status)
    if updated is None:
        raise ToolError(f"No dossier {dossier_id!r}.")
    if reason:
        updated = (
            await app.dossiers.add_note(dossier_id, body=f"Status -> {status}: {reason}", kind="system")
            or updated
        )
    await _notify_dossiers_changed(ctx)
    return updated


# --- Elicitation: ask the user before an irreversible step -------------------------------------


class ArchiveDecision(BaseModel):
    confirm: bool = Field(description="Archive this dossier? It disappears from active lists.")


def confirm_archive(dossier_id: str) -> Elicit[ArchiveDecision]:
    # Deterministic question built only from the tool's arguments: required for multi-round-trip.
    return Elicit(f"Archive dossier {dossier_id}? This hides it from active lists.", ArchiveDecision)


@mcp.tool(title="Archive dossier", annotations=DESTRUCTIVE)
async def archive_dossier(
    dossier_id: DossierId,
    decision: Annotated[ElicitationResult[ArchiveDecision], Resolve(confirm_archive)],
    *,
    ctx: Context[AppContext],
) -> str:
    """Archive a dossier after the user confirms in their client."""
    if decision.action != "accept":
        return f"Archive {decision.action}ed by the user; dossier {dossier_id} unchanged."
    if not decision.data.confirm:
        return f"User chose not to archive; dossier {dossier_id} unchanged."
    app = ctx.request_context.lifespan_context
    updated = await app.dossiers.set_status(dossier_id, "archived")
    if updated is None:
        raise ToolError(f"No dossier {dossier_id!r}.")
    await _notify_dossiers_changed(ctx)
    return f"Dossier {dossier_id} archived."


# --- Sampling: borrow the client's model for a first-draft summary ----------------------------


def _company_brief(company: Company) -> str:
    naf = describe(company.naf_code or "")
    activity = f"{company.naf_code} ({naf['label']})" if naf else company.naf_code or "unknown"
    directors = (
        ", ".join(f"{d.first_names or ''} {d.name} ({d.role})".strip() for d in company.directors)
        or "none listed"
    )
    fin = (
        ", ".join(f"{f.year}: revenue {f.revenue}, net {f.net_income}" for f in company.financials[:3])
        or "none published"
    )
    return (
        f"Name: {company.name}\nSIREN: {company.siren}\nStatus: {company.status}\n"
        f"Created: {company.created_on}\nLegal form code: {company.legal_form_code}\nActivity: {activity}\n"
        f"Head office: {company.hq_address}\nHeadcount band: {company.headcount_band}\n"
        f"Directors: {directors}\nFinancials: {fin}"
    )


async def summarize_with_client_model(dossier_id: str, ctx: Context[AppContext]) -> Sample:
    dossier = await _require(ctx, dossier_id)
    company = await ctx.request_context.lifespan_context.api.get_company(dossier.siren)
    notes = "\n".join(f"- [{n.kind}] {n.body}" for n in dossier.notes) or "- (no notes yet)"
    prompt = (
        "You are assisting a KYB analyst at a French fintech. Write a 5-line risk summary of this "
        "company: what it is, how long it has existed, who runs it, financial signal, and what "
        "document to request next. Be factual; say 'unknown' when data is missing.\n\n"
        f"{_company_brief(company)}\n\nAnalyst notes so far:\n{notes}"
    )
    return Sample(
        [SamplingMessage(role="user", content=TextContent(type="text", text=prompt))],
        max_tokens=400,
        system_prompt=(
            "Answer in the analyst's language (French if the notes are French). Plain text, no markdown."
        ),
    )


@mcp.tool(title="Draft risk summary", annotations=WRITES)
@tool_errors
async def draft_risk_summary(
    dossier_id: DossierId,
    completion: Annotated[CreateMessageResult, Resolve(summarize_with_client_model)],
    *,
    ctx: Context[AppContext],
) -> Dossier:
    """Ask the client's own model for a first-draft risk summary and store it as an AI note.

    Requires a client that supports sampling. The draft is a starting point for the analyst,
    never a decision.
    """
    text = completion.content.text if completion.content.type == "text" else str(completion.content)
    app = ctx.request_context.lifespan_context
    updated = await app.dossiers.add_note(dossier_id, body=text.strip(), kind="ai_summary")
    if updated is None:
        raise ToolError(f"No dossier {dossier_id!r}.")
    await ctx.notify_resource_updated(f"dossier://{dossier_id}")
    return updated


# --- Progress + cancellation -----------------------------------------------------------------


class BulkCheckResult(BaseModel):
    found: list[CompanySummary]
    missing: list[str] = Field(description="SIRENs not in the registry")
    failed: list[str] = Field(description="SIRENs that errored (rate limit, timeout); retry later")


@mcp.tool(title="Bulk check SIRENs", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))
async def bulk_check(
    sirens: Annotated[list[str], Field(min_length=1, max_length=50, description="Up to 50 SIRENs")],
    *,
    ctx: Context[AppContext],
) -> BulkCheckResult:
    """Look up many SIRENs at once, reporting progress. Respects the registry rate limit (~5/s)."""
    api = ctx.request_context.lifespan_context.api
    result = BulkCheckResult(found=[], missing=[], failed=[])
    total = len(sirens)
    for done, raw in enumerate(sirens, start=1):
        # No try/except around the await for cancellation: if the client cancels, the task group
        # cancels this loop and the partial result is discarded, which is what the caller expects.
        try:
            company = await api.get_company(raw)
        except NotFound:
            result.missing.append(raw)
        except ValueError:
            result.missing.append(raw)
        except Exception as exc:  # ApiError or unexpected upstream failure: record and continue
            log.warning("bulk_check: %s failed: %s", raw, exc)
            result.failed.append(raw)
        else:
            result.found.append(
                CompanySummary(**company.model_dump(include=set(CompanySummary.model_fields)))
            )
        await ctx.report_progress(done, total=total, message=f"Checked {raw}")
    return result
