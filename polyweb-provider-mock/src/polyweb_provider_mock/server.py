"""``polyweb-provider-mock``: serve the mock with uvicorn."""

import argparse
import dataclasses
from collections.abc import Sequence
from pathlib import Path

from polyweb_provider_mock.app import create_app
from polyweb_provider_mock.settings import MockSettings

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> None:
    """Serve every impersonated provider and the ``/_mock`` admin API on one port.

    Defaults come from ``POLYWEB_PROVIDER_MOCK_HOST`` (127.0.0.1),
    ``POLYWEB_PROVIDER_MOCK_PORT`` (8212), and ``POLYWEB_PROVIDER_MOCK_DB``.
    """

    import uvicorn

    settings = MockSettings.from_env()
    parser = argparse.ArgumentParser(description="Polyweb provider mock server")
    parser.add_argument("--host", default=settings.host, help="bind host")
    parser.add_argument("--port", type=int, default=settings.port, help="bind port")
    parser.add_argument("--db", type=Path, default=settings.db_path, help="state database")
    parser.add_argument("--log-level", default="info", help="uvicorn log level")
    args = parser.parse_args(argv)
    effective = dataclasses.replace(settings, host=args.host, port=args.port, db_path=args.db)
    uvicorn.run(
        create_app(effective),
        host=effective.host,
        port=effective.port,
        log_level=args.log_level,
        proxy_headers=False,
    )
