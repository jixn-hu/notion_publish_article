@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo Virtual environment not found: .venv
    echo Please create it and install requirements first.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"
python main.py

if errorlevel 1 (
    echo.
    echo Program exited with an error.
    pause
)

endlocal
