"""Runs only when DATABASE_URL points at a reachable PostgreSQL (CI always provides one)."""

from __future__ import annotations

import os

import pytest

from kyb_mcp.db.repo import PostgresDossierRepo

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.environ.get("KYB_TEST_DATABASE_URL"), reason="set KYB_TEST_DATABASE_URL to run"
    ),
]


async def test_postgres_roundtrip() -> None:
    repo = await PostgresDossierRepo.connect(os.environ["KYB_TEST_DATABASE_URL"])
    try:
        created = await repo.create(siren="819489626", company_name="QONTO", note="first")
        assert created.status == "open" and [n.body for n in created.notes] == ["first"]

        fetched = await repo.get(created.id)
        assert fetched is not None and fetched.company_name == "QONTO"

        noted = await repo.add_note(created.id, body="second", kind="system")
        assert noted is not None and [n.kind for n in noted.notes] == ["note", "system"]

        moved = await repo.set_status(created.id, "in_review")
        assert moved is not None and moved.status == "in_review"
        assert created.id in {d.id for d in await repo.list(status="in_review")}
        assert created.id not in {d.id for d in await repo.list(status="open")}

        assert await repo.get("d_missing") is None
        assert await repo.add_note("d_missing", body="x") is None
    finally:
        await repo.aclose()
