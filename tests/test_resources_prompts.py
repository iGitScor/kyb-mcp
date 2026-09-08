from __future__ import annotations

import json

import pytest
from mcp import Client, MCPError
from mcp.types import PromptReference, ResourceTemplateReference

from tests.conftest import QONTO

pytestmark = pytest.mark.anyio


async def test_templates_are_listed(client: Client) -> None:
    templates = {t.uri_template for t in (await client.list_resource_templates()).resource_templates}
    assert {"company://{siren}", "dossier://{dossier_id}", "dossiers://{status}", "naf://{code}"} <= templates
    statics = {str(r.uri) for r in (await client.list_resources()).resources}
    assert "naf://sections" in statics


async def test_company_resource_is_json(client: Client) -> None:
    read = await client.read_resource(f"company://{QONTO['siren']}")
    content = read.contents[0]
    assert content.mime_type == "application/json"
    assert json.loads(content.text)["name"] == QONTO["nom_complet"]  # type: ignore[union-attr]


async def test_missing_company_is_a_protocol_error(client: Client) -> None:
    with pytest.raises(MCPError):
        await client.read_resource("company://000000000")


async def test_naf_resources(client: Client) -> None:
    read = await client.read_resource("naf://64.19Z")
    body = json.loads(read.contents[0].text)  # type: ignore[union-attr]
    assert body["section"] == "K" and body["enhanced_due_diligence"] is True
    sections = json.loads((await client.read_resource("naf://sections")).contents[0].text)  # type: ignore[union-attr]
    assert len(sections) == 21


async def test_kyb_review_prompt_embeds_the_record(client: Client) -> None:
    prompt = await client.get_prompt("kyb_review", {"siren": QONTO["siren"]})
    assert len(prompt.messages) == 2
    first = prompt.messages[0].content
    assert first.type == "resource" and str(first.resource.uri) == f"company://{QONTO['siren']}"
    assert "KYB" in prompt.messages[1].content.text  # type: ignore[union-attr]


async def test_compare_prompt_validates_count(client: Client) -> None:
    with pytest.raises(MCPError):
        await client.get_prompt("compare_companies", {"sirens": QONTO["siren"]})


async def test_completion_suggests_recent_sirens(client: Client) -> None:
    await client.call_tool("search_companies", {"query": "hero"})
    result = await client.complete(
        ref=PromptReference(type="ref/prompt", name="kyb_review"), argument={"name": "siren", "value": "819"}
    )
    assert result.completion.values == [QONTO["siren"]]
    by_name = await client.complete(
        ref=ResourceTemplateReference(type="ref/resource", uri="company://{siren}"),
        argument={"name": "siren", "value": "hero"},
    )
    assert by_name.completion.values == ["752791061"]


async def test_prompt_errors_keep_their_message(client: Client) -> None:
    with pytest.raises(MCPError, match="9 digits"):
        await client.get_prompt("kyb_review", {"siren": "944"})
    with pytest.raises(MCPError, match="No company"):
        await client.get_prompt("kyb_review", {"siren": "000000000"})
