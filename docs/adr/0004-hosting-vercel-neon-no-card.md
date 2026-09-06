# ADR 0004: Host on Vercel Hobby with Neon PostgreSQL, personal accounts, no credit card

Date: 2026-09-08. Status: accepted.

## Context

Constraints: personal accounts only, no credit card anywhere, and a deployment that reads well
on a senior résumé. Findings (September 2026):

| Option | Verdict |
|---|---|
| Google Cloud Run | Best container platform, but needs a billing account with a card |
| Cloudflare Workers | Excellent for TypeScript MCP; Python Workers still beta, `mcp` package unproven |
| Hugging Face Spaces (Docker) | Now requires a paid plan |
| Koyeb | Free compute tier removed |
| Render free | Works, but sleeps after 15 min and takes about a minute to wake |
| Vercel Hobby | Python ASGI zero-config, lifespan + streaming, 300 s max, no card, always on |
| Supabase | Database only (Edge Functions are Deno); free project pauses after a week idle |
| Neon | Free Postgres, no card, autosuspends after 5 min with sub-second wake |

## Decision

- Runtime: **Vercel Hobby** on a personal account, entrypoint `kyb_mcp.http:app`.
- Database: **Neon** free tier, `DATABASE_URL` as a Vercel environment variable.
- The Docker image is still built and published to GHCR on tags, so the same artifact can run
  on any container host later (Render, Cloud Run) without code changes.

## Consequences

- Hobby is for personal, non-commercial use; the project stays under the personal account.
- Vercel is serverless: `stateless_http=True` (ADR 0003) and `KYB_REQUEST_STATE_KEY` are
  required, and the psycopg pool is small (`max_size=5`) because each instance has its own.
