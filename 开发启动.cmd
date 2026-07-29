@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Development environment is not initialized.
    echo Run the normal startup script once to install dependencies.
    pause
    exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
    echo npm was not found. Install Node.js 20 or later.
    pause
    exit /b 1
)

if not exist "frontend\node_modules" (
    echo Frontend dependencies are not installed.
    echo Run the normal startup script once to install dependencies.
    pause
    exit /b 1
)

echo Starting backend with automatic reload on http://127.0.0.1:8021 ...
start "MOLIU Backend - Auto Reload" cmd /k ".venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8021 --reload --reload-dir backend"

echo Starting frontend with hot reload on http://127.0.0.1:5173 ...
pushd frontend
start "MOLIU Frontend - Hot Reload" cmd /k "call npm run dev"
popd

echo.
echo Development services are starting.
echo Open http://127.0.0.1:5173
echo Close both development windows when finished.

endlocal
