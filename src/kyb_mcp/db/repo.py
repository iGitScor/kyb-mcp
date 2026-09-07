"""Dossier store.

`DossierRepo` is the port the MCP tools depend on. Two adapters implement it:

- `InMemoryDossierRepo`: default when `DATABASE_URL` is unset. Zero setup, state lives for the
  life of the process. Right for `uv run kyb-mcp` on a laptop and for unit tests.
- `PostgresDossierRepo`: production adapter over a psycopg 3 async pool. Same behaviour,
  durable. Exercised by tests/test_repo_postgres.py when `DATABASE_URL` is set (CI always sets it).

The split is documented in docs/adr/0002-postgres-behind-a-port.md.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from importlib import resources
from typing import Literal, Protocol

from pydantic import BaseModel, Field

DossierStatus = Literal["open", "in_review", "approved", "rejected", "archived"]
NoteKind = Literal["note", "ai_summary", "system"]

ACTIVE_STATUSES: tuple[DossierStatus, ...] = ("open", "in_review")
STATUS_VALUES: frozenset[str] = frozenset({"open", "in_review", "approved", "rejected", "archived"})


class Note(BaseModel):
    id: str
    kind: NoteKind = "note"
    body: str
    created_at: datetime


class Dossier(BaseModel):
    """A company under KYB review, with its running notes."""

    id: str = Field(description="Opaque dossier id, e.g. 'd_3f9a1c2b7e4d'")
    siren: str
    company_name: str
    status: DossierStatus
    created_at: datetime
    updated_at: datetime
    notes: list[Note] = Field(default_factory=list, description="Oldest first")


class DossierRepo(Protocol):
    async def create(self, *, siren: str, company_name: str, note: str | None = None) -> Dossier: ...
    async def get(self, dossier_id: str) -> Dossier | None: ...
    async def list(self, *, status: DossierStatus | None = None) -> list[Dossier]: ...
    async def add_note(self, dossier_id: str, *, body: str, kind: NoteKind = "note") -> Dossier | None: ...
    async def set_status(self, dossier_id: str, status: DossierStatus) -> Dossier | None: ...
    async def aclose(self) -> None: ...


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now() -> datetime:
    return datetime.now(UTC)


class InMemoryDossierRepo:
    def __init__(self) -> None:
        self._items: dict[str, Dossier] = {}

    async def create(self, *, siren: str, company_name: str, note: str | None = None) -> Dossier:
        now = _now()
        dossier = Dossier(
            id=_new_id("d"),
            siren=siren,
            company_name=company_name,
            status="open",
            created_at=now,
            updated_at=now,
        )
        if note:
            dossier.notes.append(Note(id=_new_id("n"), body=note, created_at=now))
        self._items[dossier.id] = dossier
        return dossier

    async def get(self, dossier_id: str) -> Dossier | None:
        found = self._items.get(dossier_id)
        return found.model_copy(deep=True) if found else None

    async def list(self, *, status: DossierStatus | None = None) -> list[Dossier]:
        items = [d for d in self._items.values() if status is None or d.status == status]
        return sorted((d.model_copy(deep=True) for d in items), key=lambda d: d.updated_at, reverse=True)

    async def add_note(self, dossier_id: str, *, body: str, kind: NoteKind = "note") -> Dossier | None:
        dossier = self._items.get(dossier_id)
        if dossier is None:
            return None
        now = _now()
        dossier.notes.append(Note(id=_new_id("n"), kind=kind, body=body, created_at=now))
        dossier.updated_at = now
        return dossier.model_copy(deep=True)

    async def set_status(self, dossier_id: str, status: DossierStatus) -> Dossier | None:
        dossier = self._items.get(dossier_id)
        if dossier is None:
            return None
        dossier.status = status
        dossier.updated_at = _now()
        return dossier.model_copy(deep=True)

    async def aclose(self) -> None:
        return None


class PostgresDossierRepo:
    """psycopg 3 adapter. Use `await PostgresDossierRepo.connect(url)`; it applies schema.sql."""

    def __init__(self, pool: object) -> None:
        from psycopg_pool import AsyncConnectionPool

        assert isinstance(pool, AsyncConnectionPool)
        self._pool: AsyncConnectionPool = pool

    @classmethod
    async def connect(cls, database_url: str, *, min_size: int = 1, max_size: int = 5) -> PostgresDossierRepo:
        from psycopg_pool import AsyncConnectionPool

        pool = AsyncConnectionPool(database_url, min_size=min_size, max_size=max_size, open=False)
        await pool.open(wait=True, timeout=30)
        schema = resources.files("kyb_mcp.db").joinpath("schema.sql").read_text(encoding="utf-8")
        async with pool.connection() as conn:
            await conn.execute(schema)  # type: ignore[arg-type]
        return cls(pool)

    async def aclose(self) -> None:
        await self._pool.close()

    async def create(self, *, siren: str, company_name: str, note: str | None = None) -> Dossier:
        dossier_id = _new_id("d")
        async with self._pool.connection() as conn, conn.transaction():
            await conn.execute(
                "INSERT INTO dossiers (id, siren, company_name, status) VALUES (%s, %s, %s, 'open')",
                (dossier_id, siren, company_name),
            )
            if note:
                await conn.execute(
                    "INSERT INTO dossier_notes (id, dossier_id, kind, body) VALUES (%s, %s, 'note', %s)",
                    (_new_id("n"), dossier_id, note),
                )
        created = await self.get(dossier_id)
        assert created is not None
        return created

    async def get(self, dossier_id: str) -> Dossier | None:
        from psycopg.rows import dict_row

        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM dossiers WHERE id = %s", (dossier_id,))
            row = await cur.fetchone()
            if row is None:
                return None
            await cur.execute(
                "SELECT id, kind, body, created_at FROM dossier_notes "
                "WHERE dossier_id = %s ORDER BY created_at, id",
                (dossier_id,),
            )
            notes = [Note(**n) for n in await cur.fetchall()]
        return Dossier(**row, notes=notes)

    async def list(self, *, status: DossierStatus | None = None) -> list[Dossier]:
        from psycopg.rows import dict_row

        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            if status is None:
                await cur.execute("SELECT * FROM dossiers ORDER BY updated_at DESC")
            else:
                await cur.execute(
                    "SELECT * FROM dossiers WHERE status = %s ORDER BY updated_at DESC", (status,)
                )
            rows = await cur.fetchall()
            if not rows:
                return []
            ids = [r["id"] for r in rows]
            await cur.execute(
                "SELECT id, dossier_id, kind, body, created_at FROM dossier_notes "
                "WHERE dossier_id = ANY(%s) ORDER BY created_at, id",
                (ids,),
            )
            notes_by_dossier: dict[str, list[Note]] = {}
            for n in await cur.fetchall():
                dossier_id = n.pop("dossier_id")
                notes_by_dossier.setdefault(dossier_id, []).append(Note(**n))
        return [Dossier(**row, notes=notes_by_dossier.get(row["id"], [])) for row in rows]

    async def add_note(self, dossier_id: str, *, body: str, kind: NoteKind = "note") -> Dossier | None:
        async with self._pool.connection() as conn, conn.transaction():
            cur = await conn.execute("UPDATE dossiers SET updated_at = now() WHERE id = %s", (dossier_id,))
            if cur.rowcount == 0:
                return None
            await conn.execute(
                "INSERT INTO dossier_notes (id, dossier_id, kind, body) VALUES (%s, %s, %s, %s)",
                (_new_id("n"), dossier_id, kind, body),
            )
        return await self.get(dossier_id)

    async def set_status(self, dossier_id: str, status: DossierStatus) -> Dossier | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE dossiers SET status = %s, updated_at = now() WHERE id = %s", (status, dossier_id)
            )
            if cur.rowcount == 0:
                return None
        return await self.get(dossier_id)
