"""Static contract checks for the explicit development Compose path."""

import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "compose.dev.yaml"
DOCKERFILE_PATH = REPO_ROOT / "Dockerfile.dev"


@pytest.mark.parametrize("compose_name", ["compose.yaml", "compose.dev.yaml"])
def test_mcp_execution_authority_and_api_dependency(compose_name: str) -> None:
    base = yaml.safe_load((REPO_ROOT / "compose.yaml").read_text(encoding="utf-8"))
    compose = yaml.safe_load((REPO_ROOT / compose_name).read_text(encoding="utf-8"))
    mcp = compose["services"]["mcp"]
    environment = mcp["environment"]
    api = compose["services"]["api"]
    # The dev override inherits its API port from the base Compose file.
    api_ports = api.get("ports", base["services"]["api"]["ports"])
    container_ports = {int(str(port).rsplit(":", 1)[-1]) for port in api_ports}
    standalone = str(environment.get("POLYWEB_EXECUTION_MCP_STANDALONE", "false")).lower()
    url = environment.get("POLYWEB_EXECUTION_AUTHORITY_URL")
    if standalone not in {"1", "true", "yes", "on"}:
        assert url
        authority = urlsplit(url)
        assert authority.scheme in {"http", "https"}
        assert authority.hostname == "api"
        assert authority.port in container_ports
        assert authority.path in {"", "/"}
    assert mcp["depends_on"]["api"]["condition"] == "service_healthy"


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
