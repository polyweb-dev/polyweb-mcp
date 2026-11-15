#!/usr/bin/env bash
# ==============================================================================
# Polyweb Generic Worktree Cleanup Script (Linux/macOS port of
# scripts/windows/delete_worktree.bat)
# Usage:
#   delete_worktree.sh <branch-or-folder|--all> [--force|-f] [--keep-branch|-k] [--yes|-y]
#
# Examples:
#   delete_worktree.sh quota-fix
#   delete_worktree.sh ui-cq-refactor --force
#   delete_worktree.sh polyweb-quota-fix --keep-branch
#   delete_worktree.sh --all --force
# ==============================================================================
set -uo pipefail

usage() {
    echo "[ERROR] Missing branch, worktree folder name, or --all option."
    cat <<'EOF'

Usage:
  delete_worktree.sh <branch-or-folder> [options]
  delete_worktree.sh --all [options]

Options:
  -a, --all           Delete ALL existing worktrees (except main repository)
  -f, --force         Force removal [even if dirty or unmerged]
  -k, --keep-branch   Delete worktree directory and registration, but keep the branch
  --clean-images      Also remove locally built Docker images (--rmi local)
  -y, --yes           Skip confirmation prompt

Examples:
  delete_worktree.sh quota-fix
  delete_worktree.sh ui-cq-refactor --force
  delete_worktree.sh polyweb-quota-fix --keep-branch
  delete_worktree.sh feature/AllSearchRanked --force --clean-images
  delete_worktree.sh --all --force
EOF
    exit 1
}

TARGET=""
FORCE=0
KEEP_BRANCH=0
AUTO_YES=0
CLEAN_IMAGES=0
DELETE_ALL=0

while [[ $# -gt 0 ]]; do
    case "${1,,}" in
        --help|-h) usage ;;
        --all|-a) DELETE_ALL=1; TARGET="ALL" ;;
        --force|-f) FORCE=1; AUTO_YES=1 ;;
        --keep-branch|-k) KEEP_BRANCH=1 ;;
        --clean-images|--rmi) CLEAN_IMAGES=1 ;;
        --yes|-y) AUTO_YES=1 ;;
        *) [[ -z "$TARGET" ]] && TARGET="$1" ;;
    esac
    shift
done

[[ -z "$TARGET" ]] && usage

confirm() {
    local reply
    read -r -p "$1 [y/N]: " reply
    [[ "${reply,,}" == "y" || "${reply,,}" == "yes" ]]
}

branch_exists() {
    git show-ref --verify --quiet "refs/heads/$1"
}

# Stop processes holding the worktree open (CodeGraph daemons and anything
# whose command line references the worktree path).
release_processes() {
    local wt="${1%/}" daemons="$HOME/.codegraph/daemons" f root pid
    if [[ -d "$daemons" ]] && command -v python3 >/dev/null 2>&1; then
        for f in "$daemons"/*.json; do
            [[ -f "$f" ]] || continue
            read -r root pid < <(python3 -I -c '
import json, sys
try:
    c = json.load(open(sys.argv[1]))
    print(c.get("root") or "", c.get("pid") or "")
except Exception:
    print("", "")
' "$f" 2>/dev/null)
            [[ -z "$root" ]] && continue
            if [[ "${root%/}" == "$wt" || "$root" == *"$wt"* ]]; then
                [[ -n "$pid" ]] && kill -9 "$pid" 2>/dev/null
                rm -f "$f"
            fi
        done
    fi
    local p cmd
    for p in /proc/[0-9]*; do
        pid="${p#/proc/}"
        [[ "$pid" == "$$" || "$pid" == "$PPID" || "$pid" == "$BASHPID" ]] && continue
        cmd="$(tr '\0' ' ' <"$p/cmdline" 2>/dev/null)" || continue
        [[ -n "$cmd" && "$cmd" == *"$wt"* ]] && kill -9 "$pid" 2>/dev/null
    done
}

# ==============================================================================
# Core Cleanup Execution Routine: execute_deletion <path> <branch>
# ==============================================================================
execute_deletion() {
    local w_path="$1" w_branch="$2"

    # Step 1: Tear down Docker Compose resources (containers, networks, volumes)
    if [[ -z "$w_path" ]]; then
        echo "[1/6] [SKIP] No worktree directory found."
    elif [[ ! -d "$w_path" ]]; then
        echo "[1/6] [SKIP] Worktree directory does not exist."
    elif ! command -v docker >/dev/null 2>&1; then
        echo "[1/6] [SKIP] Docker CLI not found."
    elif [[ -f "$w_path/compose.yaml" || -f "$w_path/docker-compose.yml" ]]; then
        echo "[1/6] Tearing down Docker Compose containers, networks, and volumes..."
        if [[ "$CLEAN_IMAGES" == "1" ]]; then
            (cd "$w_path" && docker compose down --volumes --remove-orphans --rmi local >/dev/null 2>&1)
        else
            (cd "$w_path" && docker compose down --volumes --remove-orphans >/dev/null 2>&1)
        fi
    else
        echo "[1/6] [SKIP] No Docker Compose file found in worktree."
    fi

    # Step 2: Unregister Worktree from Git
    if [[ -n "$w_path" ]]; then
        echo "[2/6] Unregistering worktree from Git..."
        if [[ "$FORCE" == "1" ]]; then
            git worktree remove --force "$w_path" >/dev/null 2>&1
        else
            git worktree remove "$w_path" >/dev/null 2>&1
        fi
    else
        echo "[2/6] [SKIP] No registered worktree path found in Git."
    fi

    # Step 3: Release CodeGraph Daemons, Locks, and Background Handles
    if [[ -z "$w_path" ]]; then
        echo "[3/6] [SKIP] No worktree directory found."
    elif [[ ! -d "$w_path" ]]; then
        echo "[3/6] [SKIP] Worktree directory does not exist."
    else
        echo "[3/6] Releasing CodeGraph locks and background processes..."
        release_processes "$w_path"
        if [[ -d "$w_path/.codegraph" ]] && command -v codegraph >/dev/null 2>&1; then
            codegraph uninit --force "$w_path" >/dev/null 2>&1
        fi
    fi

    # Step 4: Clean up filesystem leftovers (node_modules, .venv, .stryker-tmp, etc.)
    if [[ -z "$w_path" ]]; then
        echo "[4/6] [SKIP] No worktree directory to remove."
    elif [[ -d "$w_path" ]]; then
        echo "[4/6] Removing filesystem directory and leftovers '$w_path'..."
        rm -rf -- "$w_path" 2>/dev/null
        if [[ -d "$w_path" ]]; then
            sleep 1
            rm -rf -- "$w_path" 2>/dev/null
        fi
        if [[ -d "$w_path" ]]; then
            echo "[WARNING] Some files in '$w_path' could not be deleted."
            echo "          Please close any open editors/terminals using this directory."
        else
            echo "[OK] Worktree directory removed completely."
        fi
    else
        echo "[4/6] [OK] Directory already removed from disk."
    fi

    # Step 5: Prune stale worktree metadata
    echo "[5/6] Pruning stale Git worktree metadata..."
    git worktree prune

    # Step 6: Delete Git Branch
    if [[ "$KEEP_BRANCH" == "1" ]]; then
        echo "[6/6] [SKIP] Keeping branch '$w_branch' [--keep-branch]."
    elif [[ -z "$w_branch" || "$w_branch" == "detached" ]]; then
        echo "[6/6] [SKIP] No branch associated with worktree."
    elif branch_exists "$w_branch"; then
        echo "[6/6] Deleting Git branch '$w_branch'..."
        if [[ "$FORCE" == "1" ]]; then
            git branch -D "$w_branch"
        elif ! git branch -d "$w_branch"; then
            echo "[WARNING] Branch '$w_branch' was not fully merged into main."
            echo "          To force delete it, run: git branch -D \"$w_branch\""
            echo "          Or rerun this script with --force."
        fi
    else
        echo "[6/6] [INFO] Branch '$w_branch' does not exist in local Git."
    fi

    echo "[OK] Cleanup completed for '$w_path'."
}

# ------------------------------------------------------------------------------
# 1. Validate Target and Current Workspace
# ------------------------------------------------------------------------------
CURRENT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
    echo "[ERROR] Must be run inside a Git repository."
    exit 1
}
PARENT_DIR="$(cd "$CURRENT_ROOT/.." && pwd)"

# ==============================================================================
# Handle Deletion of All Registered Worktrees
# ==============================================================================
if [[ "$DELETE_ALL" == "1" ]]; then
    echo "=============================================================================="
    echo " Polyweb Bulk Worktree Deletion (--all)"
    echo "=============================================================================="
    if [[ "$AUTO_YES" == "0" ]] && ! confirm "Are you sure you want to delete ALL non-main worktrees?"; then
        echo "[ABORT] Deletion cancelled by user."
        exit 0
    fi

    WT_PATHS=()
    WT_BRANCHES=()
    t_wt=""
    while read -r key value; do
        case "$key" in
            worktree) t_wt="$value" ;;
            branch)
                if [[ "$t_wt" != "$CURRENT_ROOT" ]]; then
                    WT_PATHS+=("$t_wt"); WT_BRANCHES+=("${value#refs/heads/}")
                fi ;;
            detached)
                if [[ "$t_wt" != "$CURRENT_ROOT" ]]; then
                    WT_PATHS+=("$t_wt"); WT_BRANCHES+=("detached")
                fi ;;
        esac
    done < <(git worktree list --porcelain 2>/dev/null)

    if [[ ${#WT_PATHS[@]} -eq 0 ]]; then
        echo "[INFO] No secondary worktrees found to delete."
        echo "[OK] Done."
        exit 0
    fi

    echo "[INFO] Found ${#WT_PATHS[@]} secondary worktree(s) to remove."
    echo
    for i in "${!WT_PATHS[@]}"; do
        echo "------------------------------------------------------------------------------"
        echo "Processing worktree: ${WT_PATHS[$i]} [branch: ${WT_BRANCHES[$i]}]"
        echo "------------------------------------------------------------------------------"
        execute_deletion "${WT_PATHS[$i]}" "${WT_BRANCHES[$i]}"
        echo
    done
    echo "[OK] All secondary worktrees cleaned up successfully."
    exit 0
fi

# Guard main/master branches
if [[ "$TARGET" == "main" || "$TARGET" == "master" ]]; then
    echo "[ERROR] Cannot delete the $TARGET repository branch."
    exit 1
fi

# Determine Branch Name from Target (accepts a branch or a polyweb-<branch> folder)
BRANCH="$TARGET"
STRIPPED="${TARGET//polyweb-/}"
if ! branch_exists "$TARGET" && branch_exists "$STRIPPED"; then
    BRANCH="$STRIPPED"
fi

if [[ "$BRANCH" == "main" || "$BRANCH" == "master" ]]; then
    echo "[ERROR] Cannot delete the $BRANCH repository branch."
    exit 1
fi

# Safe folder name if branch contains slashes (e.g. ui/feature -> ui-feature)
SAFE_NAME="${BRANCH//\//-}"

# ------------------------------------------------------------------------------
# 2. Discover Worktree Directory
# ------------------------------------------------------------------------------
WORKTREE_PATH=""
curr_wt=""
while read -r key value; do
    case "$key" in
        worktree) curr_wt="$value" ;;
        branch)
            curr_branch="${value#refs/heads/}"
            if [[ "$curr_branch" == "$BRANCH" ]]; then
                WORKTREE_PATH="$curr_wt"
            elif [[ "$curr_wt" == "$PARENT_DIR/$TARGET" || "$curr_wt" == "$PARENT_DIR/polyweb-$TARGET" ]]; then
                WORKTREE_PATH="$curr_wt"
                BRANCH="$curr_branch"
            fi ;;
    esac
done < <(git worktree list --porcelain 2>/dev/null)

if [[ -z "$WORKTREE_PATH" ]]; then
    # Not registered with Git: check common directory conventions
    for candidate in "$PARENT_DIR/polyweb-$SAFE_NAME" "$PARENT_DIR/$TARGET" "$PARENT_DIR/polyweb-$TARGET"; do
        if [[ -d "$candidate" ]]; then
            WORKTREE_PATH="$candidate"
            break
        fi
    done
fi

# Guard against deleting current repository
if [[ -n "$WORKTREE_PATH" && "$WORKTREE_PATH" == "$CURRENT_ROOT" ]]; then
    echo "[ERROR] Target worktree is the active repository: '$WORKTREE_PATH'"
    echo "        Cannot delete the worktree you are currently working in."
    exit 1
fi

# If neither worktree path nor git branch exist, nothing to do
if [[ -z "$WORKTREE_PATH" ]] && ! branch_exists "$BRANCH"; then
    echo "[ERROR] No worktree directory or Git branch found matching '$TARGET'."
    exit 1
fi

# ------------------------------------------------------------------------------
# 3. Uncommitted Changes Check & User Confirmation
# ------------------------------------------------------------------------------
if [[ -n "$WORKTREE_PATH" && -d "$WORKTREE_PATH" && "$FORCE" == "0" ]]; then
    if [[ -n "$(git -C "$WORKTREE_PATH" status --porcelain 2>/dev/null)" ]]; then
        echo "[WARNING] Worktree has uncommitted changes or untracked files:"
        git -C "$WORKTREE_PATH" status -s
        echo "Re-run with --force to delete anyway."
        exit 1
    fi
fi

if [[ "$AUTO_YES" == "0" ]]; then
    echo "=============================================================================="
    echo " Polyweb Worktree Deletion"
    echo "=============================================================================="
    echo " Directory: ${WORKTREE_PATH:-[already unlinked or not found]}"
    if [[ "$KEEP_BRANCH" == "0" ]]; then
        echo " Branch:    $BRANCH [will be deleted]"
    else
        echo " Branch:    $BRANCH [will be KEPT]"
    fi
    echo "=============================================================================="
    if ! confirm "Proceed with deletion?"; then
        echo "[ABORT] Deletion cancelled by user."
        exit 0
    fi
fi

execute_deletion "$WORKTREE_PATH" "$BRANCH"
