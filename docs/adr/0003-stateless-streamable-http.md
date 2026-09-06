# ADR 0003: Streamable HTTP in stateless mode, DNS-rebinding protection on by default

Date: 2026-09-08. Status: accepted.

## Context

The remote transport is Streamable HTTP. On the 2026-07-28 protocol every request is a
self-contained POST: there is no session id and nothing for a load balancer to be sticky on.
Pre-2026 clients still open a session unless the server runs `stateless_http=True`. The target
host (Vercel Functions) starts and stops instances freely, so per-instance memory cannot be
relied on between requests.

The SDK also arms DNS-rebinding protection: without an allowlist, only requests addressed to
localhost are accepted (`421` otherwise).

## Decision

- `streamable_http_app(stateless_http=True)`: modern clients are stateless anyway; legacy
  clients lose only the server-to-client back-channel, which this server does not use.
- `KYB_ALLOWED_HOSTS` sets the Host allowlist for a real hostname. When `VERCEL` is set the
  platform owns the Host header, so the check is switched off there (`behind_trusted_proxy`).
- `/healthz` is a custom route: unauthenticated by design, carries no data.
- `KYB_REQUEST_STATE_KEY` must be shared by all instances so multi-round-trip tools
  (elicitation, sampling) survive a retry landing on a different instance.

## Consequences

- No resumability / event store: a modern exchange is one POST, one response.
- Change notifications across instances would need a shared `SubscriptionBus`; not needed
  for a single-tenant workbench, documented as a known limit.
