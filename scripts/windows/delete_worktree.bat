@echo off
setlocal enabledelayedexpansion

REM ==============================================================================
REM FreeSearch Generic Worktree Cleanup Script
REM Usage:
REM   delete_worktree.bat <branch-or-folder> [--force|-f] [--keep-branch|-k] [--yes|-y]
REM
REM Examples:
REM   delete_worktree.bat quota-fix
REM   delete_worktree.bat ui-cq-refactor --force
REM   delete_worktree.bat freesearch-quota-fix --keep-branch
REM ==============================================================================

set "TARGET="
set "FORCE=0"
set "KEEP_BRANCH=0"
set "AUTO_YES=0"
set "CLEAN_IMAGES=0"

:parse_args
if "%~1"=="" goto :args_done

if /i "%~1"=="--force" (
    set "FORCE=1"
    set "AUTO_YES=1"
) else if /i "%~1"=="-f" (
    set "FORCE=1"
    set "AUTO_YES=1"
) else if /i "%~1"=="--keep-branch" (
    set "KEEP_BRANCH=1"
) else if /i "%~1"=="-k" (
    set "KEEP_BRANCH=1"
) else if /i "%~1"=="--clean-images" (
    set "CLEAN_IMAGES=1"
) else if /i "%~1"=="--rmi" (
    set "CLEAN_IMAGES=1"
) else if /i "%~1"=="--yes" (
    set "AUTO_YES=1"
) else if /i "%~1"=="-y" (
    set "AUTO_YES=1"
) else (
    if not defined TARGET set "TARGET=%~1"
)
shift
goto :parse_args
:args_done

if not defined TARGET goto :usage

REM ------------------------------------------------------------------------------
REM 1. Validate Target and Current Workspace
REM ------------------------------------------------------------------------------
for /f "delims=" %%I in ('git rev-parse --show-toplevel 2^>nul') do set "RAW_ROOT=%%I"
if not defined RAW_ROOT (
    echo [ERROR] Must be run inside a Git repository.
    exit /b 1
)
set "CURRENT_ROOT=!RAW_ROOT:/=\!"
for %%I in ("!CURRENT_ROOT!\..") do set "PARENT_DIR=%%~fI"

REM Guard main/master branches
if /i "%TARGET%"=="main" (
    echo [ERROR] Cannot delete the main repository branch.
    exit /b 1
)
if /i "%TARGET%"=="master" (
    echo [ERROR] Cannot delete the master repository branch.
    exit /b 1
)

REM Determine Branch Name from Target
set "BRANCH=%TARGET%"
set "STRIPPED=%TARGET:freesearch-=%"

git show-ref --verify --quiet "refs/heads/%TARGET%"
if not errorlevel 1 (
    set "BRANCH=%TARGET%"
) else (
    git show-ref --verify --quiet "refs/heads/%STRIPPED%"
    if not errorlevel 1 (
        set "BRANCH=%STRIPPED%"
    )
)

if /i "%BRANCH%"=="main" (
    echo [ERROR] Cannot delete the main repository branch.
    exit /b 1
)
if /i "%BRANCH%"=="master" (
    echo [ERROR] Cannot delete the master repository branch.
    exit /b 1
)

REM Safe folder name if branch contains slashes (e.g. ui/feature -> ui-feature)
set "SAFE_NAME=%BRANCH:/=-%"

REM ------------------------------------------------------------------------------
REM 2. Discover Worktree Directory
REM ------------------------------------------------------------------------------
set "WORKTREE_PATH="

REM First, check Git's registered worktrees
set "CURR_WT="
for /f "tokens=1,*" %%A in ('git worktree list --porcelain 2^>nul') do (
    if /i "%%A"=="worktree" (
        set "CURR_WT=%%B"
    ) else if /i "%%A"=="branch" (
        if /i "%%B"=="refs/heads/%BRANCH%" (
            set "WORKTREE_PATH=!CURR_WT!"
        )
    )
)

if defined WORKTREE_PATH (
    set "WORKTREE_PATH=!WORKTREE_PATH:/=\!"
) else (
    REM If not in git worktree list, check common directory conventions
    if exist "!PARENT_DIR!\freesearch-%SAFE_NAME%" (
        set "WORKTREE_PATH=!PARENT_DIR!\freesearch-%SAFE_NAME%"
    ) else if exist "!PARENT_DIR!\%TARGET%" (
        set "WORKTREE_PATH=!PARENT_DIR!\%TARGET%"
    ) else if exist "!PARENT_DIR!\freesearch-%TARGET%" (
        set "WORKTREE_PATH=!PARENT_DIR!\freesearch-%TARGET%"
    )
)

REM Guard against deleting current repository
if defined WORKTREE_PATH (
    if /i "!WORKTREE_PATH!"=="!CURRENT_ROOT!" (
        echo [ERROR] Target worktree is the active repository: '!WORKTREE_PATH!'
        echo         Cannot delete the worktree you are currently working in.
        exit /b 1
    )
)

REM If neither worktree path nor git branch exist, nothing to do
git show-ref --verify --quiet "refs/heads/%BRANCH%"
set "BRANCH_EXISTS=%ERRORLEVEL%"

if not defined WORKTREE_PATH (
    if "%BRANCH_EXISTS%"=="1" (
        echo [ERROR] No worktree directory or Git branch found matching '%TARGET%'.
        exit /b 1
    )
)

REM ------------------------------------------------------------------------------
REM 3. Uncommitted Changes Check & User Confirmation
REM ------------------------------------------------------------------------------
if defined WORKTREE_PATH (
    if exist "!WORKTREE_PATH!" (
        for /f "delims=" %%S in ('git -C "!WORKTREE_PATH!" status --porcelain 2^>nul') do (
            if "!FORCE!"=="0" (
                echo [WARNING] Worktree has uncommitted changes or untracked files:
                git -C "!WORKTREE_PATH!" status -s
                echo Re-run with --force to delete anyway.
                exit /b 1
            )
        )
    )
)

if "!AUTO_YES!"=="0" (
    echo ==============================================================================
    echo  FreeSearch Worktree Deletion
    echo ==============================================================================
    if defined WORKTREE_PATH (
        echo  Directory: !WORKTREE_PATH!
    ) else (
        echo  Directory: [already unlinked or not found]
    )
    if "!KEEP_BRANCH!"=="0" (
        echo  Branch:    !BRANCH! [will be deleted]
    ) else (
        echo  Branch:    !BRANCH! [will be KEPT]
    )
    echo ==============================================================================
    set /p "CONFIRM=Proceed with deletion? [y/N]: "
    if /i not "!CONFIRM!"=="y" if /i not "!CONFIRM!"=="yes" (
        echo [ABORT] Deletion cancelled by user.
        exit /b 0
    )
)

REM ------------------------------------------------------------------------------
REM 4. Tear down Docker Compose resources (containers, networks, volumes)
REM ------------------------------------------------------------------------------
if defined WORKTREE_PATH (
    if exist "!WORKTREE_PATH!" (
        where docker >nul 2>&1
        if not errorlevel 1 (
            set "HAS_COMPOSE=0"
            if exist "!WORKTREE_PATH!\compose.yaml" set "HAS_COMPOSE=1"
            if exist "!WORKTREE_PATH!\docker-compose.yml" set "HAS_COMPOSE=1"
            if "!HAS_COMPOSE!"=="1" (
                echo [1/5] Tearing down Docker Compose containers, networks, and volumes...
                pushd "!WORKTREE_PATH!"
                if "!CLEAN_IMAGES!"=="1" (
                    call docker compose down --volumes --remove-orphans --rmi local >nul 2>&1
                ) else (
                    call docker compose down --volumes --remove-orphans >nul 2>&1
                )
                popd
            ) else (
                echo [1/5] [SKIP] No Docker Compose file found in worktree.
            )
        ) else (
            echo [1/5] [SKIP] Docker CLI not found.
        )
    ) else (
        echo [1/5] [SKIP] Worktree directory does not exist.
    )
) else (
    echo [1/5] [SKIP] No worktree directory found.
)

REM ------------------------------------------------------------------------------
REM 5. Remove Worktree from Git
REM ------------------------------------------------------------------------------
if defined WORKTREE_PATH (
    echo [2/5] Unregistering worktree from Git...
    if "!FORCE!"=="1" (
        call git worktree remove --force "!WORKTREE_PATH!" >nul 2>&1
    ) else (
        call git worktree remove "!WORKTREE_PATH!" >nul 2>&1
    )
) else (
    echo [2/5] [SKIP] No registered worktree path found in Git.
)

REM ------------------------------------------------------------------------------
REM 6. Clean up filesystem leftovers (node_modules, .venv, .stryker-tmp, etc.)
REM ------------------------------------------------------------------------------
if defined WORKTREE_PATH (
    if exist "!WORKTREE_PATH!" (
        echo [3/5] Removing filesystem directory and leftovers '!WORKTREE_PATH!'...
        cmd /c rmdir /s /q "!WORKTREE_PATH!" >nul 2>&1
        if exist "!WORKTREE_PATH!" (
            timeout /t 1 /nobreak >nul 2>&1
            cmd /c rmdir /s /q "!WORKTREE_PATH!" >nul 2>&1
        )
        if exist "!WORKTREE_PATH!" (
            echo [WARNING] Some files in '!WORKTREE_PATH!' could not be deleted.
            echo           Please close any open editors/terminals using this directory.
        ) else (
            echo [OK] Worktree directory removed completely.
        )
    ) else (
        echo [3/5] [OK] Directory already removed from disk.
    )
) else (
    echo [3/5] [SKIP] No worktree directory to remove.
)

REM ------------------------------------------------------------------------------
REM 7. Prune stale worktree metadata
REM ------------------------------------------------------------------------------
echo [4/5] Pruning stale Git worktree metadata...
call git worktree prune

REM ------------------------------------------------------------------------------
REM 8. Delete Git Branch
REM ------------------------------------------------------------------------------
if "!KEEP_BRANCH!"=="1" (
    echo [5/5] [SKIP] Keeping branch '!BRANCH!' [--keep-branch].
) else (
    git show-ref --verify --quiet "refs/heads/%BRANCH%"
    if not errorlevel 1 (
        echo [5/5] Deleting Git branch '!BRANCH!'...
        if "!FORCE!"=="1" (
            call git branch -D "!BRANCH!"
        ) else (
            call git branch -d "!BRANCH!"
            if errorlevel 1 (
                echo [WARNING] Branch '!BRANCH!' was not fully merged into main.
                echo           To force delete it, run: git branch -D "!BRANCH!"
                echo           Or rerun this script with --force.
            )
        )
    ) else (
        echo [5/5] [INFO] Branch '!BRANCH!' does not exist in local Git.
    )
)

echo.
echo [OK] Worktree cleanup completed for '%TARGET%'.
exit /b 0

REM ------------------------------------------------------------------------------
REM Usage Information
REM ------------------------------------------------------------------------------
:usage
echo [ERROR] Missing branch or worktree folder name.
echo.
echo Usage:
echo   delete_worktree.bat ^<branch-or-folder^> [options]
echo.
echo Options:
echo   -f, --force         Force removal [even if dirty or unmerged]
echo   -k, --keep-branch   Delete worktree directory and registration, but keep the branch
echo   --clean-images      Also remove locally built Docker images (--rmi local)
echo   -y, --yes           Skip confirmation prompt
echo.
echo Examples:
echo   delete_worktree.bat quota-fix
echo   delete_worktree.bat ui-cq-refactor --force
echo   delete_worktree.bat freesearch-quota-fix --keep-branch
echo   delete_worktree.bat feature/AllSearchRanked --force --clean-images
exit /b 1
