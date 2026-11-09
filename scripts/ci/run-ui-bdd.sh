#!/usr/bin/env bash
# Run stubbed and visual UI scenarios against a disposable local API.
set -euo pipefail

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
TEMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/polyweb-ui-bdd.XXXXXX")
API_PID=
UV_BIN=${UV_BIN:-uv}

cleanup() {
  status=$?
  if [[ -n "$API_PID" ]]; then
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
  if [[ $status -ne 0 && -f "$TEMP_DIR/api.log" ]]; then
    echo "--- API log ---"
    cat "$TEMP_DIR/api.log"
    echo "--- End API log ---"
  fi
  rm -rf "$TEMP_DIR"
  exit "$status"
}
trap cleanup EXIT

cd "$REPO_ROOT"
test -f .env || cp .env.example .env
export POLYWEB_DB="$TEMP_DIR/polyweb.db"
export POLYWEB_AUTH_JWT_SECRET="${POLYWEB_AUTH_JWT_SECRET:-ui-bdd-test-secret-material-0123456789abcdef}"
export POLYWEB_ENCRYPTION_KEY="${POLYWEB_ENCRYPTION_KEY:-ui-bdd-encryption-test-material-0123456789}"

"$UV_BIN" run --no-sync polyweb-db upgrade
"$UV_BIN" run --no-sync polyweb-api --host 127.0.0.1 --port 8001 > "$TEMP_DIR/api.log" 2>&1 &
API_PID=$!

api_ready=false
for _ in $(seq 1 30); do
  if curl --fail --silent --show-error http://127.0.0.1:8001/openapi.json > /dev/null; then
    api_ready=true
    break
  fi
  sleep 1
done
if [[ "$api_ready" != true ]]; then
  echo "UI BDD API did not become ready on port 8001." >&2
  exit 1
fi

cd polyweb-ui
pnpm bddgen
grep_args=(--grep "${PLAYWRIGHT_GREP:-@smoke|@visual}")
if [[ -n "${PLAYWRIGHT_GREP_INVERT:-}" ]]; then
  grep_args+=(--grep-invert "$PLAYWRIGHT_GREP_INVERT")
fi
pnpm exec playwright test "${grep_args[@]}" --reporter=line --reporter=html
