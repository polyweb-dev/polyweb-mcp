"""Frontend/backend API contract check (T4).

Every ``/api/v1/...`` route the UI can build must exist in the backend's
OpenAPI schema. Extraction covers three shapes seen in ``freesearch-ui/src``:

1. literals — ```/api/v1/projects/${segment(projectId)}/credentials`` — where a
   ``${...}`` interpolation may contain nested braces and must be consumed
   whole before stopping at whitespace, quotes, ``?`` or ``#``;
2. base compositions — ``const BASE = "/api/v1/projects"`` or a small function
   returning a ``/api/v1`` template, then `` `${BASE}/${x}/api-keys` `` or
   `` `${bindingsBase(id)}/grants` `` at the start of a template;
3. parameter bases — helpers like ``requestJson(`${base}/oauth/device`)`` where
   ``base`` is a function parameter; each resolved base ending in a path
   parameter is substituted, which covers the credential OAuth routes.

Test files (``*.test.*`` and ``src/test/**``) are excluded.
"""

from __future__ import annotations

import re
from itertools import chain
from pathlib import Path

import pytest

from freesearch.routers.api import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]
UI_SRC = REPO_ROOT / "freesearch-ui" / "src"

PATH_START = re.compile(r"/api/v1/")
STOP_CHARS = frozenset(" \t\n\"'`?#")
QUERY_TAIL = re.compile(r"[?#].*$")

CONST_BASE = re.compile(
    r"\bconst\s+([A-Za-z_$][\w$]*)\s*=\s*([\"'`])((?:(?!\2).)*?(?:/api/v1/|\$\{)(?:(?!\2).)*?)\2",
    re.S,
)
FN_BASE = re.compile(
    r"\bfunction\s+([A-Za-z_$][\w$]*)[^}]*?return\s*([\"'`])((?:(?!\2).)*?(?:/api/v1/|\$\{)(?:(?!\2).)*?)\2",
    re.S,
)
ARROW_BASE = re.compile(
    r"\bconst\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*(?::[^=]+?)?=>\s*([\"'`])((?:(?!\2).)*?(?:/api/v1/|\$\{)(?:(?!\2).)*?)\2",
    re.S,
)
# `${head}` or `${head(args)}` at the start of a template literal, followed by
# a path suffix. The leading quote/backtick keeps `${x}` inside an /api/v1
# literal from counting as a base composition.
COMPOSITION = re.compile(r"[\"'`]\s*\$\{\s*([A-Za-z_$][\w$]*)\s*(?:\([^}]*\))?\s*\}(/[^\s\"'`?#]*)")
BASE_LIKE = re.compile(r"base", re.I)


def _path_literals(text: str) -> list[str]:
    """Every ``/api/v1/...`` literal; ``${...}`` is consumed with balancing."""

    literals: list[str] = []
    for match in PATH_START.finditer(text):
        buf = [match.group(0)]
        i = match.end()
        depth = 0
        while i < len(text):
            if depth == 0 and text[i] in STOP_CHARS:
                break
            if depth == 0 and text.startswith("${", i):
                depth += 1
                buf.append("${")
                i += 2
                continue
            ch = text[i]
            buf.append(ch)
            if depth > 0:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
            i += 1
        literal = "".join(buf).rstrip("/")
        if literal != "/api/v1":
            literals.append(literal)
    return literals


def _replace_interpolations(text: str) -> str:
    """Substitute each balanced ``${...}`` with one ``{param}`` segment."""

    out: list[str] = []
    i = 0
    while i < len(text):
        if text.startswith("${", i):
            depth = 1
            j = i + 2
            while j < len(text) and depth > 0:
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                j += 1
            out.append("{param}")
            i = j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _normalize(template: str) -> str:
    """Reduce a raw template to a route: interpolations out, query stripped."""

    return QUERY_TAIL.sub("", _replace_interpolations(template))


ALL_CAPS_NAME = re.compile(r"[A-Z][A-Z0-9_]*")


def _bases(text: str) -> dict[str, str]:
    """Resolve const and single-return base builders to normalized templates.

    Plain consts count as bases only when their name says so — ``BASE``,
    ``SYSTEM_BASE``, ``poolBase`` — or when it is all caps; a local ``path``
    or ``url`` is a request path, not a base. Function builders qualify by
    what they return.
    """

    raw: dict[str, str] = {}
    for match in chain(CONST_BASE.finditer(text), ARROW_BASE.finditer(text)):
        name = match.group(1)
        if BASE_LIKE.search(name) or ALL_CAPS_NAME.fullmatch(name):
            raw.setdefault(name, match.group(3))
    for match in FN_BASE.finditer(text):
        raw.setdefault(match.group(1), match.group(3))
    # Nested bases (`${SYSTEM_BASE}/...` inside another base) need a few passes.
    for _ in range(4):
        changed = False
        for name, template in list(raw.items()):
            expanded = template
            for other, expansion in raw.items():
                expanded = expanded.replace(f"${{{other}}}", expansion)
                expanded = re.sub(
                    r"\$\{\s*" + re.escape(other) + r"\s*\([^)]*\)\s*\}", expansion, expanded
                )
            if expanded != template:
                raw[name] = expanded
                changed = True
        if not changed:
            break
    resolved = {name: _normalize(template) for name, template in raw.items()}
    return {name: t for name, t in resolved.items() if "/api/v1" in t}


def extract_routes(text: str) -> set[tuple[str, ...]]:
    """Route observations of one file.

    Each tuple lists alternative templates for one observed path; at least one
    alternative must resolve to a backend route. A ``${base}`` parameter that
    no same-file binding resolves expands to every base ending in a path
    parameter — the check passes when any substitution exists.
    """

    literals = {_normalize(literal) for literal in _path_literals(text)}
    bases = _bases(text)
    literals.update(bases.values())
    refs: set[tuple[str, ...]] = {(route,) for route in literals if route != "/api/v1"}
    param_bases = sorted(t for t in bases.values() if t.endswith("/{param}"))
    for match in COMPOSITION.finditer(text):
        head, suffix = match.group(1), match.group(2).rstrip("/")
        if head in bases:
            refs.add((_normalize(bases[head] + suffix),))
        elif BASE_LIKE.search(head) and param_bases:
            refs.add(tuple({_normalize(base + suffix) for base in param_bases}))
    return refs


def _ui_route_literals() -> dict[tuple[str, ...], Path]:
    """Map each extracted route observation to the first source file using it."""

    found: dict[tuple[str, ...], Path] = {}
    for path in sorted(UI_SRC.rglob("*")):
        if path.suffix not in (".ts", ".tsx") or ".test." in path.name:
            continue
        if path.is_relative_to(UI_SRC / "test"):
            continue
        for observation in extract_routes(path.read_text(encoding="utf-8")):
            found.setdefault(observation, path.relative_to(REPO_ROOT))
    return found


def _matches_template(route: str, templates: frozenset[str]) -> bool:
    """Segment-wise match of one normalized route against OpenAPI templates."""

    route_parts = route.split("/")
    for template in templates:
        template_parts = template.split("/")
        if len(route_parts) != len(template_parts):
            continue
        if all(
            (t.startswith("{") and t.endswith("}")) or t == r
            for t, r in zip(template_parts, route_parts, strict=True)
        ):
            return True
    return False


@pytest.fixture(scope="module")
def openapi_templates() -> frozenset[str]:
    """The path templates of the real API application."""

    return frozenset(create_app([]).openapi()["paths"])


SAMPLE_TS = """
const BASE = "/api/v1/projects"
function itemPath(id: string): string {
  return `/api/v1/projects/${encodeURIComponent(id)}/items/${segment(id)}`
}
async function load(base: string) {
  await fetch(`${base}/status`)
  await fetch(`${BASE}/${x()}/grants?deep=true`)
  await fetch(`/api/v1/projects/${cond ? a({b:1}) : b()}/meta`)
}
"""


def test_extractor_handles_balanced_and_composed_paths() -> None:
    """The extractor covers interpolation braces and base compositions."""

    refs = extract_routes(SAMPLE_TS)
    assert ("/api/v1/projects",) in refs  # the const itself
    assert ("/api/v1/projects/{param}/items/{param}",) in refs  # balanced nested braces
    assert ("/api/v1/projects/{param}/meta",) in refs  # braces inside interpolation
    assert ("/api/v1/projects/{param}/grants",) in refs  # const composition + query strip
    # `${base}` expands to each base ending in a path param (here only itemPath's).
    assert ("/api/v1/projects/{param}/items/{param}/status",) in refs


def test_extractor_param_base_substitutes_id_ended_bases() -> None:
    """A `${base}` parameter expands to every base ending in a path param."""

    snippet = """
    const SYSTEM_BASE = "/api/v1/system/credentials"
    function onePath(id: string): string {
      return `${SYSTEM_BASE}/${encodeURIComponent(id)}`
    }
    async function call(base: string) {
      await fetch(`${base}/oauth/device`)
    }
    """
    refs = extract_routes(snippet)
    assert ("/api/v1/system/credentials/{param}/oauth/device",) in refs


def test_ui_api_literals_match_openapi_paths(openapi_templates: frozenset[str]) -> None:
    """Every UI ``/api/v1`` route resolves to a backend route."""

    observations = _ui_route_literals()
    assert observations, "no /api/v1 routes found under freesearch-ui/src"
    missing = {
        observation: source
        for observation, source in observations.items()
        if not any(_matches_template(route, openapi_templates) for route in observation)
    }
    assert not missing, "UI references routes absent from the OpenAPI schema: " + ", ".join(
        f"{' | '.join(observation)} ({source})" for observation, source in sorted(missing.items())
    )
