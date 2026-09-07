"""Entry point. `uv run kyb-mcp` serves over stdio; `kyb_mcp.http:app` serves over HTTP.

Importing the handler modules is what registers them; keep those imports even though
nothing references them by name.
"""

from __future__ import annotations

import logging
import sys

from kyb_mcp import prompts, resources  # noqa: F401  (registration side effects)
from kyb_mcp.core import mcp
from kyb_mcp.tools import companies, dossiers  # noqa: F401

__all__ = ["main", "mcp"]


def configure_logging() -> None:
    # stdout is the MCP wire on stdio; every log line must go to stderr.
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> None:
    configure_logging()
    mcp.run("stdio")


if __name__ == "__main__":
    main()
