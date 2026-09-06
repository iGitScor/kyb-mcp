# Contributing

```bash
uv sync                      # deps + dev tools
uv run pytest                # unit tests, offline (respx mocks the registry API)
docker compose up -d db      # PostgreSQL for the integration test
KYB_TEST_DATABASE_URL=postgresql://kyb:kyb@localhost:5433/kyb uv run pytest tests/test_repo_postgres.py
uv run ruff check && uv run ruff format --check && uv run pyright
```

Conventions:

- Tools raise `ToolError` for anything the model could fix by calling again; everything else
  is a crash and is logged with a traceback.
- Never `print()`: stdout is the stdio transport. Use `logging`.
- A decision worth arguing about gets an ADR in `docs/adr/`.
