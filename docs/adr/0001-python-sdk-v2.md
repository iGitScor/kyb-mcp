# ADR 0001: Build on the MCP Python SDK v2 (protocol 2026-07-28)

Date: 2026-09-08. Status: accepted.

## Context

The official `mcp` package moved to 2.x in 2026. Compared with the 1.x `FastMCP` era it:

- renames `FastMCP` to `MCPServer` (`mcp.server.fastmcp` is removed, not deprecated);
- ships an in-memory `mcp.Client(server)` for tests;
- implements protocol revision **2026-07-28**, which removes server-initiated requests. A tool
  that needs user input (elicitation) or the client's model (sampling) returns an
  `InputRequiredResult`; the client answers and retries. The SDK hides this behind
  `Resolve(...)` parameters returning `Elicit(...)` / `Sample(...)`, and keeps the legacy
  push path for 2025-era clients from the same code;
- deprecates protocol-level logging (`ctx.info`) in favour of stdlib `logging`, and deprecates
  standalone sampling and roots.

Most tutorials online still show 1.x code.

## Decision

Target `mcp>=2.1` and the 2026-07-28 semantics exclusively:

- handlers are plain decorated functions; schemas come from type hints;
- elicitation and sampling go through `Resolve` dependencies, never `ctx.elicit` /
  `ctx.session.create_message`;
- all logging is stdlib `logging` to stderr (stdout is the stdio wire);
- change notifications call both `ctx.notify_*` (2026 subscription streams) and
  `ctx.session.send_*_list_changed()` (legacy sessions), each a no-op when nobody listens.

## Consequences

- Multi-round-trip tools seal state in a per-process key. Any multi-instance HTTP deployment
  must set `KYB_REQUEST_STATE_KEY` (see ADR 0003).
- Sampling depends on the client declaring the capability; the tool fails cleanly (`-32021`)
  otherwise, and the MCP Inspector is the reference client for it.
- Reference: `py.sdk.modelcontextprotocol.io/v2`, not blog posts.
