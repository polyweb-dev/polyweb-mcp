#!/usr/bin/env python3
"""Publish bounded CI report bundles through the standard Gitea package API."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import socket
import ssl
import sys
import tempfile
import time
import zipfile
from pathlib import Path

HOST = "gitea.thiocyanate.dev"
TAILNET_IP = "100.64.0.2"
OWNER = "polyweb"
MAX_BYTES = 256 * 1024 * 1024
MAX_FILES = 2000
WORKFLOWS = {
    "api-unit": "unit-tests.log",
    "api-integration": "integration-tests.log",
    "api-bdd": "bdd-acceptance-tests.log",
    "api-live": "live-provider-tests.log",
    "api-mutation": "mutation-tests.log",
    "api-latency": "routing-latency-tests.log",
    "ui-quality": "ui-quality.log",
    "ui-bdd": "ui-bdd-tests.log",
}
REPORT_DIRECTORIES = (
    "coverage/gremlins",
    "test_reports",
    "polyweb-ui/coverage",
    "polyweb-ui/playwright-report",
    "polyweb-ui/test-results",
)
METADATA_KEYS = (
    "CI_REPO",
    "CI_COMMIT_SHA",
    "CI_COMMIT_BRANCH",
    "CI_PIPELINE_NUMBER",
    "CI_PIPELINE_URL",
    "CI_PIPELINE_STATUS",
    "CI_PIPELINE_RERUNS",
)


def report_files(root: Path, workflow: str) -> list[Path]:
    """Select report trees and this workflow's log, never caches or credentials."""
    candidates = [root / WORKFLOWS[workflow]]
    for name in REPORT_DIRECTORIES:
        directory = root / name
        if any(p.is_symlink() for p in (directory, *directory.parents)):
            continue
        if directory.is_dir():
            candidates.extend(directory.rglob("*"))
    files = []
    total = 0
    for path in sorted(candidates):
        if path.is_symlink() or not path.is_file():
            continue
        if any(p.is_symlink() for p in path.parents) or not path.resolve().is_relative_to(root):
            continue
        # A report directory must not accidentally archive an environment file or DB.
        if any(
            part.startswith(".") for part in path.relative_to(root).parts
        ) or path.suffix.lower() not in {
            ".html",
            ".json",
            ".md",
            ".txt",
            ".xml",
            ".csv",
            ".log",
            ".svg",
            ".css",
            ".js",
            ".png",
        }:
            continue
        total += path.stat().st_size
        files.append(path)
        if total > MAX_BYTES or len(files) > MAX_FILES:
            raise ValueError("Report files exceed the 256 MiB or 2000-file limit")
    return files


def make_bundle(root: Path, workflow: str, destination: Path) -> None:
    files = report_files(root, workflow)
    metadata: dict[str, object] = {key: os.environ.get(key, "") for key in METADATA_KEYS}
    metadata["workflow"] = workflow
    metadata["files"] = [str(path.relative_to(root)) for path in files]
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ci-metadata.json", json.dumps(metadata, indent=2) + "\n")
        for path in files:
            archive.write(path, path.relative_to(root))
    if destination.stat().st_size > MAX_BYTES:
        raise ValueError("Report ZIP exceeds the 256 MiB limit")


def publish(archive: Path, package: str, version: str, token: str) -> None:
    """Use the tailnet route with canonical SNI, full TLS checks, and no redirects."""
    path = f"/api/packages/{OWNER}/generic/{package}/{version}/reports.zip"
    context = ssl.create_default_context()
    # Docker step resolvers need not implement MagicDNS. Pin only the connection
    # address, equivalent to curl --resolve; certificate checks still use HOST.
    with (
        socket.create_connection((TAILNET_IP, 443), timeout=120) as tcp,
        context.wrap_socket(tcp, server_hostname=HOST) as tls,
    ):
        connection = http.client.HTTPSConnection(HOST, timeout=120, context=context)
        connection.sock = tls
        try:
            with archive.open("rb") as body:
                connection.request(
                    "PUT",
                    path,
                    body=body,
                    headers={
                        "Authorization": f"token {token}",
                        "Content-Type": "application/zip",
                        "Content-Length": str(archive.stat().st_size),
                    },
                )
                response = connection.getresponse()
                status = response.status
                response.close()
            if status != 201:
                # Never print response bodies: a server could reflect credentials.
                raise RuntimeError(f"Gitea upload failed with HTTP {status}")
        finally:
            connection.close()
    with archive.open("rb") as body:
        digest = hashlib.file_digest(body, "sha256").hexdigest()
    print(f"Artifact: https://{HOST}{path}")
    print(f"Package: https://{HOST}/{OWNER}/-/packages/generic/{package}/{version}")
    print(f"ZIP: {archive.stat().st_size} bytes, SHA256 {digest}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow", choices=WORKFLOWS)
    args = parser.parse_args()
    token = os.environ.pop("GITEA_UPLOAD_TOKEN", "").strip()
    if not token:
        raise ValueError("GITEA_UPLOAD_TOKEN is missing")
    number = os.environ.get("CI_PIPELINE_NUMBER", "")
    reruns = os.environ.get("CI_PIPELINE_RERUNS", "0") or "0"
    if not re.fullmatch(r"[0-9]+", number) or not re.fullmatch(r"[0-9]+", reruns):
        raise ValueError("CI pipeline number and rerun count must be numeric")
    version = f"pipeline-{number}-r{reruns}-{time.time_ns()}"
    with tempfile.TemporaryDirectory(prefix="gitea-ci-") as directory:
        archive = Path(directory) / "reports.zip"
        make_bundle(Path.cwd().resolve(), args.workflow, archive)
        publish(archive, f"polyweb-{args.workflow}", version, token)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, http.client.HTTPException) as exc:
        print(f"Artifact upload failed: {exc}", file=sys.stderr)
        sys.exit(1)
