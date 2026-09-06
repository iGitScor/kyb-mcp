# kyb-mcp

A **KYB (Know Your Business) workbench** exposed over the [Model Context Protocol](https://modelcontextprotocol.io).
It searches the French company registry (SIRENE / RNE through the free
[recherche-entreprises.api.gouv.fr](https://recherche-entreprises.api.gouv.fr/docs/) API), keeps review
dossiers in PostgreSQL, and exposes all of it to Claude Code, claude.ai or any MCP client.

Built on the **MCP Python SDK v2** (protocol revision 2026-07-28) as a learning project that uses every
protocol primitive on purpose: tools, resources, prompts, completions, elicitation, sampling, progress,
change notifications, stdio and Streamable HTTP.

```
┌────────────┐  stdio / Streamable HTTP  ┌──────────────────────────┐   https   ┌────────────────────────┐
│ MCP client │ ◄───────────────────────► │ kyb-mcp (MCPServer)      │ ────────► │ recherche-entreprises  │
│ Claude Code│   tools · resources ·     │  tools/  resources.py    │ 5 req/s   │ .api.gouv.fr (public)  │
│ claude.ai  │   prompts · completions   │  prompts.py  core.py     │           └────────────────────────┘
│ Inspector  │   elicit · sample ·       │  db/repo.py (port)       │   SQL     ┌────────────────────────┐
└────────────┘   progress · notify       │   ├ InMemoryDossierRepo  │ ────────► │ PostgreSQL             │
                                         │   └ PostgresDossierRepo  │           │ (Compose local / Neon) │
                                         └──────────────────────────┘           └────────────────────────┘
```

## Quick start

```bash
uv sync
uv run kyb-mcp                     # stdio server, in-memory dossiers, no config needed
uv run mcp dev src/kyb_mcp/server.py   # same server inside the MCP Inspector (needs Node)
```

Register it in Claude Code (stdio):

```bash
claude mcp add kyb -- uv run --directory /absolute/path/to/kyb-mcp kyb-mcp
```

Then try: *"Find the company Qonto, open a dossier for it and run the KYB review prompt."*

## What the server exposes

| Primitive | Name | What it teaches |
|---|---|---|
| Tool | `search_companies`, `get_company`, `find_by_person` | Typed inputs (`Annotated` + `Field`), structured output from pydantic models, `ToolError` for model-recoverable failures, `read_only_hint` |
| Tool | `create_dossier`, `add_note`, `set_status`, `list_dossiers`, `get_dossier` | Lifespan-held store, `list_changed` / `resource_updated` notifications, mutation annotations |
| Tool | `archive_dossier` | **Elicitation** through a `Resolve(...)` dependency returning `Elicit(...)`; accept / decline / cancel branches |
| Tool | `draft_risk_summary` | **Sampling**: `Resolve(...)` returning `Sample(...)`, result stored as an `ai_summary` note |
| Tool | `bulk_check` | `ctx.report_progress`, cooperative cancellation, rate-limit-aware loops |
| Resource | `company://{siren}`, `dossier://{id}`, `dossiers://{status}`, `naf://{code}`, `naf://sections` | URI templates, `application/json` payloads, `ResourceNotFoundError` |
| Prompt | `kyb_review`, `compare_companies` | Multi-message prompts with an `EmbeddedResource` attached |
| Completion | `siren` arguments | Server-side autocomplete fed by recently seen companies |

All tool calls to the registry go through one `httpx.AsyncClient` with a token bucket (5 req/s, the public
limit is 7) and a 60 s cache. Directors' birth dates are dropped before anything leaves the process.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | unset → in-memory | PostgreSQL DSN for durable dossiers |
| `KYB_ALLOWED_HOSTS` | localhost only | Host allowlist for HTTP behind a real hostname (comma-separated) |
| `KYB_ALLOWED_ORIGINS` | none | Browser origins (CORS twin) |
| `KYB_REQUEST_STATE_KEY` | per-process random | Shared key for multi-instance HTTP (elicitation / sampling retries) |
| `KYB_API_RATE_PER_SECOND` | 5 | Upstream rate limit |
| `VERCEL` / `KYB_BEHIND_TRUSTED_PROXY` | unset | Disable DNS-rebinding checks when the proxy owns `Host` |

## Streamable HTTP, Docker, Compose

```bash
uv run uvicorn kyb_mcp.http:app --port 8000          # http://127.0.0.1:8000/mcp  (+ /healthz)
claude mcp add --transport http kyb-http http://127.0.0.1:8000/mcp

docker compose up -d --build                         # PostgreSQL 16 (host port 5433) + server on :8000
```

Tagged releases publish `ghcr.io/igitscor/kyb-mcp` with an SBOM and provenance attestation
(`.github/workflows/image.yml`).

## Deploy (Vercel Hobby + Neon, no credit card)

1. `npm i -g vercel@latest && vercel login` with your **personal** account, then `vercel link`.
2. Create a free Neon project and add its DSN: `vercel env add DATABASE_URL production`.
3. `vercel env add KYB_REQUEST_STATE_KEY production` with `python -c "import secrets; print(secrets.token_hex(32))"`.
4. `vercel deploy --prod`. The entrypoint is `kyb_mcp.http:app` (see `[tool.vercel]` in `pyproject.toml`).
5. Point Claude Code at `https://<project>.vercel.app/mcp`, or add it as a claude.ai custom connector.

Why this host and database: [ADR 0004](docs/adr/0004-hosting-vercel-neon-no-card.md).

## Development

```bash
uv run pytest                                        # 23 offline tests (respx mocks the registry)
docker compose up -d db && KYB_TEST_DATABASE_URL=postgresql://kyb:kyb@localhost:5433/kyb uv run pytest tests/test_repo_postgres.py
uv run ruff check && uv run ruff format --check && uv run pyright
```

CI runs the same on every push with a PostgreSQL service container, then builds the Docker image and
smoke-tests `/healthz` and `server/discover`.

## Design notes

- [ADR 0001](docs/adr/0001-python-sdk-v2.md): why SDK v2 / protocol 2026-07-28, and what changed from FastMCP.
- [ADR 0002](docs/adr/0002-postgres-behind-a-port.md): PostgreSQL behind a repository port, in-memory adapter for zero-setup runs.
- [ADR 0003](docs/adr/0003-stateless-streamable-http.md): stateless HTTP, DNS-rebinding protection, shared request-state key.
- [ADR 0004](docs/adr/0004-hosting-vercel-neon-no-card.md): hosting comparison and the no-card constraint.
- [SECURITY.md](SECURITY.md): data handling, transport exposure, what is not protected yet.

## Learning path (how this repo was built)

| Stage | Files | Concepts |
|---|---|---|
| 1 | `api/`, `tools/companies.py` | stdio, `tools/list`, `tools/call`, structured output, errors |
| 2 | `resources.py`, `prompts.py` | URI templates, MIME types, embedded resources, completions |
| 3 | `db/`, `tools/dossiers.py` | lifespan, typed `Context[AppContext]`, change notifications |
| 4 | `tools/dossiers.py` | elicitation and sampling via `Resolve`, progress, cancellation |
| 5 | `tests/` | in-memory `Client(mcp)`, callbacks as capability declarations |
| 6 | `http.py`, `Dockerfile`, `compose.yaml` | Streamable HTTP, transport security, containers |
| 7 | `vercel.json`, `pyproject.toml [tool.vercel]` | serverless deployment, Neon |

## Next steps

- OAuth 2.1 resource server (`AuthSettings` + `TokenVerifier`) before exposing write tools publicly.
- OpenTelemetry exporter: the SDK already emits a span per request; add `opentelemetry-sdk` and an OTLP endpoint.
- Publish to the official MCP Registry with `mcp-publisher`.

## License

MIT. Registry data is public data from INSEE / INPI under the Licence Ouverte 2.0.
