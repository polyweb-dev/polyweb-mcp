#!/usr/bin/env python3
"""Create and remove a temporary account for UI reviews of a running Polyweb stack.

Visual reviews (screenshots via Playwright) need a signed-in dashboard session.
This script provisions a throwaway reviewer instead of using a person's own
credentials, and removes it afterwards:

    # 1. Register the reviewer (prints its email).
    uv run python scripts/ui_review_account.py create --credentials-file /tmp/ui-review.json

    # 2. A project admin adds that email on the project's Members page as
    #    "Project admin". Polyweb has no operator route for joining a project,
    #    and system admins cannot see project scope, so this step is manual.
    #    The reviewer never needs (and this script never grants) system_admin.

    # 3. Confirm the reviewer can see the project(s), then sign in from
    #    Playwright with the email/password in the credentials file.
    uv run python scripts/ui_review_account.py status --credentials-file /tmp/ui-review.json

    # 4. Remove: leave every project, deactivate, delete the credentials file.
    uv run python scripts/ui_review_account.py cleanup --credentials-file /tmp/ui-review.json

The password is generated randomly, written only to the credentials file (keep
it outside the repository), and never printed. Deactivation goes through the
operator CLI (``polyweb-users``) inside the API container, so the Compose stack
must be running. Accounts cannot be hard-deleted: ``cleanup`` leaves the
reviewer deactivated, which blocks every sign-in.
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn

import httpx

DEFAULT_API = "http://localhost:8001"
DEFAULT_EMAIL = "ui-reviewer@polyweb-review.dev"


def _fail(message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def _operator(args: argparse.Namespace, *cli_args: str) -> subprocess.CompletedProcess[str]:
    """Run ``polyweb-users`` inside the API container (operator-only commands)."""

    command = [
        "docker",
        "compose",
        *(["-p", args.compose_project] if args.compose_project else []),
        "exec",
        "-T",
        args.compose_service,
        "uv",
        "run",
        "--no-sync",
        "polyweb-users",
        *cli_args,
    ]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        _fail(f"{path} not found")
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _login(client: httpx.Client, email: str, password: str) -> dict[str, str]:
    response = client.post("/auth/jwt/login", data={"username": email, "password": password})
    if response.status_code != 200:
        _fail(f"sign-in failed with HTTP {response.status_code}")
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _projects(client: httpx.Client, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = client.get("/api/v1/projects", headers=headers)
    if response.status_code != 200:
        _fail(f"listing projects failed with HTTP {response.status_code}")
    return list(response.json())


def create(args: argparse.Namespace) -> None:
    path = Path(args.credentials_file)
    if path.exists():
        _fail(f"{path} already exists; run cleanup first or choose another file")
    password = secrets.token_urlsafe(24)
    with httpx.Client(base_url=args.api, timeout=20) as client:
        response = client.post(
            "/auth/register",
            json={
                "email": args.email,
                "password": password,
                "username": args.username,
                "first_name": args.first_name,
                "last_name": args.last_name,
            },
        )
    if response.status_code not in (200, 201):
        _fail(
            f"registration failed with HTTP {response.status_code}: {response.text[:200]} "
            "(an earlier reviewer with this email may still exist; pass --email)"
        )
    record = {
        "api": args.api,
        "email": args.email,
        "password": password,
        "user_id": str(response.json()["id"]),
    }
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"registered reviewer {args.email} (user_id {record['user_id']})")
    print(f"credentials written to {path}")
    print(f"next: a project admin adds {args.email} as 'Project admin' on the Members page")


def status(args: argparse.Namespace) -> None:
    record = _load(Path(args.credentials_file))
    with httpx.Client(base_url=record.get("api", args.api), timeout=20) as client:
        projects = _projects(client, _login(client, record["email"], record["password"]))
    if not projects:
        _fail(f"{record['email']} is not a member of any project yet")
    for project in projects:
        print(f"member of {project.get('name')!r} ({project.get('id')})")


def cleanup(args: argparse.Namespace) -> None:
    path = Path(args.credentials_file)
    record = _load(path)
    user_id = record["user_id"]
    with httpx.Client(base_url=record.get("api", args.api), timeout=20) as client:
        headers = _login(client, record["email"], record["password"])
        for project in _projects(client, headers):
            response = client.delete(
                f"/api/v1/projects/{project['id']}/members/{user_id}", headers=headers
            )
            if response.status_code not in (200, 204, 404):
                _fail(
                    f"leaving {project.get('name')!r} failed with HTTP {response.status_code}: "
                    f"{response.text[:200]}"
                )
            print(f"left {project.get('name')!r} ({project['id']})")
    result = _operator(args, "deactivate", "--user-id", user_id)
    if result.returncode != 0:
        _fail(f"deactivate failed: {result.stderr.strip() or result.stdout.strip()}")
    path.unlink()
    print(f"removed reviewer {record['email']}: left its projects and deactivated the account")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--api", default=DEFAULT_API, help=f"API base URL (default {DEFAULT_API})")
    parser.add_argument("--compose-project", default=None, help="docker compose project name")
    parser.add_argument("--compose-service", default="api", help="API service name (default api)")
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("create", help="register the reviewer account")
    make.add_argument("--credentials-file", required=True, help="where to write the credentials")
    make.add_argument("--email", default=DEFAULT_EMAIL)
    make.add_argument("--username", default="ui-reviewer")
    make.add_argument("--first-name", default="UI")
    make.add_argument("--last-name", default="Reviewer")
    for name, help_text in (
        ("status", "list the projects the reviewer can see"),
        ("cleanup", "leave every project, deactivate, delete the credentials file"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--credentials-file", required=True)
    args = parser.parse_args(argv)
    {"create": create, "status": status, "cleanup": cleanup}[args.command](args)


if __name__ == "__main__":
    main()
