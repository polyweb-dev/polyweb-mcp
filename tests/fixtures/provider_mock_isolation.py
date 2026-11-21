"""Keep a developer's provider mock origin out of the test suites.

``Settings`` reads the worktree ``.env`` as well as the process environment.
A developer who points the app at the provider mock with
``POLYWEB_PROVIDER_MOCK_URL`` would otherwise reroute provider traffic in every
test that builds the shared HTTP client. The root ``tests/conftest.py`` and the
Behave ``before_all`` hook call :func:`isolate_provider_mock` first.
"""

import os
from collections.abc import MutableMapping

__all__ = ["PROVIDER_MOCK_OPT_IN", "PROVIDER_MOCK_URL", "isolate_provider_mock"]

PROVIDER_MOCK_URL = "POLYWEB_PROVIDER_MOCK_URL"
PROVIDER_MOCK_OPT_IN = "POLYWEB_TEST_PROVIDER_MOCK"


def isolate_provider_mock(environ: MutableMapping[str, str] | None = None) -> str | None:
    """Mask the mock origin unless the run opts in; return the origin that stays active.

    Without ``POLYWEB_TEST_PROVIDER_MOCK=1`` the process value becomes blank.
    A blank process value wins over the ``.env`` value and means "off". With
    the opt-in, the origin must come from the process environment: an
    opted-in run that has no origin raises, so fake mock keys never go to a
    real provider.
    """

    env = os.environ if environ is None else environ
    if env.get(PROVIDER_MOCK_OPT_IN, "").strip() != "1":
        env[PROVIDER_MOCK_URL] = ""
        return None
    origin = env.get(PROVIDER_MOCK_URL, "").strip()
    if not origin:
        raise RuntimeError(
            f"{PROVIDER_MOCK_OPT_IN}=1 needs {PROVIDER_MOCK_URL} in the process environment"
        )
    return origin
