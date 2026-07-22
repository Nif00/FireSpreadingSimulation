@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "VENV_DIR=%~dp0.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "BOOTSTRAP_PYTHON="

where python >nul 2>&1
if not errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if not errorlevel 1 set "BOOTSTRAP_PYTHON=python"
)

if not defined BOOTSTRAP_PYTHON (
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
        if not errorlevel 1 set "BOOTSTRAP_PYTHON=py -3.11"
    )
)

if not defined BOOTSTRAP_PYTHON (
    echo Python 3.11 or newer is required.
    pause
    exit /b 1
)

if not exist "%VENV_PYTHON%" %BOOTSTRAP_PYTHON% -m venv "%VENV_DIR%"
"%VENV_PYTHON%" -m pip install --disable-pip-version-check --no-deps -e .
if errorlevel 1 exit /b 1

echo Starting the Manhattan Island fire-spread UI at http://127.0.0.1:8000
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8000'"
"%VENV_PYTHON%" -m fire_spread.web --dataset "%~dp0data\processed\manhattan_network.json" --buildings "%~dp0data\processed\manhattan_buildings.json" --host 127.0.0.1 --port 8000
