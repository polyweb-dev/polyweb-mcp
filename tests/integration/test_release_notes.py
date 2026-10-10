"""Release-note contract checks for the local-users slice (P8, RC-5 parts).

The note records the custom-guard deviation beside the published Bearer
scheme, so a discovery client finds the token URL and no operation carries a
security requirement. These tests read the checked-in note only.
"""

from pathlib import Path

_NOTE = Path(__file__).resolve().parents[2] / "docs" / "releases" / "local-users.md"


def test_release_note_records_custom_guard_deviation() -> None:
    text = _NOTE.read_text(encoding="utf-8")

    assert "custom ASGI guard" in text
    assert "auth/jwt/login" in text
    assert "no single operation carries a security requirement" in text
