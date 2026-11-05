#!/usr/bin/env python3
"""Seed project-private provider API keys into a local FreeSearch backend.

Stores real provider keys for the ``@live`` e2e scenarios through the REST API:
log in, find or create the project, then keep one ``local-e2e-<provider>``
credential and one enabled binding per provider. Reruns are idempotent.

Secrets enter through masked ``getpass`` prompts or ``--keys-file``, a
dotenv-style file of ``provider=key`` lines that replaces every key prompt
(the account password is still prompted). Keep the keys file gitignored —
``.env.*`` is ignored in this repo — and delete it after seeding. Only
``api_key`` credentials are seeded; ``parallel`` also supports OAuth
credentials, which the per-credential device-flow surface handles instead.

Examples:
  uv run python scripts/seed_local_providers.py --email you@example.com
  uv run python scripts/seed_local_providers.py --email you@example.com --providers tavily,exa
  uv run python scripts/seed_local_providers.py --email you@example.com --keys-file .env.providers
  uv run python scripts/seed_local_providers.py --email you@example.com --rotate
"""

import argparse
import contextlib
import getpass
import stat
import sys
from pathlib import Path
from typing import Any

import httpx

from freesearch.configuration.config import get_settings
from freesearch.infrastructure.secrets import ProviderName

LABEL_PREFIX = "local-e2e-"
BINDING_PRIORITY = 100


class ApiError(RuntimeError):
    """One HTTP failure reduced to a secret-free message."""


def _detail(response: httpx.Response) -> str:
    """Return the response's error code/detail text, never request content."""

    try:
        body: Any = response.json()
    except ValueError:
        return response.reason_phrase or "error"
    detail = body.get("detail") if isinstance(body, dict) else body
    if isinstance(detail, dict):
        detail = detail.get("code") or detail.get("message") or detail
    if isinstance(detail, list):
        detail = "; ".join(
            item.get("msg", str(item)) if isinstance(item, dict) else str(item) for item in detail
        )
    return str(detail)[:300]


def call(client: httpx.Client, method: str, path: str, **kwargs: Any) -> Any:
    """Run one API request; failures raise ApiError without secret material."""

    try:
        response = client.request(method, path, **kwargs)
    except httpx.HTTPError as error:
        raise ApiError(f"{method} {path}: {type(error).__name__}") from error
    if response.status_code >= 400:
        raise ApiError(f"{method} {path}: HTTP {response.status_code} {_detail(response)}")
    return response.json() if response.content else None


def login(client: httpx.Client, email: str, password: str) -> str:
    """Exchange the account credentials for a bearer token."""

    body = call(client, "POST", "/auth/jwt/login", data={"username": email, "password": password})
    return str(body["access_token"])


def ensure_project(client: httpx.Client, name: str, email: str) -> str:
    """Return the id of the project named ``name``, creating it when absent."""

    projects = call(client, "GET", "/api/v1/projects", params={"include_archived": "false"})
    for project in projects:
        if project.get("name") == name:
            return str(project["id"])
    created = call(
        client,
        "POST",
        "/api/v1/projects",
        json={"name": name, "initial_admin_email": email},
    )
    return str(created["id"])


def find_credential(
    credentials: list[dict[str, Any]], provider: str, label: str
) -> dict[str, Any] | None:
    """Return the seeded credential: active, private, this provider and label."""

    for credential in credentials:
        if (
            credential.get("provider_type") == provider
            and credential.get("label") == label
            and credential.get("owner_scope") == "project"
            and credential.get("status") == "active"
        ):
            return credential
    return None


def ensure_binding(
    client: httpx.Client,
    project_id: str,
    credential: dict[str, Any],
    provider: str,
    operations: set[str],
) -> list[str]:
    """Keep exactly one binding on this credential and set its enabled operations."""

    base = f"/api/v1/projects/{project_id}/bindings"
    bindings = call(client, "GET", base)
    candidates = [b for b in bindings if b.get("credential_id") == credential["id"]]
    binding = next((b for b in candidates if b.get("route_label") == provider), None)
    if binding is None and candidates:
        binding = candidates[0]
    for extra in candidates:
        if extra is not binding:
            call(client, "DELETE", f"{base}/{extra['id']}")
    if binding is None:
        binding = call(
            client,
            "POST",
            base,
            json={
                "credential_id": credential["id"],
                "route_label": provider,
                "priority": BINDING_PRIORITY,
            },
        )
    update: dict[str, Any] = {"enabled_operations": sorted(operations)}
    if binding.get("route_label") != provider:
        update["route_label"] = provider
    if binding.get("priority") != BINDING_PRIORITY:
        update["priority"] = BINDING_PRIORITY
    updated = call(client, "PATCH", f"{base}/{binding['id']}", json=update)
    return sorted(updated.get("enabled_operations", []))


def _provider_key(keys: dict[str, str] | None, provider: str, prompt: str) -> str:
    """Return the key for one provider from the file, or its masked prompt."""

    if keys is not None:
        return keys.get(provider, "").strip()
    return getpass.getpass(prompt).strip()


def seed_provider(
    client: httpx.Client,
    project_id: str,
    provider: str,
    capability: set[str],
    rotate: bool,
    keys: dict[str, str] | None,
) -> None:
    """Create or rotate the seeded credential for one provider and bind it."""

    base = f"/api/v1/projects/{project_id}"
    credentials = call(client, "GET", f"{base}/credentials")
    credential = find_credential(credentials, provider, f"{LABEL_PREFIX}{provider}")
    state = "existing"
    if credential is None:
        secret = _provider_key(keys, provider, f"{provider} API key (blank to skip): ")
        if not secret:
            print(f"{provider}: skipped")
            return
        credential = call(
            client,
            "POST",
            f"{base}/credentials",
            json={
                "provider_type": provider,
                "label": f"{LABEL_PREFIX}{provider}",
                "auth_mode": "api_key",
                "secret": secret,
            },
        )
        state = "created"
    elif rotate:
        secret = _provider_key(keys, provider, f"{provider} new API key (blank to keep): ")
        if secret:
            credential = call(
                client,
                "POST",
                f"{base}/credentials/{credential['id']}/rotate",
                json={
                    "expected_generation": credential["generation"],
                    "secret": secret,
                },
            )
            state = "rotated"
    permitted = set(credential.get("permitted_operations") or [])
    enabled = ensure_binding(client, project_id, credential, provider, capability & permitted)
    print(f"{provider}: {state} credential={credential['id']} enabled={enabled}")


def _keys_file(parser: argparse.ArgumentParser, value: str | None) -> dict[str, str] | None:
    """Parse ``--keys-file`` into {provider: key}; errors never name a value."""

    if value is None:
        return None
    path = Path(value)
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        parser.error(f"cannot read keys file {path}: {error.strerror or error}")
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        print(
            f"warning: {path} grants group/other permissions; consider chmod 600 {path}",
            file=sys.stderr,
        )
    valid = {provider.value for provider in ProviderName}
    keys: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line[:7].lower() == "export ":
            line = line[7:].strip()
        if "=" not in line:
            parser.error(f"keys file line {lineno}: expected provider=key")
        name, _, val = line.partition("=")
        name = name.strip().lower()
        if name not in valid:
            parser.error(
                f"keys file line {lineno}: unknown provider name "
                f"(expected one of: {', '.join(sorted(valid))})"
            )
        if name in keys:
            parser.error(f"keys file line {lineno}: duplicate provider {name!r}")
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        keys[name] = val
    return keys


def _parse_providers(parser: argparse.ArgumentParser, value: str | None) -> list[str]:
    names = [name.strip() for name in (value or "").split(",") if name.strip()]
    names = names or [provider.value for provider in ProviderName]
    valid = {provider.value for provider in ProviderName}
    unknown = [name for name in names if name not in valid]
    if unknown:
        parser.error(f"unknown provider types: {', '.join(unknown)}")
    return names


def _base_url(parser: argparse.ArgumentParser, value: str | None) -> str:
    if value:
        return value.rstrip("/")
    port = get_settings().api_port
    if port is None:
        parser.error("--base-url is required: FREESEARCH_API_PORT is not set")
    return f"http://127.0.0.1:{port}"


def main() -> int:
    """Seed the requested provider credentials and print a secret-free summary."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="account email used to log in")
    parser.add_argument(
        "--project-name", default="Local E2E", help="project to seed (created if absent)"
    )
    parser.add_argument(
        "--providers",
        default=None,
        help="comma-separated provider types (default: all supported providers)",
    )
    parser.add_argument(
        "--keys-file",
        default=None,
        help="dotenv-style file of provider=key lines; replaces all key prompts",
    )
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="prompt for new keys on existing seeded credentials and rotate them",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="API base URL (default: http://127.0.0.1:$FREESEARCH_API_PORT)",
    )
    args = parser.parse_args()

    providers = _parse_providers(parser, args.providers)
    base_url = _base_url(parser, args.base_url)
    keys = _keys_file(parser, args.keys_file)

    password = getpass.getpass("Password: ")
    if not password:
        print("a password is required", file=sys.stderr)
        return 2

    failures = 0
    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        try:
            token = login(client, args.email, password)
        except ApiError as error:
            print(f"login failed: {error}", file=sys.stderr)
            return 2
        client.headers["Authorization"] = f"Bearer {token}"
        try:
            project_id = ensure_project(client, args.project_name, args.email)
            view = call(client, "GET", f"/api/v1/projects/{project_id}/providers")
            capability = {
                item["provider_type"]: set(item.get("capability") or [])
                for item in view.get("providers", [])
            }
            for provider in providers:
                try:
                    seed_provider(
                        client,
                        project_id,
                        provider,
                        capability.get(provider, set()),
                        rotate=args.rotate,
                        keys=keys,
                    )
                except ApiError as error:
                    failures += 1
                    print(f"{provider}: failed {error}")
            view = call(client, "GET", f"/api/v1/projects/{project_id}/providers")
            effective = {
                item["provider_type"]: item.get("effective_operations") or []
                for item in view.get("providers", [])
            }
            print(f"project: {project_id}")
            for provider in providers:
                print(f"{provider}: effective_operations={sorted(effective.get(provider, []))}")
        except ApiError as error:
            print(f"failed: {error}", file=sys.stderr)
            return 2
        finally:
            with contextlib.suppress(Exception):
                call(client, "POST", "/auth/jwt/logout")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("cancelled", file=sys.stderr)
        raise SystemExit(130) from None
