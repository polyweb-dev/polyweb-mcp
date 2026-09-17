"""Unified container supervisor entrypoint running both API and MCP servers."""

import multiprocessing
import signal
import sys
import time
from typing import Any


def _run_api() -> None:
    from freesearch.api import main as api_main  # type: ignore[import-untyped]

    api_main()


def _run_mcp() -> None:
    from freesearch.server import main as mcp_main  # type: ignore[import-untyped]

    mcp_main()


def main() -> None:
    """Run both the REST API and the FastMCP server concurrently."""
    api_proc = multiprocessing.Process(target=_run_api, name="freesearch-api")
    mcp_proc = multiprocessing.Process(target=_run_mcp, name="freesearch-mcp")

    def _shutdown(signum: int, frame: Any) -> None:
        if api_proc.is_alive():
            api_proc.terminate()
        if mcp_proc.is_alive():
            mcp_proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    api_proc.start()
    mcp_proc.start()

    try:
        while api_proc.is_alive() and mcp_proc.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        _shutdown(signal.SIGINT, None)

    if api_proc.is_alive():
        api_proc.terminate()
    if mcp_proc.is_alive():
        mcp_proc.terminate()

    api_proc.join(timeout=5)
    mcp_proc.join(timeout=5)
    exit_code = api_proc.exitcode or mcp_proc.exitcode or 0
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
