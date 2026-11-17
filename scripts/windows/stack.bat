@echo off
setlocal enabledelayedexpansion

REM ==============================================================================
REM Polyweb worktree stacks (DEVELOPMENT ONLY). Windows port of
REM scripts/linux/stack.sh. pd, the deployed stack, is not run from here.
REM
REM   npd  compose.yaml + docker/npd/compose.yaml: worktree source, real providers.
REM   dev  ... + docker/dev/compose.yaml: worktree source, every provider call
REM        goes to the provider mock.
REM
REM Each runs as a worktree-unique Compose project (polyweb_wt_N -^>
REM polyweb-wtN-npd or polyweb-wtN-dev), never the pd `polyweb` project, with
REM this worktree's ports from .env.
REM
REM Usage:
REM   stack.bat npd^|dev up                 build and start (dev: start the mock and seed once)
REM   stack.bat npd^|dev down [-v]          stop this project (-v also deletes its volumes)
REM   stack.bat npd^|dev logs [service...]  show logs (add -f to follow)
REM   stack.bat npd^|dev ps                 list this project's containers
REM   stack.bat dev seed                    re-seed the mock; seed the Polyweb DB if missing
REM   stack.bat dev cli ^<args...^>           run polyweb-mock in the mock container
REM   stack.bat dev live [behave args...]   dev-live: the @live Behave scenarios on this
REM                                         host against this stack's mock
REM ==============================================================================

pushd "%~dp0..\.."

set "STACK=%~1"
if /i not "!STACK!"=="npd" if /i not "!STACK!"=="dev" goto :usage
shift
set "COMMAND=%~1"
if "!COMMAND!"=="" goto :usage
shift
set "ARGS="
:collect
if "%~1"=="" goto :checked
set "ARGS=!ARGS! %1"
shift
goto :collect

:checked
if not exist ".env" (
    echo [ERROR] No .env in the repository root. Create it from .env.example with this worktree's ports.
    goto :fail
)

REM Worktree-unique project name: polyweb_wt_N -> polyweb-wtN-<stack>.
for %%I in ("%CD%") do set "FOLDER=%%~nxI"
set "PROJECT="
if /i "!FOLDER:~0,11!"=="polyweb_wt_" (
    set "SLOT_REST=!FOLDER:~11!"
    for %%D in (1 2 3 4 5 6 7 8 9) do if "!SLOT_REST!"=="%%D" set "PROJECT=polyweb-wt%%D-!STACK!"
)
if not defined PROJECT (
    set "PROJECT=!FOLDER:_=-!-!STACK!"
    for %%L in (a b c d e f g h i j k l m n o p q r s t u v w x y z) do set "PROJECT=!PROJECT:%%L=%%L!"
)
if defined POLYWEB_STACK_PROJECT set "PROJECT=%POLYWEB_STACK_PROJECT%"
if /i "!PROJECT:~-4!" neq "-!STACK!" (
    echo [ERROR] Compose project '!PROJECT!' must end in -!STACK!; the pd project is 'polyweb'.
    goto :fail
)

REM Read the non-secret port settings: the process value wins, then .env.
set "PORT_NAMES=POLYWEB_API_PORT POLYWEB_MCP_PORT"
if /i "!STACK!"=="dev" set "PORT_NAMES=!PORT_NAMES! POLYWEB_PROVIDER_MOCK_PORT"
for %%N in (!PORT_NAMES!) do (
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

set "POLYWEB_STACK_PROJECT=!PROJECT!"
set "COMPOSE=docker compose -p !PROJECT! -f compose.yaml -f docker/npd/compose.yaml"
if /i "!STACK!"=="dev" set "COMPOSE=!COMPOSE! -f docker/dev/compose.yaml"
set "SEED_COMMAND=test -e /data/polyweb.mock-dev.db && echo 'Polyweb mock dev DB exists; seed skipped.' || uv run --no-sync python scripts/seed_dev.py --database /data/polyweb.mock-dev.db --keys-from-mock http://provider-mock:8212"

if /i "!COMMAND!"=="up" goto :up
if /i "!COMMAND!"=="down" (!COMPOSE! down !ARGS! & goto :done)
if /i "!COMMAND!"=="logs" (!COMPOSE! logs !ARGS! & goto :done)
if /i "!COMMAND!"=="ps" (!COMPOSE! ps !ARGS! & goto :done)
if /i "!COMMAND!"=="seed" goto :seed
if /i "!COMMAND!"=="cli" goto :cli
if /i "!COMMAND!"=="live" goto :live
goto :usage

:up
if /i "!STACK!"=="npd" goto :up_npd
echo [INFO] Project !PROJECT!: API !POLYWEB_API_PORT!, MCP !POLYWEB_MCP_PORT!, mock !POLYWEB_PROVIDER_MOCK_PORT! (127.0.0.1).
!COMPOSE! build provider-mock api || goto :fail
!COMPOSE! up -d --wait provider-mock || goto :fail
REM Seed before api starts: the API creates the database file on startup.
!COMPOSE! run --rm --no-deps api sh -c "!SEED_COMMAND!" || goto :fail
!COMPOSE! up -d --wait api mcp || goto :fail
echo [OK] API http://127.0.0.1:!POLYWEB_API_PORT!  MCP http://127.0.0.1:!POLYWEB_MCP_PORT!/mcp
echo      Mock http://127.0.0.1:!POLYWEB_PROVIDER_MOCK_PORT!/_mock/health  Log in as admin1@example.com.
goto :done

:up_npd
echo [INFO] Project !PROJECT!: API !POLYWEB_API_PORT!, MCP !POLYWEB_MCP_PORT! (127.0.0.1), real providers.
!COMPOSE! build api || goto :fail
!COMPOSE! up -d --wait api mcp || goto :fail
echo [OK] API http://127.0.0.1:!POLYWEB_API_PORT!  MCP http://127.0.0.1:!POLYWEB_MCP_PORT!/mcp
echo      Provider keys live in this project's vault; add them in the dashboard (pnpm dev).
goto :done

:seed
if /i not "!STACK!"=="dev" goto :need_dev
!COMPOSE! exec provider-mock /app/.venv/bin/polyweb-mock seed !ARGS! || goto :fail
!COMPOSE! run --rm --no-deps api sh -c "!SEED_COMMAND!" || goto :fail
goto :done

:cli
if /i not "!STACK!"=="dev" goto :need_dev
!COMPOSE! exec provider-mock /app/.venv/bin/polyweb-mock !ARGS!
goto :done

:live
REM dev-live: the same @live scenarios the live run sends to the real providers,
REM run on this host with the mock's keys and every provider call rerouted to
REM this stack's mock. Mirrors the provider-mock Woodpecker workflow.
if /i not "!STACK!"=="dev" goto :need_dev
!COMPOSE! build provider-mock || goto :fail
!COMPOSE! up -d --wait provider-mock || goto :fail
set "KEY_COUNT=0"
for /f "usebackq tokens=1,* delims==" %%A in (`!COMPOSE! exec -T provider-mock /app/.venv/bin/polyweb-mock export-keys --format dotenv`) do (
    set "KEY_NAME=%%A"
    if /i not "!KEY_NAME:~-8!"=="_API_KEY" (
        echo [ERROR] Unexpected export-keys line from the mock: %%A
        goto :fail
    )
    set "%%A=%%B"
    set /a KEY_COUNT+=1
)
if "!KEY_COUNT!"=="0" (
    echo [ERROR] The mock exported no keys.
    goto :fail
)
set "POLYWEB_PROVIDER_MOCK_URL=http://127.0.0.1:!POLYWEB_PROVIDER_MOCK_PORT!"
set "POLYWEB_TEST_PROVIDER_MOCK=1"
set "POLYWEB_RUN_LIVE=1"
echo [INFO] dev-live: @live scenarios against mock !POLYWEB_PROVIDER_MOCK_URL! (!PROJECT!).
uv run polyweb-db upgrade || goto :fail
uv run behave --tags="@live and not @latency" !ARGS!
goto :done

:need_dev
echo [ERROR] '!COMMAND!' needs the dev stack (it uses the provider mock).
goto :fail

:usage
echo Usage: stack.bat npd^|dev up^|down [-v]^|logs [service...]^|ps
echo        stack.bat dev seed^|cli ^<polyweb-mock args^>^|live [behave args]
popd
exit /b 1

:done
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%

:fail
popd
exit /b 1
