"""Static contract checks for the explicit development Compose path."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "compose.dev.yaml"
DOCKERFILE_PATH = REPO_ROOT / "Dockerfile.dev"


def test_development_compose_keeps_secrets_out_of_the_image() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert COMPOSE_PATH.name == "compose.dev.yaml"
    assert not (REPO_ROOT / "compose.override.yaml").exists()
    assert "-f compose.dev.yaml" in compose
    assert compose.count("- path: .env") == 2
    assert compose.count("required: true") == 2
    assert compose.count("- ./src:/app/src") == 2
    assert compose.count("- polyweb-data:/data") == 2

    assert re.search(r"(?im)^\s*(?:COPY|ADD)\s+[^\n]*\.env", dockerfile) is None
    assert re.search(r"(?im)^\s*(?:COPY|ADD)\s+[^\n]*(?:\./)?src(?:/|\s|$)", dockerfile) is None
    assert re.search(r"(?im)^\s*ARG\s+", dockerfile) is None
    assert set(re.findall(r"(?im)^\s*ENV\s+([A-Z][A-Z0-9_]*)", dockerfile)) == {
        "PYTHON_KEYRING_BACKEND",
        "PYTHONUNBUFFERED",
        "UV_COMPILE_BYTECODE",
        "UV_LINK_MODE",
    }
