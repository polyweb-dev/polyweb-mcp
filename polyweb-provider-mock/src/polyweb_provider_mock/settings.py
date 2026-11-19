"""Process settings of the provider mock, read from ``POLYWEB_PROVIDER_MOCK_*`` variables."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

__all__ = ["DEFAULT_PORT", "MockSettings", "default_db_path"]

DEFAULT_PORT = 8212
_PROJECT_DIR = Path(__file__).resolve().parents[2]


def default_db_path() -> Path:
    """Return ``polyweb-provider-mock/mock.db`` for a source checkout, else ``./mock.db``."""

    if (_PROJECT_DIR / "pyproject.toml").is_file():
        return _PROJECT_DIR / "mock.db"
    return Path.cwd() / "mock.db"


def _flag(value: str | None, *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class MockSettings:
    """Bind address, state database, and admin protection of one mock process.

    ``admin_token`` protects the ``/_mock`` admin API with a bearer token when
    set. ``auto_seed`` seeds the default accounts and keys into a database
    that has never been seeded. ``random_seed`` makes fault probabilities and
    latency jitter repeatable. ``public_url`` is the origin a browser on the
    host uses to reach the mock (for links the mock hands out, such as the
    Parallel device page); unset, the listening socket address is used.
    """

    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    db_path: Path = Path("mock.db")
    admin_token: str | None = None
    auto_seed: bool = True
    random_seed: int | None = None
    public_url: str | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "MockSettings":
        env = os.environ if environ is None else environ
        seed = env.get("POLYWEB_PROVIDER_MOCK_RANDOM_SEED", "").strip()
        db = env.get("POLYWEB_PROVIDER_MOCK_DB", "").strip()
        return cls(
            host=env.get("POLYWEB_PROVIDER_MOCK_HOST", "").strip() or "127.0.0.1",
            port=int(env.get("POLYWEB_PROVIDER_MOCK_PORT", "").strip() or DEFAULT_PORT),
            db_path=Path(db) if db else default_db_path(),
            admin_token=env.get("POLYWEB_PROVIDER_MOCK_ADMIN_TOKEN", "").strip() or None,
            auto_seed=_flag(env.get("POLYWEB_PROVIDER_MOCK_AUTO_SEED"), default=True),
            random_seed=int(seed) if seed else None,
            public_url=env.get("POLYWEB_PROVIDER_MOCK_PUBLIC_URL", "").strip().rstrip("/") or None,
        )
