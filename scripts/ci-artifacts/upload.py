#!/usr/bin/env python3
"""Package report files and upload them before the disposable workspace disappears."""
import argparse
import json
import os
import tempfile
import urllib.request
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    files = set()
    for name in args.paths:
        path = root / name
        if path.is_dir():
            files.update(item for item in path.rglob("*") if item.is_file() and not item.is_symlink())
        elif path.is_file() and not path.is_symlink():
            files.add(path)
    files = {path for path in files if path.resolve().is_relative_to(root)}
    with tempfile.TemporaryFile() as temporary:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(files):
                # Resolve intermediate symlinks too; never package outside the workspace.
                if path.resolve().is_relative_to(root):
                    bundle.write(path, path.relative_to(root))
            manifest = {"pipeline": os.environ["CI_PIPELINE_NUMBER"], "workflow": os.environ["CI_WORKFLOW_NAME"],
                        "commit": os.environ.get("CI_COMMIT_SHA"), "status": os.environ.get("CI_PIPELINE_STATUS"),
                        "report_files": len(files), "note": "Report files can be absent after an early test failure."}
            bundle.writestr("artifact-manifest.json", json.dumps(manifest, indent=2))
        temporary.seek(0)
        data = temporary.read()
    # Upload over the private encrypted tailnet, independently of browser DNS.
    base = os.environ.get("CI_ARTIFACT_URL", "http://100.64.0.2:9010").rstrip("/")
    key = os.environ["CI_PIPELINE_NUMBER"] + "--" + os.environ["CI_WORKFLOW_NAME"]
    request = urllib.request.Request(base + "/artifacts/upload/" + key, data=data, method="POST", headers={
        "Authorization": "Bearer " + os.environ["CI_ARTIFACT_UPLOAD_TOKEN"],
        "Content-Type": "application/zip", "X-Artifact-Status": os.environ.get("CI_PIPELINE_STATUS", "unknown")})
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.load(response)
    print(f"Uploaded {len(files)} report files. Download (Woodpecker login required): {result['download']}", flush=True)
    print(f"Browse and delete report bundles: {result['browse']}", flush=True)


if __name__ == "__main__":
    main()
