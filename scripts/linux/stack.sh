#!/usr/bin/env bash
# ==============================================================================
# Polyweb worktree stacks (DEVELOPMENT ONLY). pd, the deployed stack, is not
# run from here.
#
#   npd  compose.yaml + docker/npd/compose.yaml: worktree source, real providers.
#   dev  ... + docker/dev/compose.yaml: worktree source, every provider call
#        goes to the provider mock.
#
# Each runs as a worktree-unique Compose project (polyweb_wt_N ->
# polyweb-wtN-npd or polyweb-wtN-dev), never the pd `polyweb` project, with this
# worktree's ports from .env on 127.0.0.1: POLYWEB_API_PORT, POLYWEB_MCP_PORT,
# and for dev POLYWEB_PROVIDER_MOCK_PORT.
#
# Usage:
#   stack.sh npd|dev up                 build and start (dev: start the mock and seed once)
#   stack.sh npd|dev down [-v]          stop this project (-v also deletes its volumes)
#   stack.sh npd|dev logs [service...]  show logs (add -f to follow)
#   stack.sh npd|dev ps                 list this project's containers
#   stack.sh dev seed                   re-seed the mock; seed the Polyweb DB if missing
#                                       (after `cli reset` or `cli seed --reset`, run
#                                       `down -v` and `up`: the mock keys change)
#   stack.sh dev cli <args...>          run polyweb-mock in the mock container
#   stack.sh dev live [behave args...]  dev-live: the @live Behave scenarios on this
#                                       host, every provider call answered by this
#                                       stack's mock (faults you applied stay active)
# ==============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

die() {
    echo "[ERROR] $*" >&2
    exit 1
}

usage() {
    sed -n '2,27p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 1
}

STACK="${1:-}"
[[ "$STACK" == "npd" || "$STACK" == "dev" ]] || usage
shift
COMMAND="${1:-}"
[[ -n "$COMMAND" ]] || usage
shift

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
    DEFAULT_PROJECT="polyweb-wt${BASH_REMATCH[1]}-$STACK"
else
    DEFAULT_PROJECT="$(printf '%s' "${FOLDER,,}" | tr '_' '-' | tr -cd 'a-z0-9-')-$STACK"
fi
PROJECT="${POLYWEB_STACK_PROJECT:-$DEFAULT_PROJECT}"
[[ "$PROJECT" =~ ^[a-z0-9][a-z0-9-]*-${STACK}$ ]] ||
    die "Compose project '$PROJECT' must end in -$STACK; the pd project is 'polyweb'."

PORT_NAMES=(POLYWEB_API_PORT POLYWEB_MCP_PORT)
[[ "$STACK" == "dev" ]] && PORT_NAMES+=(POLYWEB_PROVIDER_MOCK_PORT)
for name in "${PORT_NAMES[@]}"; do
    port="$(env_value "$name")"
    [[ "$port" =~ ^[0-9]+$ ]] || die "$name is not set in .env (see the AGENTS.md port table)."
    case "$port" in
        3000 | 3100 | 8000 | 8001 | 8080 | 8090 | 8100 | 8101 | 9000 | 9090)
            die "$name=$port belongs to another service on this host; use the worktree port." ;;
    esac
    export "$name=$port"
done
export POLYWEB_STACK_PROJECT="$PROJECT"

COMPOSE_FILES=(-f compose.yaml -f docker/npd/compose.yaml)
[[ "$STACK" == "dev" ]] && COMPOSE_FILES+=(-f docker/dev/compose.yaml)

compose() {
    docker compose -p "$PROJECT" "${COMPOSE_FILES[@]}" "$@"
}

MOCK_DB=/data/polyweb.mock-dev.db
SEED_COMMAND="test -e $MOCK_DB && echo 'Polyweb mock dev DB exists; seed skipped.' || \
uv run --no-sync python scripts/seed_dev.py --database $MOCK_DB \
--keys-from-mock http://provider-mock:8212"

seed_polyweb() {
    # Seed before api starts: the API creates the database file on startup.
    compose run --rm --no-deps api sh -c "$SEED_COMMAND"
}

require_dev() {
    [[ "$STACK" == "dev" ]] || die "'$COMMAND' needs the dev stack (it uses the provider mock)."
}

# dev-live: the same @live scenarios the live run sends to the real providers,
# run on this host with the mock's keys and every provider call rerouted to
# this stack's mock. Mirrors the provider-mock Woodpecker workflow.
dev_live() {
    compose build provider-mock
    compose up -d --wait provider-mock
    local line keys
    keys="$(compose exec -T provider-mock /app/.venv/bin/polyweb-mock export-keys --format dotenv)"
    while IFS= read -r line; do
        line="${line%$'\r'}"
        [[ -z "$line" ]] && continue
        [[ "$line" =~ ^[A-Z][A-Z0-9_]*_API_KEY=[A-Za-z0-9._-]+$ ]] ||
            die "Unexpected export-keys line from the mock: ${line%%=*}"
        export "${line?}"
    done <<<"$keys"
    export POLYWEB_PROVIDER_MOCK_URL="http://127.0.0.1:$POLYWEB_PROVIDER_MOCK_PORT"
    export POLYWEB_TEST_PROVIDER_MOCK=1
    export POLYWEB_RUN_LIVE=1
    echo "[INFO] dev-live: @live scenarios against mock $POLYWEB_PROVIDER_MOCK_URL ($PROJECT)."
    uv run polyweb-db upgrade
    uv run behave --tags="@live and not @latency" "$@"
}

case "$COMMAND" in
    up)
        if [[ "$STACK" == "dev" ]]; then
            echo "[INFO] Project $PROJECT: API $POLYWEB_API_PORT, MCP $POLYWEB_MCP_PORT, mock $POLYWEB_PROVIDER_MOCK_PORT (127.0.0.1)."
            compose build provider-mock api
            compose up -d --wait provider-mock
            seed_polyweb
            compose up -d --wait api mcp
            echo "[OK] API http://127.0.0.1:$POLYWEB_API_PORT  MCP http://127.0.0.1:$POLYWEB_MCP_PORT/mcp"
            echo "     Mock http://127.0.0.1:$POLYWEB_PROVIDER_MOCK_PORT/_mock/health  Log in as admin1@example.com."
        else
            echo "[INFO] Project $PROJECT: API $POLYWEB_API_PORT, MCP $POLYWEB_MCP_PORT (127.0.0.1), real providers."
            compose build api
            compose up -d --wait api mcp
            echo "[OK] API http://127.0.0.1:$POLYWEB_API_PORT  MCP http://127.0.0.1:$POLYWEB_MCP_PORT/mcp"
            echo "     Provider keys live in this project's vault; add them in the dashboard (pnpm dev)."
        fi
        ;;
    down) compose down "$@" ;;
    logs) compose logs "$@" ;;
    ps) compose ps "$@" ;;
    seed)
        require_dev
        compose exec provider-mock /app/.venv/bin/polyweb-mock seed "$@"
        seed_polyweb
        ;;
    cli)
        require_dev
        compose exec provider-mock /app/.venv/bin/polyweb-mock "$@"
        ;;
    live)
        require_dev
        dev_live "$@"
        ;;
    *) usage ;;
esac
