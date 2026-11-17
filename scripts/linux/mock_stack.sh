#!/usr/bin/env bash
# ==============================================================================
# Polyweb provider-mock dev stack (DEVELOPMENT ONLY).
#
# Runs compose.yaml + compose.dev.yaml + compose.mock.yaml as a worktree-unique
# Compose project (polyweb_wt_N -> polyweb-wtN-mock), never the live `polyweb`
# project, with this worktree's ports from .env:
#   API 127.0.0.1:$POLYWEB_API_PORT, MCP 127.0.0.1:$POLYWEB_MCP_PORT,
#   provider mock 127.0.0.1:$POLYWEB_PROVIDER_MOCK_PORT.
#
# Usage:
#   mock_stack.sh up                 build, start the mock, seed once, start api + mcp
#   mock_stack.sh down [-v]          stop this project (-v also deletes its volumes)
#   mock_stack.sh logs [service...]  show logs (add -f to follow)
#   mock_stack.sh seed               re-seed the mock; seed the Polyweb DB if missing
#                                    (after `cli reset` or `cli seed --reset`, run
#                                    `down -v` and `up`: the mock keys change)
#   mock_stack.sh cli <args...>      run polyweb-mock in the mock container
#   mock_stack.sh ps                 list this project's containers
# ==============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

die() {
    echo "[ERROR] $*" >&2
    exit 1
}

[[ -f .env ]] || die "No .env in $REPO_ROOT. Create it from .env.example with this worktree's ports."

# Read one non-secret setting: the process value wins, then the .env value.
env_value() {
    local name="$1"
    if [[ -n "${!name:-}" ]]; then
        printf '%s' "${!name}"
        return
    fi
    grep -E "^(\xEF\xBB\xBF)?${name}=" .env | tail -n 1 | cut -d= -f2- | tr -d "\r\"'" || true
}

FOLDER="$(basename "$REPO_ROOT")"
if [[ "${FOLDER,,}" =~ ^polyweb_wt_([1-9])$ ]]; then
    DEFAULT_PROJECT="polyweb-wt${BASH_REMATCH[1]}-mock"
else
    DEFAULT_PROJECT="$(printf '%s' "${FOLDER,,}" | tr '_' '-' | tr -cd 'a-z0-9-')-mock"
fi
PROJECT="${POLYWEB_MOCK_STACK_PROJECT:-$DEFAULT_PROJECT}"
[[ "$PROJECT" =~ ^[a-z0-9][a-z0-9-]*-mock$ ]] ||
    die "Compose project '$PROJECT' must end in -mock; the live project is 'polyweb'."

API_PORT="$(env_value POLYWEB_API_PORT)"
MCP_PORT="$(env_value POLYWEB_MCP_PORT)"
MOCK_PORT="$(env_value POLYWEB_PROVIDER_MOCK_PORT)"
for pair in "POLYWEB_API_PORT=$API_PORT" "POLYWEB_MCP_PORT=$MCP_PORT" \
    "POLYWEB_PROVIDER_MOCK_PORT=$MOCK_PORT"; do
    name="${pair%%=*}"
    port="${pair#*=}"
    [[ "$port" =~ ^[0-9]+$ ]] || die "$name is not set in .env (see the AGENTS.md port table)."
    case "$port" in
        3000 | 3100 | 8000 | 8001 | 8080 | 8090 | 8100 | 8101 | 9000 | 9090)
            die "$name=$port belongs to another service on this host; use the worktree port." ;;
    esac
done

export POLYWEB_MOCK_STACK_PROJECT="$PROJECT"
export POLYWEB_API_PORT="$API_PORT" POLYWEB_MCP_PORT="$MCP_PORT"
export POLYWEB_PROVIDER_MOCK_PORT="$MOCK_PORT"

MOCK_DB=/data/polyweb.mock-dev.db
SEED_COMMAND="test -e $MOCK_DB && echo 'Polyweb mock dev DB exists; seed skipped.' || \
uv run --no-sync python scripts/seed_dev.py --database $MOCK_DB \
--keys-from-mock http://provider-mock:8212"

compose() {
    docker compose -p "$PROJECT" -f compose.yaml -f compose.dev.yaml -f compose.mock.yaml "$@"
}

seed_polyweb() {
    # Seed before api starts: the API creates the database file on startup.
    compose run --rm --no-deps api sh -c "$SEED_COMMAND"
}

COMMAND="${1:-}"
[[ -n "$COMMAND" ]] && shift
case "$COMMAND" in
    up)
        echo "[INFO] Project $PROJECT: API $API_PORT, MCP $MCP_PORT, mock $MOCK_PORT (127.0.0.1)."
        compose build provider-mock api
        compose up -d --wait provider-mock
        seed_polyweb
        compose up -d --wait api mcp
        echo "[OK] API http://127.0.0.1:$API_PORT  MCP http://127.0.0.1:$MCP_PORT/mcp"
        echo "     Mock http://127.0.0.1:$MOCK_PORT/_mock/health  Log in as admin1@example.com."
        ;;
    down) compose down "$@" ;;
    logs) compose logs "$@" ;;
    ps) compose ps "$@" ;;
    seed)
        compose exec provider-mock /app/.venv/bin/polyweb-mock seed "$@"
        seed_polyweb
        ;;
    cli) compose exec provider-mock /app/.venv/bin/polyweb-mock "$@" ;;
    *)
        sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
        exit 1
        ;;
esac
