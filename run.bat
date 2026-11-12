@echo off
setlocal EnableDelayedExpansion

REM Save argument before any sub-call resets parameters
set "PASSED_CHOICE=%~1"

REM Change directory to script folder
cd /d "%~dp0"

title CF IP Tester Launcher

echo ============================================================
echo                CF IP Tester Launcher (Windows)
echo ============================================================
echo.

REM 1. Detection of Python 3.11+
set "PY_CMD="

REM Test python in PATH
for %%P in (python.exe python3.exe py.exe) do (
    if "!PY_CMD!"=="" (
        %%P -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY_CMD=%%P"
    )
)

REM Test standard Windows installation directories
if "!PY_CMD!"=="" (
    for %%D in (
        "%ProgramFiles%\Python311\python.exe"
        "%ProgramFiles%\Python312\python.exe"
        "%ProgramFiles%\Python313\python.exe"
        "%ProgramFiles(x86)%\Python311\python.exe"
        "%ProgramFiles(x86)%\Python312\python.exe"
        "%ProgramFiles(x86)%\Python313\python.exe"
        "%LocalAppData%\Programs\Python\Python311\python.exe"
        "%LocalAppData%\Programs\Python\Python312\python.exe"
        "%LocalAppData%\Programs\Python\Python313\python.exe"
    ) do (
        if "!PY_CMD!"=="" if exist %%D (
            %%D -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
            if not errorlevel 1 set "PY_CMD=%%~D"
        )
    )
)

REM Test py -3 launcher
if "!PY_CMD!"=="" (
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py -3"
)

REM If Python 3.11+ is still not found, prompt user for automated installation
if not "!PY_CMD!"=="" goto :python_found

echo [PROMPT] Python 3.11+ was not detected on your system.
echo Python 3.11 or higher is required to run CF IP Tester.
echo.
set "INSTALL_CHOICE=y"
set /p "INSTALL_CHOICE=Would you like to automatically download and install Python 3.11 now? (y/n) [Default: y]: "
if "!INSTALL_CHOICE!"=="" set "INSTALL_CHOICE=y"
if /i not "!INSTALL_CHOICE!"=="y" (
    echo.
    echo [ERROR] Installation cancelled. Please install Python 3.11+ from https://www.python.org/
    pause
    exit /b 1
)

echo.
echo ============================================================
echo [INFO] Starting automated Python 3.11 installation...
echo ============================================================

REM Attempt 1: winget (if available)
where winget >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Installing Python 3.11 via Windows Package Manager (winget)...
    winget install --id Python.Python.3.11 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
)

REM Re-verify if winget installed it
for %%D in (
    "%LocalAppData%\Programs\Python\Python311\python.exe"
    "%ProgramFiles%\Python311\python.exe"
) do (
    if "!PY_CMD!"=="" if exist %%D set "PY_CMD=%%~D"
)

REM Attempt 2: Direct official installer download via PowerShell if needed
if "!PY_CMD!"=="" (
    echo [INFO] Downloading official Python 3.11 installer from python.org...
    set "INSTALLER_PATH=%TEMP%\python-3.11.9-amd64.exe"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $ProgressPreference = 'SilentlyContinue'; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile '!INSTALLER_PATH!'"
    if exist "!INSTALLER_PATH!" (
        echo [INFO] Running Python 3.11 installer silently...
        start /wait "" "!INSTALLER_PATH!" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 SimpleInstall=1
        del /f /q "!INSTALLER_PATH!" >nul 2>&1
    )
)

REM Final check after installation
for %%D in (
    "%LocalAppData%\Programs\Python\Python311\python.exe"
    "%ProgramFiles%\Python311\python.exe"
) do (
    if "!PY_CMD!"=="" if exist %%D set "PY_CMD=%%~D"
)

if "!PY_CMD!"=="" (
    echo [ERROR] Automated installation could not be completed.
    echo Please install Python 3.11+ manually from https://www.python.org/
    pause
    exit /b 1
)

echo [SUCCESS] Python 3.11 installed successfully at: !PY_CMD!
echo.

:python_found
echo [INFO] Using Python: !PY_CMD!

REM 2. Virtual environment management
if exist ".venv" goto :venv_exists
echo [INFO] Creating virtual environment .venv ...
"!PY_CMD!" -m venv .venv
if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)
echo [INFO] Virtual environment created successfully.

:venv_exists
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment.
    pause
    exit /b 1
)

REM 3. Check and install dependencies
python -c "import PySide6, openpyxl, xlrd, xlwt" >nul 2>&1
if not errorlevel 1 goto :deps_ready

echo [INFO] Installing required dependencies from requirements.txt...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)
echo [INFO] Dependencies installed successfully.
echo.

:deps_ready
REM 4. Menu loop
if not "%PASSED_CHOICE%"=="" (
    set "CHOICE=%PASSED_CHOICE%"
    set "PASSED_CHOICE="
    goto :handle_choice
)

:menu_loop
echo.
echo ============================================================
echo  [1] Launch CF IP Tester GUI (Default)
echo  [2] Build Standalone Executable (PyInstaller Binary)
echo  [0] Exit
echo ============================================================
set "CHOICE=1"
set /p "CHOICE=Enter selection (1, 2, or 0) [Default: 1]: "
if "%CHOICE%"=="" set "CHOICE=1"

:handle_choice
if "%CHOICE%"=="1" goto :run_gui
if "%CHOICE%"=="2" goto :build_binary
if "%CHOICE%"=="0" goto :exit_clean
if "%CHOICE%"=="3" goto :exit_clean

echo [WARNING] Invalid selection. Please enter 1, 2, or 0.
goto :menu_loop

:run_gui
echo.
echo [INFO] Starting CF IP Tester GUI...
python main.py
echo.
echo [INFO] Application closed. Returning to launcher menu...
goto :menu_loop

:build_binary
echo.
echo [INFO] Checking PyInstaller...
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing PyInstaller...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] Failed to install PyInstaller.
        echo.
        goto :menu_loop
    )
)

echo [INFO] Building standalone binary...
pyinstaller --noconsole --onefile --name "CF-IP-Tester" --clean main.py

if not errorlevel 1 (
    echo.
    echo ============================================================
    echo [SUCCESS] Standalone executable created at:
    echo  dist\CF-IP-Tester.exe
    echo ============================================================
    echo.
    if exist "dist\CF-IP-Tester.exe" (
        explorer.exe /select,"dist\CF-IP-Tester.exe"
    ) else if exist "dist" (
        explorer.exe "dist"
    )
    set "RUN_NOW=y"
    set /p "RUN_NOW=Would you like to run the built executable now? (y/n) [Default: y]: "
    if "!RUN_NOW!"=="" set "RUN_NOW=y"
    if /i "!RUN_NOW!"=="y" (
        start "" "dist\CF-IP-Tester.exe"
    )
) else (
    echo.
    echo [ERROR] Binary compilation failed.
)
echo.
goto :menu_loop

:exit_clean
echo.
echo [INFO] Exiting launcher.
exit /b 0
