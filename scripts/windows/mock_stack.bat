@echo off
setlocal enabledelayedexpansion

REM ==============================================================================
REM Polyweb provider-mock dev stack (DEVELOPMENT ONLY). Windows port of
REM scripts/linux/mock_stack.sh.
REM
REM Runs compose.yaml + compose.dev.yaml + compose.mock.yaml as a worktree-unique
REM Compose project (polyweb_wt_N -^> polyweb-wtN-mock), never the live `polyweb`
REM project, with this worktree's ports from .env.
REM
REM Usage:
REM   mock_stack.bat up                 build, start the mock, seed once, start api + mcp
REM   mock_stack.bat down [-v]          stop this project (-v also deletes its volumes)
REM   mock_stack.bat logs [service...]  show logs (add -f to follow)
REM   mock_stack.bat seed               re-seed the mock; seed the Polyweb DB if missing
REM   mock_stack.bat cli ^<args...^>      run polyweb-mock in the mock container
REM   mock_stack.bat ps                 list this project's containers
REM ==============================================================================

pushd "%~dp0..\.."
if not exist ".env" (
    echo [ERROR] No .env in the repository root. Create it from .env.example with this worktree's ports.
    goto :fail
)

REM Worktree-unique project name: polyweb_wt_N -> polyweb-wtN-mock.
for %%I in ("%CD%") do set "FOLDER=%%~nxI"
set "PROJECT="
if /i "!FOLDER:~0,11!"=="polyweb_wt_" (
    set "SLOT_REST=!FOLDER:~11!"
    for %%D in (1 2 3 4 5 6 7 8 9) do if "!SLOT_REST!"=="%%D" set "PROJECT=polyweb-wt%%D-mock"
)
if not defined PROJECT (
    set "PROJECT=!FOLDER:_=-!-mock"
    for %%L in (a b c d e f g h i j k l m n o p q r s t u v w x y z) do set "PROJECT=!PROJECT:%%L=%%L!"
)
if defined POLYWEB_MOCK_STACK_PROJECT set "PROJECT=%POLYWEB_MOCK_STACK_PROJECT%"
if /i "!PROJECT:~-5!" neq "-mock" (
    echo [ERROR] Compose project '!PROJECT!' must end in -mock; the live project is 'polyweb'.
    goto :fail
)

REM Read the non-secret port settings: the process value wins, then .env.
for %%N in (POLYWEB_API_PORT POLYWEB_MCP_PORT POLYWEB_PROVIDER_MOCK_PORT) do (
    if not defined %%N (
        for /f "usebackq tokens=1,* delims==" %%A in (`findstr /b /c:"%%N=" ".env"`) do set "%%N=%%B"
    )
    if not defined %%N (
        echo [ERROR] %%N is not set in .env ^(see the AGENTS.md port table^).
        goto :fail
    )
    for %%P in (3000 3100 8000 8001 8080 8090 8100 8101 9000 9090) do (
        if "!%%N!"=="%%P" (
            echo [ERROR] %%N=%%P belongs to another service on this host; use the worktree port.
            goto :fail
        )
    )
)

set "POLYWEB_MOCK_STACK_PROJECT=!PROJECT!"
set "COMPOSE=docker compose -p !PROJECT! -f compose.yaml -f compose.dev.yaml -f compose.mock.yaml"
set "SEED_COMMAND=test -e /data/polyweb.mock-dev.db && echo 'Polyweb mock dev DB exists; seed skipped.' || uv run --no-sync python scripts/seed_dev.py --database /data/polyweb.mock-dev.db --keys-from-mock http://provider-mock:8212"

set "COMMAND=%~1"
if "%COMMAND%"=="" goto :usage
shift
set "ARGS="
:collect
if "%~1"=="" goto :dispatch
set "ARGS=!ARGS! %1"
shift
goto :collect

:dispatch
if /i "%COMMAND%"=="up" goto :up
if /i "%COMMAND%"=="down" (%COMPOSE% down !ARGS! & goto :done)
if /i "%COMMAND%"=="logs" (%COMPOSE% logs !ARGS! & goto :done)
if /i "%COMMAND%"=="ps" (%COMPOSE% ps !ARGS! & goto :done)
if /i "%COMMAND%"=="cli" (%COMPOSE% exec provider-mock /app/.venv/bin/polyweb-mock !ARGS! & goto :done)
if /i "%COMMAND%"=="seed" goto :seed
goto :usage

:up
echo [INFO] Project !PROJECT!: API !POLYWEB_API_PORT!, MCP !POLYWEB_MCP_PORT!, mock !POLYWEB_PROVIDER_MOCK_PORT! (127.0.0.1).
%COMPOSE% build provider-mock api || goto :fail
%COMPOSE% up -d --wait provider-mock || goto :fail
REM Seed before api starts: the API creates the database file on startup.
%COMPOSE% run --rm --no-deps api sh -c "!SEED_COMMAND!" || goto :fail
%COMPOSE% up -d --wait api mcp || goto :fail
echo [OK] API http://127.0.0.1:!POLYWEB_API_PORT!  MCP http://127.0.0.1:!POLYWEB_MCP_PORT!/mcp
echo      Mock http://127.0.0.1:!POLYWEB_PROVIDER_MOCK_PORT!/_mock/health  Log in as admin1@example.com.
goto :done

:seed
%COMPOSE% exec provider-mock /app/.venv/bin/polyweb-mock seed !ARGS! || goto :fail
%COMPOSE% run --rm --no-deps api sh -c "!SEED_COMMAND!" || goto :fail
goto :done

:usage
echo Usage: mock_stack.bat up^|down [-v]^|logs [service...]^|seed^|cli ^<polyweb-mock args^>^|ps
popd
exit /b 1

:done
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%

:fail
popd
exit /b 1
