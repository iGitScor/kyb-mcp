from __future__ import annotations

import pytest
from mcp import Client
from mcp.client.context import ClientRequestContext
from mcp.types import (
    CreateMessageRequestParams,
    CreateMessageResult,
    ElicitRequestParams,
    ElicitResult,
    TextContent,
)

from tests.conftest import HERO, QONTO

pytestmark = pytest.mark.anyio


async def _open(client: Client, siren: str = QONTO["siren"]) -> str:
    result = await client.call_tool("create_dossier", {"siren": siren, "note": "onboarding request"})
    assert result.is_error is False, result.content
    return (result.structured_content or {})["id"]


async def test_dossier_lifecycle(client: Client) -> None:
    dossier_id = await _open(client)
    listed = await client.call_tool("list_dossiers", {"status": "open"})
    assert [d["id"] for d in (listed.structured_content or {})["result"]] == [dossier_id]

    noted = await client.call_tool("add_note", {"dossier_id": dossier_id, "body": "Kbis received"})
    assert [n["body"] for n in (noted.structured_content or {})["notes"]] == [
        "onboarding request",
        "Kbis received",
    ]

    moved = await client.call_tool(
        "set_status", {"dossier_id": dossier_id, "status": "in_review", "reason": "docs ok"}
    )
    body = moved.structured_content or {}
    assert body["status"] == "in_review" and body["notes"][-1]["kind"] == "system"

    via_resource = await client.read_resource(f"dossier://{dossier_id}")
    assert dossier_id in via_resource.contents[0].text  # type: ignore[union-attr]
    active = await client.read_resource("dossiers://active")
    assert dossier_id in active.contents[0].text  # type: ignore[union-attr]


async def test_create_dossier_requires_a_real_company(client: Client) -> None:
    result = await client.call_tool("create_dossier", {"siren": "000000000"})
    assert result.is_error is True and "No company" in result.content[0].text  # type: ignore[union-attr]


async def test_set_status_refuses_archive_shortcut(client: Client) -> None:
    dossier_id = await _open(client)
    result = await client.call_tool("set_status", {"dossier_id": dossier_id, "status": "archived"})
    assert result.is_error is True and "archive_dossier" in result.content[0].text  # type: ignore[union-attr]


async def test_archive_asks_the_user_and_honours_accept() -> None:
    from kyb_mcp.server import mcp

    questions: list[str] = []

    async def confirm(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        questions.append(params.message)
        return ElicitResult(action="accept", content={"confirm": True})

    async with Client(mcp, elicitation_callback=confirm, raise_exceptions=True) as client:
        dossier_id = await _open(client)
        result = await client.call_tool("archive_dossier", {"dossier_id": dossier_id})
        assert result.is_error is False and "archived" in result.content[0].text  # type: ignore[union-attr]
        assert questions and dossier_id in questions[0]
        archived = await client.call_tool("get_dossier", {"dossier_id": dossier_id})
        assert (archived.structured_content or {})["status"] == "archived"


async def test_archive_decline_changes_nothing() -> None:
    from kyb_mcp.server import mcp

    async def decline(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action="decline")

    async with Client(mcp, elicitation_callback=decline, raise_exceptions=True) as client:
        dossier_id = await _open(client)
        result = await client.call_tool("archive_dossier", {"dossier_id": dossier_id})
        assert result.is_error is False and "unchanged" in result.content[0].text  # type: ignore[union-attr]
        still = await client.call_tool("get_dossier", {"dossier_id": dossier_id})
        assert (still.structured_content or {})["status"] == "open"


async def test_draft_summary_uses_the_client_model() -> None:
    from kyb_mcp.server import mcp

    seen_prompts: list[str] = []

    async def fake_model(
        context: ClientRequestContext, params: CreateMessageRequestParams
    ) -> CreateMessageResult:
        first = params.messages[0].content
        seen_prompts.append(first.text if not isinstance(first, list) and first.type == "text" else "")
        return CreateMessageResult(
            role="assistant",
            content=TextContent(type="text", text="Société active depuis 2016, pas de signal négatif."),
            model="fake-model",
            stop_reason="endTurn",
        )

    async with Client(mcp, sampling_callback=fake_model, raise_exceptions=True) as client:
        dossier_id = await _open(client)
        result = await client.call_tool("draft_risk_summary", {"dossier_id": dossier_id})
        assert result.is_error is False, result.content
        notes = (result.structured_content or {})["notes"]
        assert notes[-1]["kind"] == "ai_summary" and "Société active" in notes[-1]["body"]
        assert QONTO["nom_complet"] in seen_prompts[0] and "onboarding request" in seen_prompts[0]


async def test_bulk_check_reports_progress(client: Client) -> None:
    ticks: list[tuple[float, float | None, str | None]] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        ticks.append((progress, total, message))

    result = await client.call_tool(
        "bulk_check",
        {"sirens": [HERO["siren"], "000000000", "not-a-siren", QONTO["siren"]]},
        progress_callback=on_progress,
    )
    body = result.structured_content or {}
    assert [c["siren"] for c in body["found"]] == [HERO["siren"], QONTO["siren"]]
    assert body["missing"] == ["000000000", "not-a-siren"] and body["failed"] == []
    assert [t[0] for t in ticks] == [1, 2, 3, 4] and ticks[-1][1] == 4
