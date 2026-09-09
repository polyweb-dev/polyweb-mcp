@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%..\.."
pushd "%REPO_ROOT%"

REM Build the mutation test image
echo [1/2] Building Docker image for mutation testing...
docker build -f Dockerfile.test -t freesearch-mutation .
if errorlevel 1 (
    echo [ERROR] Docker build failed. Make sure Docker Desktop is running.
    popd
    exit /b 1
)

REM Ensure local output directories exist
if not exist "coverage\gremlins" mkdir "coverage\gremlins"
if not exist ".gremlins_cache" mkdir ".gremlins_cache"

REM Run mutation testing in Linux container, mounting coverage and cache back to host
echo [2/2] Running containerized mutation testing...
docker run --rm ^
  -v "%cd%/coverage:/app/coverage" ^
  -v "%cd%/.gremlins_cache:/app/.gremlins_cache" ^
  freesearch-mutation %*

echo.
echo Reports written to coverage\gremlins\index.html
popd
exit /b %ERRORLEVEL%
