"""Prompts: review templates the user picks from their client, plus argument completion."""

from __future__ import annotations

import json
from typing import Annotated

from mcp.server.mcpserver import Message, UserMessage
from mcp.types import (
    Completion,
    CompletionArgument,
    CompletionContext,
    EmbeddedResource,
    PromptReference,
    ResourceTemplateReference,
    TextResourceContents,
)
from pydantic import Field

from kyb_mcp import core
from kyb_mcp.api.client import normalize_siren
from kyb_mcp.core import Context, app_of, mcp

REVIEW_CHECKLIST = """\
Run a KYB review of the company above for a French payment institution onboarding. Cover:
1. Identity: legal name, SIREN, legal form, creation date, head office. Flag anything inconsistent.
2. Status: is it active? Any recent creation (< 12 months) or dormant signals?
3. People: directors and roles; note legal-person directors that need their own lookup.
4. Activity: NAF code and section; say whether it calls for enhanced due diligence.
5. Financials: latest published revenue and net income, or state that none are published.
6. Decision: approve / request documents / escalate, with the exact documents to request
   (Kbis < 3 months, beneficial-owner declaration, ID of legal representative, proof of address).
Answer in French. Be concise and factual; mark unknowns as such.
"""


async def _company_block(siren: str, ctx: Context) -> EmbeddedResource:
    company = await app_of(ctx).api.get_company(siren)
    return EmbeddedResource(
        resource=TextResourceContents(
            uri=f"company://{company.siren}",
            mime_type="application/json",
            text=json.dumps(company.model_dump(mode="json"), ensure_ascii=False, indent=2),
        )
    )


@mcp.prompt(title="KYB review")
async def kyb_review(
    siren: Annotated[str, Field(description="9-digit SIREN of the company to review")],
    ctx: Context,
) -> list[Message]:
    """Structured KYB review of one company, with the registry record attached."""
    return [UserMessage(await _company_block(siren, ctx)), UserMessage(REVIEW_CHECKLIST)]


@mcp.prompt(title="Compare companies")
async def compare_companies(
    sirens: Annotated[str, Field(description="Comma-separated SIRENs, 2 to 5")],
    ctx: Context,
) -> list[Message]:
    """Side-by-side comparison of several companies (size, age, activity, financial signal)."""
    ids = [normalize_siren(s) for s in sirens.split(",") if s.strip()]
    if not 2 <= len(ids) <= 5:
        raise ValueError("Give between 2 and 5 SIRENs, comma-separated.")
    messages: list[Message] = [UserMessage(await _company_block(s, ctx)) for s in ids]
    messages.append(
        UserMessage(
            "Compare the companies above in a table: legal form, age, activity, head office, headcount band, "
            "latest revenue and net income, directors in common. Then rank them by KYB risk with one line of "
            "justification each. Answer in French."
        )
    )
    return messages


@mcp.completion()
async def complete(
    ref: PromptReference | ResourceTemplateReference,
    argument: CompletionArgument,
    context: CompletionContext | None,
) -> Completion | None:
    """Suggest SIRENs the server has seen recently (search hits, opened companies)."""
    wants_siren = (isinstance(ref, PromptReference) and argument.name in {"siren", "sirens"}) or (
        isinstance(ref, ResourceTemplateReference) and ref.uri == "company://{siren}"
    )
    if not wants_siren or core.current is None:
        return None
    typed = argument.value.strip().lower()
    recent = core.current.api.recent
    values = [siren for siren, name in reversed(recent.items()) if typed in siren or typed in name.lower()]
    return Completion(values=values[:20], has_more=len(values) > 20)
