@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo Creating the local Python environment...
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 -m venv "%~dp0.venv"
    ) else (
        python -m venv "%~dp0.venv"
    )
    if errorlevel 1 (
        echo Could not create the virtual environment.
        echo Install Python 3.11 or newer and run this file again.
        pause
        exit /b 1
    )
)

echo Preparing the editable project install...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check --no-deps -e .
if errorlevel 1 (
    echo Could not install the project into the local environment.
    pause
    exit /b 1
)

echo Starting the Polatli fire-spread UI at http://127.0.0.1:8000
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8000'"
"%VENV_PYTHON%" -m fire_spread.web ^
    --dataset "%~dp0data\processed\polatli_network.json" ^
    --buildings "%~dp0data\processed\polatli_buildings.json" ^
    --host 127.0.0.1 ^
    --port 8000

set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo Polatli UI stopped with exit code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
