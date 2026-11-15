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
# Stubbed scenarios run fully parallel across Playwright workers (see
# playwright.config.ts). The default fills the spot worker but never exceeds
# its cores; PLAYWRIGHT_WORKERS overrides it.
cores=$(nproc)
default_workers=$(( cores < 12 ? cores : 12 ))
export PLAYWRIGHT_WORKERS="${PLAYWRIGHT_WORKERS:-$default_workers}"
echo "Playwright workers: ${PLAYWRIGHT_WORKERS} (nproc ${cores})"
grep_args=(--grep "${PLAYWRIGHT_GREP:-@smoke}")
if [[ -n "${PLAYWRIGHT_GREP_INVERT:-}" ]]; then
  grep_args+=(--grep-invert "$PLAYWRIGHT_GREP_INVERT")
fi
for project in chromium chromium-serial; do
  echo "Selected in ${project}: $(pnpm exec playwright test --list --project "$project" "${grep_args[@]}" 2>/dev/null | tail -n 1)"
done

# Pass 1: everything except `@serial`, in parallel. An empty selection fails.
# Pass 2: the `@serial` scenarios on one worker, only after pass 1 has
# finished, so their fixed delay windows never compete with other workers.
# The gate selection may hold no `@serial` scenario, so pass 2 may be empty.
status=0
PLAYWRIGHT_HTML_OUTPUT_DIR=playwright-report \
  pnpm exec playwright test --project chromium "${grep_args[@]}" --reporter=line --reporter=html || status=$?
PLAYWRIGHT_HTML_OUTPUT_DIR=playwright-report/serial \
  pnpm exec playwright test --project chromium-serial --workers 1 --pass-with-no-tests \
    "${grep_args[@]}" --reporter=line --reporter=html || status=$?
exit "$status"
