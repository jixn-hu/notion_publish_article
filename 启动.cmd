@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )

    call ".venv\Scripts\activate.bat"
    echo Installing Python dependencies...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Failed to install Python dependencies.
        pause
        exit /b 1
    )
) else (
    call ".venv\Scripts\activate.bat"
)

where npm >nul 2>nul
if errorlevel 1 (
    echo npm was not found. Install Node.js 20 or later.
    pause
    exit /b 1
)

if not exist "frontend\node_modules" (
    echo Installing frontend dependencies...
    pushd frontend
    call npm ci
    if errorlevel 1 (
        popd
        echo Failed to install frontend dependencies.
        pause
        exit /b 1
    )
    popd
)

set "BUILD_FRONTEND="
if not exist "frontend\dist\index.html" (
    set "BUILD_FRONTEND=1"
) else (
    powershell -NoProfile -Command "$output = (Get-Item 'frontend\dist\index.html').LastWriteTime; $source = Get-ChildItem 'frontend' -File -Recurse | Where-Object { $_.FullName -notmatch '\\(node_modules|dist)\\' }; if ($source | Where-Object { $_.LastWriteTime -gt $output }) { exit 0 }; exit 1"
    if not errorlevel 1 set "BUILD_FRONTEND=1"
)

if defined BUILD_FRONTEND (
    echo Building frontend...
    pushd frontend
    call npm run build
    if errorlevel 1 (
        popd
        echo Failed to build frontend.
        pause
        exit /b 1
    )
    popd
)

echo Starting application...
python main.py

if errorlevel 1 (
    echo.
    echo Program exited with an error.
    pause
)

endlocal
