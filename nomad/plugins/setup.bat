@echo off
setlocal enabledelayedexpansion

title TGA Automation Setup
cls
echo ============================================
echo   TGA Automation for Windows - Setup
echo ============================================
echo.
echo This will install everything needed to watch
echo a folder for TGA exports and push results to
echo elabFTW and NOMAD Oasis.
echo.
echo Requirements: Python 3.9+ and internet access.
echo.

:: ── 1. Find Python ──────────────────────────────
echo [1/4] Checking Python...

set PYTHON_CMD=

:: Try Python launcher (most reliable on Windows, not affected by Store stub)
py -3 --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=py -3
    goto :found_python
)

:: Try python (must actually run, not Microsoft Store stub)
where python >nul 2>&1
if %errorlevel% equ 0 (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>&1
    if !errorlevel! equ 0 (
        set PYTHON_CMD=python
        goto :found_python
    )
)

:: Try python3 (may be Microsoft Store stub — verify it runs)
where python3 >nul 2>&1
if %errorlevel% equ 0 (
    python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>&1
    if !errorlevel! equ 0 (
        set PYTHON_CMD=python3
        goto :found_python
    )
)

:: Not found or too old - offer to install
echo.
echo Python 3.9+ not found.
echo Would you like to download and install Python?
echo (Opens python.org in your browser)
echo.
set /p INSTALL_PYTHON="Install Python now? (Y/n): "
if /i "!INSTALL_PYTHON!"=="" set INSTALL_PYTHON=Y
if /i "!INSTALL_PYTHON!"=="Y" (
    echo Opening https://www.python.org/downloads/ ...
    start https://www.python.org/downloads/
    echo.
    echo After installing, CHECK "Add Python to PATH" and run setup.bat again.
    pause
    exit /b 1
) else (
    echo Cannot continue without Python.
    pause
    exit /b 1
)

:found_python
echo   Found: %PYTHON_CMD%
%PYTHON_CMD% --version
echo.

:: ── 2. Create virtual environment ──────────────
echo [2/4] Creating virtual environment...

if exist "%~dp0venv" (
    echo   Virtual environment already exists.
) else (
    %PYTHON_CMD% -m venv "%~dp0venv"
    if !errorlevel! neq 0 (
        echo   Failed to create venv. Trying without venv...
        set USE_VENV=0
    ) else (
        echo   Virtual environment created.
        set USE_VENV=1
    )
)

:: Activate venv
if defined USE_VENV (
    if exist "%~dp0venv\Scripts\activate.bat" (
        call "%~dp0venv\Scripts\activate.bat"
    ) else (
        set USE_VENV=0
    )
)
echo.

:: ── 3. Install dependencies ────────────────────
echo [3/4] Installing dependencies...
echo   numpy, matplotlib, requests

if defined USE_VENV (
    "%~dp0venv\Scripts\python.exe" -m pip install --quiet --upgrade pip 2>nul
    "%~dp0venv\Scripts\python.exe" -m pip install --quiet numpy matplotlib requests 2>&1 <nul
    if !errorlevel! equ 0 (
        echo   All dependencies installed.
    ) else (
        echo   Warning: pip install had issues. Trying without venv...
        %PYTHON_CMD% -m pip install --quiet numpy matplotlib requests 2>&1 <nul
    )
) else (
    %PYTHON_CMD% -m pip install --quiet --upgrade pip 2>nul
    %PYTHON_CMD% -m pip install --quiet numpy matplotlib requests 2>&1 <nul
)
echo.

:: ── 4. Run configuration ───────────────────────
echo [4/4] Configuring API keys...

if defined USE_VENV (
    "%~dp0venv\Scripts\python.exe" "%~dp0tga_watch.py" setup
) else (
    %PYTHON_CMD% "%~dp0tga_watch.py" setup
)

if !errorlevel! neq 0 (
    echo.
    echo   Configuration step had an error.
    echo   Try running manually: tga_watch.py setup
)

echo.
echo ============================================
echo   Setup complete!
echo ============================================
echo.
echo Quick start:
echo   Double-click: start_watch.bat
echo   Or run:       tga_watch.py watch
echo.
echo To process one file:
echo   tga_watch.py process path\to\file.csv
echo.
echo To see current config:
echo   tga_watch.py show-config
echo.

:: Create a convenience start script
if not exist "%~dp0start_watch.bat" (
    (
        echo @echo off
        echo title TGA Automation Watcher
        echo.
        if defined USE_VENV (
            echo "%%~dp0venv\Scripts\python.exe" "%%~dp0tga_watch.py" watch
        ) else (
            echo python "%%~dp0tga_watch.py" watch
        )
        echo pause
    ) > "%~dp0start_watch.bat"
    echo   Created start_watch.bat - double-click to run the watcher
)

pause
