#!/usr/bin/env python3
"""Read generic Gitea package metadata and download artifacts."""
import argparse
import json
import os
import shlex
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parent.parent
DOWNLOAD_DIR = ROOT / '.gitea-packages'


def settings():
    values = {}
    env_file = ROOT / '.env'
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.removeprefix('export ').split('=', 1)
            if key.strip() in ('GITEA_BASE_URL', 'GITEA_DOWNLOAD_TOKEN'):
                parts = shlex.split(value, comments=True)
                values[key.strip()] = parts[0] if parts else ''
    url = os.environ.get('GITEA_BASE_URL', values.get('GITEA_BASE_URL', '')).rstrip('/')
    token = os.environ.get('GITEA_DOWNLOAD_TOKEN', values.get('GITEA_DOWNLOAD_TOKEN', '')).strip()
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('GITEA_BASE_URL must be an HTTPS URL without credentials, query, or fragment')
    if not token:
        raise ValueError('GITEA_DOWNLOAD_TOKEN is missing')
    return url, token


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner', default='polyweb')
    sub = parser.add_subparsers(dest='action', required=True)
    listing = sub.add_parser('list', help='List or search generic packages')
    listing.add_argument('--query', default='')
    listing.add_argument('--page', type=int, default=1)
    listing.add_argument('--limit', type=int, default=50)
    versions = sub.add_parser('versions', help='List package versions')
    versions.add_argument('name')
    versions.add_argument('--page', type=int, default=1)
    versions.add_argument('--limit', type=int, default=50)
    for action in ('files', 'get', 'download'):
        cmd = sub.add_parser(action)
        cmd.add_argument('name')
        cmd.add_argument('version')
        if action == 'download':
            cmd.add_argument('filename')
    args = parser.parse_args()
    if hasattr(args, 'page') and (args.page < 1 or args.limit < 1):
        parser.error('page and limit must be positive')
    if args.action == 'download' and (args.filename in ('', '.', '..') or '/' in args.filename or '\\' in args.filename):
        parser.error('filename must be a single file name')
    base, token = settings()
    part = lambda value: quote(value, safe='')
    owner = part(args.owner)
    if args.action == 'list':
        path = f'/api/v1/packages/{owner}?' + urlencode({'type': 'generic', 'q': args.query, 'page': args.page, 'limit': args.limit})
    else:
        path = f'/api/v1/packages/{owner}/generic/{part(args.name)}'
        if args.action == 'versions':
            path += '?' + urlencode({'page': args.page, 'limit': args.limit})
        else:
            path += '/' + part(args.version)
            if args.action == 'files':
                path += '/files'
            elif args.action == 'download':
                path = f'/api/packages/{owner}/generic/{part(args.name)}/{part(args.version)}/{part(args.filename)}'
    request = Request(base + path, headers={'Authorization': 'token ' + token, 'Accept': 'application/octet-stream' if args.action == 'download' else 'application/json'})
    with build_opener(NoRedirect).open(request, timeout=60) as response:
        if args.action != 'download':
            print(json.dumps(json.load(response), indent=2))
        else:
            DOWNLOAD_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
            target = DOWNLOAD_DIR / args.filename
            if target.exists():
                raise ValueError('output already exists')
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.gitea-download-', delete=False) as temp:
                    temp_path = Path(temp.name)
                    while chunk := response.read(1024 * 1024):
                        temp.write(chunk)
                os.link(temp_path, target)
            finally:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
            print(f'Downloaded to {target}')


if __name__ == '__main__':
    try:
        main()
    except HTTPError as exc:
        print(f'Gitea request failed: HTTP {exc.code}', file=sys.stderr)
        sys.exit(1)
    except (ValueError, OSError, URLError) as exc:
        print(f'Gitea request failed: {exc}', file=sys.stderr)
        sys.exit(1)
