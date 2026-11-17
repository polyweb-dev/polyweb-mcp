"""Static contract checks for the npd and dev Compose overlays."""

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "docker" / "npd" / "compose.yaml"
DEV_COMPOSE_PATH = REPO_ROOT / "docker" / "dev" / "compose.yaml"
DOCKERFILE_PATH = REPO_ROOT / "docker" / "npd" / "Dockerfile"


class _ComposeLoader(yaml.SafeLoader):
    """Safe loader that reads Compose merge tags (``!override``, ``!reset``) as plain values."""


def _untagged(loader: yaml.SafeLoader, node: yaml.Node) -> object:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return loader.construct_scalar(node)


for _tag in ("!override", "!reset"):
    _ComposeLoader.add_constructor(_tag, _untagged)


def _load(path: Path) -> Any:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_ComposeLoader)


@pytest.mark.parametrize("compose_name", ["compose.yaml", "docker/npd/compose.yaml"])
def test_mcp_execution_authority_and_api_dependency(compose_name: str) -> None:
    base = _load(REPO_ROOT / "compose.yaml")
    compose = _load(REPO_ROOT / compose_name)
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

    assert not (REPO_ROOT / "compose.override.yaml").exists()
    assert "scripts/linux/stack.sh npd" in compose
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


@pytest.mark.parametrize("overlay", [COMPOSE_PATH, DEV_COMPOSE_PATH])
def test_worktree_overlays_never_address_the_pd_project(overlay: Path) -> None:
    """npd and dev take their project name from the stack script, never `polyweb`."""

    base = _load(REPO_ROOT / "compose.yaml")
    compose = _load(overlay)

    assert base["name"] == "polyweb"
    assert compose["name"].startswith("${POLYWEB_STACK_PROJECT:?")


def test_npd_binds_loopback_worktree_ports_and_calls_real_providers() -> None:
    compose = _load(COMPOSE_PATH)
    services = compose["services"]

    assert services["api"]["ports"] == ["127.0.0.1:${POLYWEB_API_PORT:?set POLYWEB_API_PORT}:8001"]
    assert services["mcp"]["ports"] == ["127.0.0.1:${POLYWEB_MCP_PORT:?set POLYWEB_MCP_PORT}:8000"]
    assert services["ui"]["profiles"] == ["ui"]
    assert services["ui"]["ports"] == ["127.0.0.1::80"]
    for name in ("api", "mcp"):
        assert services[name]["build"]["dockerfile"] == "docker/npd/Dockerfile"
        assert services[name]["environment"]["POLYWEB_PROVIDER_MOCK_URL"] == ""


def test_dev_routes_providers_to_the_mock_without_real_keys() -> None:
    services = _load(DEV_COMPOSE_PATH)["services"]

    for name in ("api", "mcp"):
        environment = services[name]["environment"]
        assert environment["POLYWEB_PROVIDER_MOCK_URL"] == "http://provider-mock:8212"
        keys = {key: value for key, value in environment.items() if key.endswith("_API_KEY")}
        assert keys
        assert set(keys.values()) == {""}
        assert services[name]["depends_on"]["provider-mock"]["condition"] == "service_healthy"
    assert services["provider-mock"]["ports"][0].startswith("127.0.0.1:")
