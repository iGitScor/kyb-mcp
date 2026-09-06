# Security

## Data

The server reads **public** registry data (SIRENE / RNE via recherche-entreprises.api.gouv.fr).
It deliberately drops directors' birth dates before anything leaves the process, and never logs
full upstream payloads. Dossier notes are analyst-written free text stored in your own database.

## Transport

- stdio: the server trusts its parent process (Claude Code, Inspector). No network exposure.
- HTTP: DNS-rebinding protection is on unless `KYB_ALLOWED_HOSTS` or a trusted proxy is
  configured. `/healthz` is intentionally unauthenticated and returns no data.
- The HTTP endpoint has no authentication yet. Do not expose write tools on a public URL
  without the OAuth resource-server layer (planned; see README "Next steps").

## Multi-round-trip state

Elicitation and sampling seal per-call state with `KYB_REQUEST_STATE_KEY` (AES-GCM, 10 min
TTL, bound to the server name). Rotate by listing several keys; the first seals, all unseal.

## Reporting

Open a private security advisory on GitHub or email the maintainer. Please do not file public
issues for vulnerabilities.
