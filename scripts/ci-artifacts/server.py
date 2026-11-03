#!/usr/bin/env python3
"""VPS report bundles with Woodpecker authentication. Python stdlib only."""
from __future__ import annotations

import hashlib
import hmac
import html
import io
import json
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath

SAFE_KEY = re.compile(r"[1-9][0-9]*--[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}\Z")
MAX_BYTES = 100 * 1024 * 1024


class ArtifactServer(ThreadingHTTPServer):
    def __init__(self, address, root, token, api_token, wp_url, public_url, repo_id=1):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.token = token
        self.api_token = api_token
        self.wp_url = wp_url.rstrip("/")
        self.public_url = public_url.rstrip("/")
        self.origins = {self.public_url} | {value.strip().rstrip("/") for value in
            os.environ.get("ARTIFACT_ALTERNATE_ORIGINS", "").split(",") if value.strip()}
        self.repo_id = repo_id
        self.lock = threading.Lock()
        super().__init__(address, Handler)

    def api(self, path, headers):
        request = urllib.request.Request(self.wp_url + path, headers=headers)
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)


class Handler(BaseHTTPRequestHandler):
    server: ArtifactServer

    def reply(self, status, body=b"", content_type="text/plain; charset=utf-8", **headers):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
        for key, value in headers.items():
            self.send_header(key.replace("_", "-"), value)
        self.end_headers()
        self.wfile.write(body)

    def authorized_user(self):
        headers = {name: self.headers[name] for name in ("Authorization", "Cookie") if name in self.headers}
        if not headers:
            self.reply(401, b'Log in to Woodpecker first, then open /artifacts/.')
            return None
        try:
            user = self.server.api("/api/user", headers)
            self.server.api(f"/api/repos/{self.server.repo_id}", headers)
            if not user.get("admin"):
                self.reply(403, b"Woodpecker administrator permission is required for report access.")
                return None
            return user
        except urllib.error.HTTPError as error:
            self.reply(401 if error.code == 401 else 403, b"Woodpecker authentication or repository access denied.")
        except (OSError, ValueError):
            self.reply(503, b"Woodpecker authentication service is unavailable.")
        return None

    def csrf(self, user, key, hour=None):
        value = f'{user["id"]}:{key}:{int(time.time() // 3600) if hour is None else hour}'
        return hmac.new(self.server.token.encode(), value.encode(), hashlib.sha256).hexdigest()

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/artifacts":
            self.reply(303, Location="/artifacts/")
            return
        user = self.authorized_user()
        if user is None:
            return
        if path == "/artifacts/":
            self.index(user)
            return
        key = path.removeprefix("/artifacts/download/")
        if path.startswith("/artifacts/download/") and SAFE_KEY.fullmatch(key):
            with self.server.lock:
                bundle = self.server.root / f"{key}.zip"
                try:
                    data = bundle.read_bytes()
                except FileNotFoundError:
                    self.reply(404, b"Report bundle not found.")
                    return
            self.reply(200, data, "application/zip", Content_Disposition=f'attachment; filename="pipeline-{key}.zip"')
            return
        self.reply(404, b"Not found.")

    def index(self, user):
        rows = []
        with self.server.lock:
            records = []
            for path in self.server.root.glob("*.json"):
                try:
                    record = json.loads(path.read_text())
                    if (self.server.root / f'{record["key"]}.zip').is_file():
                        records.append(record)
                except (OSError, ValueError, KeyError):
                    continue
        for record in sorted(records, key=lambda item: item["uploaded_at"], reverse=True):
            key = record["key"]
            esc = lambda value: html.escape(str(value), quote=True)
            files = "<br>".join(esc(name) for name in record["files"])
            rows.append(f'''<tr><td><a href="/repos/{self.server.repo_id}/pipeline/{record['pipeline']}">#{record['pipeline']}</a>
                <br>{esc(record['workflow'])}</td><td><code>{esc(record['commit'][:12])}</code><br>{esc(record['status'])}</td>
                <td>{record['bytes'] / 1024:.1f} KiB<details><summary>Files</summary>{files}</details></td>
                <td><a class="button" href="/artifacts/download/{key}">Download ZIP</a>
                <form method="post" action="/artifacts/delete/{key}">
                <input type="hidden" name="csrf" value="{self.csrf(user, key)}">
                <label><input type="checkbox" name="confirm" value="yes" required> Confirm deletion</label>
                <button type="submit">Delete bundle</button></form></td></tr>''')
        content = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
            <title>CI reports · Woodpecker</title><style>
            body{{font:16px system-ui;background:#171b20;color:#e7ebef;max-width:1100px;margin:48px auto;padding:0 24px}}
            a{{color:#8dd7bd}}h1{{font-size:32px}}p{{color:#b9c3ce}}table{{width:100%;border-collapse:collapse}}
            th,td{{padding:20px 12px;text-align:left;border-bottom:1px solid #39424e;vertical-align:top}}
            form{{margin-top:16px}}button,.button{{padding:8px 12px;border:1px solid #6e8195;background:#242e38;color:#e7ebef;border-radius:5px}}
            label{{display:block;font-size:13px;margin-bottom:8px}}details{{max-width:420px;overflow-wrap:anywhere;font-size:13px;margin-top:10px}}
            </style><a href="/">← Woodpecker</a><h1>CI reports</h1>
            <p>Signed in as {html.escape(user.get('login', str(user['id'])))} · VPS storage · {len(records)} bundles</p>
            <p>Download and extract a ZIP to view its HTML, JSON, Markdown, CSV, and image reports. Deletion is permanent.</p>
            <table><thead><tr><th>Pipeline / workflow</th><th>Commit / result</th><th>Bundle contents</th><th>Actions</th></tr></thead>
            <tbody>{''.join(rows) or '<tr><td colspan="4">No report bundles uploaded yet.</td></tr>'}</tbody></table></html>'''
        self.reply(200, content.encode(), "text/html; charset=utf-8")

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if path.startswith("/artifacts/upload/"):
            self.upload(path.removeprefix("/artifacts/upload/"))
            return
        user = self.authorized_user()
        if user is None:
            return
        key = path.removeprefix("/artifacts/delete/")
        if not path.startswith("/artifacts/delete/") or not SAFE_KEY.fullmatch(key):
            self.reply(404, b"Not found.")
            return
        if self.headers.get("Origin") not in self.server.origins:
            self.reply(403, b"Invalid request origin.")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= 4096:
            self.reply(400, b"Invalid delete request.")
            return
        form = urllib.parse.parse_qs(self.rfile.read(length).decode())
        hour = int(time.time() // 3600)
        valid = any(hmac.compare_digest(form.get("csrf", [""])[0], self.csrf(user, key, bucket)) for bucket in (hour, hour - 1))
        if not valid or form.get("confirm") != ["yes"]:
            self.reply(403, b"Deletion requires a valid form and explicit confirmation.")
            return
        with self.server.lock:
            (self.server.root / f"{key}.zip").unlink(missing_ok=True)
            (self.server.root / f"{key}.json").unlink(missing_ok=True)
        self.reply(303, Location="/artifacts/")

    def upload(self, key):
        if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + self.server.token):
            self.reply(401, b"Invalid upload credential.")
            return
        if not SAFE_KEY.fullmatch(key):
            self.reply(400, b"Invalid bundle key.")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= MAX_BYTES:
            self.reply(413, b"Bundle must be between 1 byte and 100 MiB.")
            return
        data = self.rfile.read(length)
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as bundle:
                members = bundle.infolist()
                if not members or len(members) > 10000 or sum(item.file_size for item in members) > MAX_BYTES:
                    raise ValueError("Invalid expanded bundle size")
                for item in members:
                    name = PurePosixPath(item.filename)
                    if name.is_absolute() or ".." in name.parts or "\\" in item.filename or (item.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError("Unsafe archive member")
                if bundle.testzip() is not None:
                    raise ValueError("Corrupt archive")
        except (ValueError, zipfile.BadZipFile, RuntimeError):
            self.reply(400, b"Invalid or unsafe ZIP archive.")
            return
        pipeline, workflow = key.split("--", 1)
        try:
            metadata = self.server.api(f"/api/repos/{self.server.repo_id}/pipelines/{pipeline}",
                                       {"Authorization": "Bearer " + self.server.api_token})
            if not any(item["name"] == workflow for item in metadata.get("workflows", [])):
                raise ValueError("Workflow not found")
        except (OSError, ValueError):
            self.reply(400, b"Pipeline or workflow cannot be verified with Woodpecker.")
            return
        status = self.headers.get("X-Artifact-Status", "unknown")
        record = {"key": key, "pipeline": int(pipeline), "workflow": workflow, "commit": metadata["commit"],
                  "status": status if status in ("success", "failure", "canceled") else "unknown",
                  "uploaded_at": time.time(), "bytes": length, "files": [item.filename for item in members]}
        with self.server.lock:
            if (self.server.root / f"{key}.zip").exists():
                self.reply(409, b"A bundle already exists for this pipeline and workflow.")
                return
            if sum(path.stat().st_size for path in self.server.root.glob("*.zip")) + length > 5 * 1024**3:
                self.reply(507, b"Artifact storage limit reached (5 GiB). Delete old bundles.")
                return
            # Publish ZIP last: readers only see a bundle once its metadata exists.
            for suffix, payload in (("json", json.dumps(record).encode()), ("zip", data)):
                with tempfile.NamedTemporaryFile(dir=self.server.root, delete=False) as temporary:
                    temporary.write(payload)
                    temporary_path = Path(temporary.name)
                temporary_path.replace(self.server.root / f"{key}.{suffix}")
        result = {"download": self.server.public_url + "/artifacts/download/" + key,
                  "browse": self.server.public_url + "/artifacts/"}
        self.reply(201, json.dumps(result).encode(), "application/json")


if __name__ == "__main__":
    server = ArtifactServer(("127.0.0.1", int(os.environ.get("ARTIFACT_PORT", "9080"))),
                            os.environ["ARTIFACT_ROOT"], os.environ["ARTIFACT_UPLOAD_TOKEN"],
                            os.environ["WOODPECKER_API_TOKEN"], os.environ.get("WOODPECKER_URL", "http://127.0.0.1:8000"),
                            os.environ.get("ARTIFACT_PUBLIC_URL", "https://woodpecker.thiocyanate.dev"))
    server.serve_forever()
