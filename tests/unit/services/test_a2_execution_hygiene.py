"""A2 hygiene: shared execution service exists and transports stay decoupled.

AC1 requires REST and MCP to share one transport-independent execution
service. This module locks the structural half of that contract by inspecting
parsed import targets, never raw text: docstrings and comments cannot trip the
checks:

* a shared execution module exists under ``services/`` (beyond scope-only),
* no execution module imports transport frameworks or routers,
* MCP never imports the REST router.
"""

from __future__ import annotations

import ast
import pathlib

SRC_ROOT = pathlib.Path(__file__).resolve().parents[3] / "src" / "freesearch"
SERVICES_ROOT = SRC_ROOT / "services"
MCP_SERVER = SRC_ROOT / "mcp" / "server.py"

_TRANSPORT_MODULES = ("fastapi", "starlette", "mcp", "fastmcp", "freesearch.routers")


def _execution_modules() -> list[pathlib.Path]:
    return sorted(SERVICES_ROOT.glob("*execut*.py"))


def _imported_modules(path: pathlib.Path) -> list[str]:
    """Return every module named by an import statement in ``path``."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append(node.module)
    return modules


def _is_transport_module(module: str) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in _TRANSPORT_MODULES)


def test_shared_execution_service_exists_beyond_scope() -> None:
    """AC1 structural: a transport-independent execution service is present."""

    modules = _execution_modules()
    names = [path.name for path in modules]
    assert "execution_scope.py" in names, f"scope module missing, found: {names}"
    shared = [name for name in names if name != "execution_scope.py"]
    assert shared, (
        "missing shared execution service: expected a new "
        "src/freesearch/services/*execut*.py beyond execution_scope.py "
        f"(found only {names})"
    )


def test_execution_modules_have_no_transport_imports() -> None:
    """New execution service must have no transport imports (AC1/DoD layering)."""

    offenders: list[str] = []
    for path in _execution_modules():
        hits = sorted(
            {module for module in _imported_modules(path) if _is_transport_module(module)}
        )
        if hits:
            offenders.append(f"{path.name} imports {hits}")
    assert not offenders, f"execution service must stay transport-free: {offenders}"


def test_mcp_does_not_import_rest_router() -> None:
    """Transports share a service; MCP must not import the REST router."""

    imported = _imported_modules(MCP_SERVER)
    router_imports = sorted(
        module
        for module in imported
        if module == "freesearch.routers" or module.startswith("freesearch.routers.")
    )
    assert not router_imports, (
        "mcp/server.py still imports a REST router module "
        f"({router_imports}); extract shared execution into services/"
    )
