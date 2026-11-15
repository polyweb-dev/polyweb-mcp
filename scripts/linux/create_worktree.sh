#!/usr/bin/env bash
# ==============================================================================
# Polyweb Generic Worktree Setup Script (Linux/macOS port of
# scripts/windows/create_worktree.bat)
# Usage:
#   create_worktree.sh <branch-name> [mode|folder-name] [mode] [options]
# ==============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN_REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"

usage() {
    cat <<'EOF'

Usage:
  create_worktree.sh <branch-name> [mode|folder-name] [mode] [options]

Modes:
  docker (or bare, none)    - Fast passthrough: git checkout + .env only (skips uv & pnpm)
  backend (or be)           - Setup backend only (uv sync + polyweb-db upgrade)
  ui (or frontend, fe)      - Setup UI only (pnpm install + bddgen)
  full (or fullstack)       - Setup both backend and UI [default]

Options:
  --base <ref>   Base ref for a NEW branch (default: main; ignored if the branch exists)
  --slot <N>     Worktree slot 1-9; sets .env ports MCP 82N0 / API 82N1 / VITE 5174+N
  --copy-db      Copy the main checkout's polyweb.db (contains credentials/history).
                 A copy works only if the main database is already at the alpha
                 baseline; otherwise the new worktree refuses it with reset steps.

Examples:
  create_worktree.sh my-feature docker
  create_worktree.sh my-feature backend --base develop
  create_worktree.sh my-feature polyweb_wt_1 backend
  create_worktree.sh my-feature custom-folder-name docker --slot 3
EOF
    exit 1
}

# Map a mode alias to its canonical mode; prints nothing for unknown values.
resolve_mode() {
    case "${1,,}" in
        backend|be) echo backend ;;
        ui|frontend|fe) echo ui ;;
        full|fullstack) echo full ;;
        docker|bare|none) echo docker ;;
    esac
}

if [[ $# -eq 0 || -z "${1:-}" ]]; then
    echo "[ERROR] Missing branch name argument."
    usage
fi

BRANCH="$1"
shift

MODE="full"
FOLDER=""
BASE="main"
BASE_GIVEN=0
SLOT=""
COPY_DB=0
POS=()

while [[ $# -gt 0 ]]; do
    case "${1,,}" in
        --base)
            if [[ -z "${2:-}" ]]; then
                echo "[ERROR] --base requires a git ref (branch, tag, or commit)."
                usage
            fi
            BASE="$2"; BASE_GIVEN=1; shift 2 ;;
        --slot)
            if [[ -z "${2:-}" ]]; then
                echo "[ERROR] --slot requires a worktree slot number 1-9."
                usage
            fi
            SLOT="$2"; shift 2 ;;
        --copy-db)
            COPY_DB=1; shift ;;
        --*)
            echo "[ERROR] Unknown option '$1'."
            usage ;;
        *)
            POS+=("$1"); shift ;;
    esac
done

ARG2="${POS[0]:-}"
ARG3="${POS[1]:-}"

# ARG2 is either a mode or a custom folder name (optionally followed by a mode)
if [[ -n "$ARG2" ]]; then
    m="$(resolve_mode "$ARG2")"
    if [[ -n "$m" ]]; then
        MODE="$m"
    else
        FOLDER="$ARG2"
        m="$(resolve_mode "$ARG3")"
        [[ -n "$m" ]] && MODE="$m"
    fi
fi

if [[ -z "$FOLDER" ]]; then
    # Replace slashes in the branch name for folder safety
    FOLDER="polyweb-${BRANCH//\//-}"
fi

# ------------------------------------------------------------------------------
# Validate --slot: must be a single digit 1-9 (slot 0 is the main checkout)
# ------------------------------------------------------------------------------
if [[ -n "$SLOT" && ! "$SLOT" =~ ^[1-9]$ ]]; then
    echo "[ERROR] Invalid --slot '$SLOT': expected an integer 1-9 (slot 0 is the main checkout)."
    exit 1
fi

# Detect the slot implied by a 'polyweb_wt_N' folder name (N = digit 1-9)
FOLDER_SLOT=""
if [[ "${FOLDER,,}" =~ ^polyweb_wt_([1-9])$ ]]; then
    FOLDER_SLOT="${BASH_REMATCH[1]}"
fi

if [[ -n "$SLOT" ]]; then
    if [[ -n "$FOLDER_SLOT" && "$SLOT" != "$FOLDER_SLOT" ]]; then
        echo "[ERROR] --slot $SLOT conflicts with folder name '$FOLDER' (implies slot $FOLDER_SLOT)."
        exit 1
    fi
elif [[ -n "$FOLDER_SLOT" ]]; then
    SLOT="$FOLDER_SLOT"
    echo "[INFO] Worktree slot $SLOT inferred from folder name '$FOLDER'."
fi

# Run from the repository root so relative paths match the Windows script
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
    echo "[ERROR] Must be run inside a Git repository."
    exit 1
}
cd "$REPO_ROOT" || exit 1

# ------------------------------------------------------------------------------
# Resolve the branch state and validate --base BEFORE creating anything
# ------------------------------------------------------------------------------
BRANCH_STATE="new"
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    BRANCH_STATE="local"
elif git show-ref --verify --quiet "refs/remotes/origin/$BRANCH"; then
    BRANCH_STATE="remote"
fi

if [[ "$BRANCH_STATE" == "new" ]]; then
    if ! git rev-parse --verify --quiet "${BASE}^{commit}" >/dev/null 2>&1; then
        echo "[ERROR] --base ref '$BASE' does not resolve to a commit."
        exit 1
    fi
elif [[ "$BASE_GIVEN" == "1" ]]; then
    echo "[INFO] Branch '$BRANCH' already exists; --base '$BASE' is ignored."
fi

# Set KEY=VALUE in an env file: replace an existing line or append one.
# Preserves a UTF-8 BOM and CRLF line endings if present.
set_env_var() {
    local file="$1" key="$2" value="$3"
    if grep -qE "^(\xEF\xBB\xBF)?${key}=" "$file"; then
        sed -i -E "s/^(\xEF\xBB\xBF)?${key}=[^\r]*/\1${key}=${value}/" "$file"
    else
        if [[ -s "$file" && -n "$(tail -c1 "$file")" ]]; then
            printf '\n' >>"$file"
        fi
        printf '%s=%s\n' "$key" "$value" >>"$file"
    fi
}

TARGET_PATH="../$FOLDER"
BASE_USED="$BASE"
PORTS_USED="unchanged"
DB_USED="fresh"

echo
echo "-------------------------------------------------------"
echo "Setting up worktree: $BRANCH"
echo "Path: $TARGET_PATH"
echo "Target mode: [$MODE]"
echo "-------------------------------------------------------"

# 1. Create Git Worktree (checks local, then remote, else creates new from --base)
if [[ "$BRANCH_STATE" == "local" ]]; then
    BASE_USED="existing branch"
    echo "[1/6] Checking out existing local branch '$BRANCH' in worktree '$TARGET_PATH'..."
    git worktree add "$TARGET_PATH" "$BRANCH"
elif [[ "$BRANCH_STATE" == "remote" ]]; then
    BASE_USED="existing branch"
    echo "[1/6] Checking out remote branch 'origin/$BRANCH' in worktree '$TARGET_PATH'..."
    git worktree add --track -b "$BRANCH" "$TARGET_PATH" "origin/$BRANCH"
else
    echo "[1/6] Branch not found locally or remotely. Creating new branch '$BRANCH' from '$BASE'..."
    git worktree add -b "$BRANCH" "$TARGET_PATH" "$BASE"
fi
if [[ $? -ne 0 ]]; then
    echo "[ERROR] Failed to create git worktree for '$BRANCH'."
    exit 1
fi

# 2. Copy .env, assign slot ports, and optionally copy the database
if [[ -f ".env" ]]; then
    echo "[2/6] Copying root .env file to '$TARGET_PATH/.env'..."
    cp -f ".env" "$TARGET_PATH/.env"
    if [[ -n "$SLOT" ]]; then
        MCP_PORT=$((8200 + SLOT * 10))
        API_PORT=$((8200 + SLOT * 10 + 1))
        VITE_PORT=$((5174 + SLOT))
        echo "[2/6] Assigning slot $SLOT ports: POLYWEB_MCP_PORT=$MCP_PORT, POLYWEB_API_PORT=$API_PORT, VITE_PORT=$VITE_PORT"
        if ! { set_env_var "$TARGET_PATH/.env" POLYWEB_MCP_PORT "$MCP_PORT" &&
               set_env_var "$TARGET_PATH/.env" POLYWEB_API_PORT "$API_PORT" &&
               set_env_var "$TARGET_PATH/.env" VITE_PORT "$VITE_PORT"; }; then
            echo "[ERROR] Failed to write worktree ports into '$TARGET_PATH/.env'."
            exit 1
        fi
        PORTS_USED="MCP=$MCP_PORT, API=$API_PORT, VITE=$VITE_PORT"
    else
        echo "[WARNING] No slot resolved for folder '$FOLDER': .env ports were copied"
        echo "          unchanged from the main checkout and will collide if both run at once."
        echo "          Re-run with '--slot N' or use a 'polyweb_wt_N' folder name."
    fi
else
    echo "[2/6] Warning: No .env file found in root repository. Skipping copy."
    echo "[WARNING] No .env in the main checkout - worktree ports cannot be assigned."
fi

if [[ "$COPY_DB" == "1" ]]; then
    if [[ -f "polyweb.db" ]]; then
        echo "[2/6] Copying polyweb.db to '$TARGET_PATH/polyweb.db'..."
        cp -f "polyweb.db" "$TARGET_PATH/polyweb.db"
        DB_USED="copied"
        echo "[WARNING] The copied polyweb.db contains stored provider credentials"
        echo "          and real request history - treat it as sensitive."
        echo "[INFO] The copy opens only if it is at the alpha baseline revision;"
        echo "       an older database is refused with reset instructions."
    else
        echo "[2/6] [INFO] --copy-db given but no polyweb.db found in main checkout. Skipping copy."
    fi
else
    echo "[2/6] [INFO] polyweb.db is NOT copied - use --copy-db to opt in;"
    echo "          a fresh database will be created by 'polyweb-db upgrade'."
fi

# 3. Backend Setup (uv sync + database migration)
if [[ "$MODE" == "ui" || "$MODE" == "docker" ]]; then
    echo "[3/6] [SKIP] Mode is '$MODE' - skipping backend 'uv sync'."
else
    echo "[3/6] Initializing backend virtualenv with 'uv sync' in '$TARGET_PATH'..."
    if ! (cd "$TARGET_PATH" && uv sync); then
        echo "[ERROR] 'uv sync' failed in '$TARGET_PATH'."
        exit 1
    fi
    echo "[3/6] Ensuring database schema is current with 'uv run polyweb-db upgrade'..."
    if ! (cd "$TARGET_PATH" && uv run polyweb-db upgrade); then
        echo "[WARNING] Database upgrade reported an issue in '$TARGET_PATH'."
    fi
fi

# 4. UI Setup (pnpm install + bddgen)
UI_ENV_LOCAL="$MAIN_REPO/polyweb-ui/.env.local"
if [[ "$MODE" == "backend" ]]; then
    echo "[4/6] [SKIP] Mode is 'backend' - skipping UI dependency setup."
elif [[ "$MODE" == "docker" ]]; then
    echo "[4/6] [SKIP] Mode is 'docker' - skipping UI dependencies."
    if [[ -d "$TARGET_PATH/polyweb-ui" && -f "$UI_ENV_LOCAL" ]]; then
        echo "[4/6] Copying UI .env.local to '$TARGET_PATH/polyweb-ui/.env.local'..."
        cp -f "$UI_ENV_LOCAL" "$TARGET_PATH/polyweb-ui/.env.local"
    fi
else
    if [[ -f "$TARGET_PATH/polyweb-ui/package.json" ]]; then
        echo "[4/6] Setting up UI dependencies in '$TARGET_PATH/polyweb-ui'..."
        [[ -f "$UI_ENV_LOCAL" ]] && cp -f "$UI_ENV_LOCAL" "$TARGET_PATH/polyweb-ui/.env.local"
        if ! (cd "$TARGET_PATH/polyweb-ui" && pnpm install --store-dir "$MAIN_REPO/.pnpm-store"); then
            echo "[ERROR] 'pnpm install' failed in '$TARGET_PATH/polyweb-ui'."
            exit 1
        fi
        echo "[4/6] Generating Playwright BDD specs with 'pnpm bddgen'..."
        (cd "$TARGET_PATH/polyweb-ui" && pnpm bddgen)
    else
        echo "[4/6] [INFO] No polyweb-ui directory found on this branch. Skipping UI setup."
    fi
fi

# 5. CodeGraph Initialization
if command -v codegraph >/dev/null 2>&1; then
    echo "[5/6] Initializing CodeGraph index in '$TARGET_PATH' with 'codegraph init -y'..."
    (cd "$TARGET_PATH" && codegraph init -y)
else
    echo "[5/6] [SKIP] 'codegraph' CLI not found. Skipping CodeGraph initialization."
fi

echo
echo "-------------------------------------------------------"
echo "[OK] Worktree setup complete."
echo "  Branch : $BRANCH"
echo "  Base   : $BASE_USED"
echo "  Path   : $TARGET_PATH"
echo "  Mode   : $MODE"
echo "  Slot   : ${SLOT:-none}"
echo "  Ports  : $PORTS_USED"
echo "  DB     : $DB_USED"
echo "-------------------------------------------------------"
exit 0
