# CF IP Tester Launcher for PowerShell (Windows)
[CmdletBinding()]
param (
    [Parameter(Position = 0)]
    [string]$Choice = "",
    [switch]$ElevatedRetry
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Set working directory to script directory
Set-Location -LiteralPath $PSScriptRoot

# Setup and builds write to the project directory. Ask for elevation only if
# the current user cannot create a file there, and never retry indefinitely.
$probe = Join-Path $PSScriptRoot ('.write-test-' + [guid]::NewGuid().ToString('N'))
try {
    $stream = [System.IO.File]::Open($probe, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write)
    $stream.Dispose()
    Remove-Item -LiteralPath $probe -Force
} catch {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if ($ElevatedRetry -or $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Host '[ERROR] Cannot write to the project directory, even with administrator privileges. Check its permissions or move the project.' -ForegroundColor Red
        exit 1
    }
    Write-Host '[INFO] The project directory is not writable. Requesting administrator permission...' -ForegroundColor Yellow
    $arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"'
    if ($Choice) { $arguments += ' -Choice "' + $Choice.Replace('"', '') + '"' }
    $arguments += ' -ElevatedRetry'
    try {
        $process = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -Verb RunAs -Wait -PassThru
        exit $process.ExitCode
    } catch {
        Write-Host '[ERROR] Administrator permission was not granted or the launcher could not be started.' -ForegroundColor Red
        exit 1
    }
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "           CF IP Tester Launcher (PowerShell)" -ForegroundColor Cyan
Write-Host "============================================================`n" -ForegroundColor Cyan

# 1. Detect Python 3.11+
function Test-PythonCandidate([string]$exePath) {
    if (-not $exePath) { return $false }
    try {
        $p = Start-Process -FilePath $exePath -ArgumentList "-c `"import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)`"" -NoNewWindow -Wait -PassThru -ErrorAction SilentlyContinue
        return ($p.ExitCode -eq 0)
    } catch {
        return $false
    }
}

$pyCmd = $null

# Check PATH candidates
$candidates = @("python.exe", "python3.exe", "py.exe")
foreach ($c in $candidates) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd -and (Test-PythonCandidate $cmd.Source)) {
        $pyCmd = $cmd.Source
        break
    }
}

# Check standard installation directories
if (-not $pyCmd) {
    $dirs = @(
        "$env:ProgramFiles\Python311\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python313\python.exe",
        "${env:ProgramFiles(x86)}\Python311\python.exe",
        "${env:ProgramFiles(x86)}\Python312\python.exe",
        "${env:ProgramFiles(x86)}\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
    )
    foreach ($d in $dirs) {
        if ((Test-Path $d) -and (Test-PythonCandidate $d)) {
            $pyCmd = $d
            break
        }
    }
}

# Check py -3
if (-not $pyCmd) {
    $pyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        try {
            $p = Start-Process -FilePath "py.exe" -ArgumentList "-3", "-c", "`"import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)`"" -NoNewWindow -Wait -PassThru -ErrorAction SilentlyContinue
            if ($p.ExitCode -eq 0) {
                $pyCmd = "py -3"
            }
        } catch {}
    }
}

# If Python 3.11+ is still not found, prompt user for automated installation
if (-not $pyCmd) {
    Write-Host "[PROMPT] Python 3.11+ was not detected on your system." -ForegroundColor Yellow
    Write-Host "Python 3.11 or higher is required to run CF IP Tester.`n"
    $installChoice = Read-Host "Would you like to automatically download and install Python 3.11 now? (y/n) [Default: y]"
    if (-not $installChoice) { $installChoice = "y" }

    if ($installChoice -ne "y" -and $installChoice -ne "Y") {
        Write-Host "`n[ERROR] Installation cancelled. Please install Python 3.11+ from https://www.python.org/" -ForegroundColor Red
        Read-Host "Press Enter to exit..."
        exit 1
    }

    Write-Host "`n============================================================" -ForegroundColor Cyan
    Write-Host "[INFO] Starting automated Python 3.11 installation..." -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan

    # Attempt 1: winget
    $wingetCmd = Get-Command "winget.exe" -ErrorAction SilentlyContinue
    if ($wingetCmd) {
        Write-Host "[INFO] Installing Python 3.11 via Windows Package Manager (winget)..." -ForegroundColor Yellow
        try {
            Start-Process "winget.exe" -ArgumentList "install --id Python.Python.3.11 --exact --scope user --silent --accept-package-agreements --accept-source-agreements" -NoNewWindow -Wait
        } catch {
            Write-Host '[WARNING] winget could not start; trying the official installer.' -ForegroundColor Yellow
        }
    }

    # Re-check standard directories
    $postDirs = @(
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python311\python.exe"
    )
    foreach ($pd in $postDirs) {
        if ((Test-Path $pd) -and (Test-PythonCandidate $pd)) {
            $pyCmd = $pd
            break
        }
    }

    # Attempt 2: Direct official download from python.org
    if (-not $pyCmd) {
        Write-Host "[INFO] Downloading official Python 3.11 installer from python.org..." -ForegroundColor Yellow
        $installerPath = Join-Path $env:TEMP "python-3.11.9-amd64.exe"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $ProgressPreference = 'SilentlyContinue'
        try {
            Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" -OutFile $installerPath -UseBasicParsing
        } catch {
            Write-Host "[ERROR] Python download failed: $_" -ForegroundColor Red
            exit 1
        }

        if (Test-Path $installerPath) {
            Write-Host "[INFO] Running Python 3.11 installer silently..." -ForegroundColor Yellow
            Start-Process -FilePath $installerPath -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0 SimpleInstall=1" -Wait
            Remove-Item -Force $installerPath -ErrorAction SilentlyContinue
        }
    }

    # Final post-install check
    foreach ($pd in $postDirs) {
        if ((Test-Path $pd) -and (Test-PythonCandidate $pd)) {
            $pyCmd = $pd
            break
        }
    }

    if (-not $pyCmd) {
        Write-Host "[ERROR] Automated installation could not be completed." -ForegroundColor Red
        Write-Host "Please install Python 3.11+ manually from https://www.python.org/"
        Read-Host "Press Enter to exit..."
        exit 1
    }

    Write-Host "[SUCCESS] Python 3.11 installed successfully at: $pyCmd`n" -ForegroundColor Green
}

Write-Host "[INFO] Using Python: $pyCmd" -ForegroundColor Green

# 2. Virtual environment setup
if (-not (Test-Path ".venv")) {
    Write-Host "[INFO] Creating virtual environment (.venv)..." -ForegroundColor Yellow
    if ($pyCmd -eq "py -3") {
        py -3 -m venv .venv
    } else {
        & $pyCmd -m venv .venv
    }
    if ($LASTEXITCODE -ne 0) { Write-Host '[ERROR] Failed to create the virtual environment.' -ForegroundColor Red; exit 1 }
    Write-Host "[INFO] Virtual environment created successfully." -ForegroundColor Green
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) { Write-Host '[ERROR] The .venv directory is incomplete. Repair or remove it and run the launcher again.' -ForegroundColor Red; exit 1 }

# 3. Check and install dependencies
$depCheck = Start-Process -FilePath $venvPython -ArgumentList "-c `"import PySide6, openpyxl, xlrd, xlwt`"" -NoNewWindow -Wait -PassThru -ErrorAction SilentlyContinue
if ($depCheck.ExitCode -ne 0) {
    Write-Host "[INFO] Installing required dependencies from requirements.txt..." -ForegroundColor Yellow
    Start-Process -FilePath $venvPython -ArgumentList "-m pip install --upgrade pip" -NoNewWindow -Wait
    $installProc = Start-Process -FilePath $venvPython -ArgumentList "-m pip install -r requirements.txt" -NoNewWindow -Wait -PassThru
    if ($installProc.ExitCode -ne 0) { Write-Host '[ERROR] Failed to install dependencies.' -ForegroundColor Red; exit 1 }
    Write-Host "[INFO] Dependencies installed successfully.`n" -ForegroundColor Green
}

# 4. Interactive menu loop
$initialChoice = $Choice

while ($true) {
    if ($initialChoice) {
        $userChoice = $initialChoice
        $initialChoice = ""
    } else {
        Write-Host "`n============================================================" -ForegroundColor Cyan
        Write-Host " [1] Launch CF IP Tester GUI (Default)"
        Write-Host " [2] Build Standalone Executable (PyInstaller Binary)"
        Write-Host " [0] Exit"
        Write-Host "============================================================" -ForegroundColor Cyan
        $userChoice = Read-Host "Enter selection [1, 2, or 0] (Default: 1)"
        if (-not $userChoice) { $userChoice = "1" }
    }

    switch ($userChoice) {
        "2" {
            Write-Host "`n[INFO] Checking PyInstaller..." -ForegroundColor Yellow
            $piCheck = Start-Process -FilePath $venvPython -ArgumentList "-c `"import PyInstaller`"" -NoNewWindow -Wait -PassThru -ErrorAction SilentlyContinue
            if ($piCheck.ExitCode -ne 0) {
                Write-Host "[INFO] Installing PyInstaller..." -ForegroundColor Yellow
                Start-Process -FilePath $venvPython -ArgumentList "-m pip install pyinstaller" -NoNewWindow -Wait
            }

            Write-Host "[INFO] Building standalone binary..." -ForegroundColor Cyan
            $pyiExe = Join-Path $PSScriptRoot ".venv\Scripts\pyinstaller.exe"
            $buildProc = Start-Process -FilePath $pyiExe -ArgumentList "--noconsole --onefile --name `"CF-IP-Tester`" --clean main.py" -NoNewWindow -Wait -PassThru

            if ($buildProc.ExitCode -eq 0) {
                $binPath = Join-Path $PSScriptRoot "dist\CF-IP-Tester.exe"
                Write-Host "`n============================================================" -ForegroundColor Green
                Write-Host "[SUCCESS] Standalone executable created at:" -ForegroundColor Green
                Write-Host " $binPath" -ForegroundColor Green
                Write-Host "============================================================`n" -ForegroundColor Green

                # Automatically reveal the built binary in Windows Explorer
                if (Test-Path $binPath) {
                    Start-Process "explorer.exe" -ArgumentList "/select,`"$binPath`""
                } else {
                    Start-Process "explorer.exe" -ArgumentList "`"$PSScriptRoot\dist`""
                }

                $runNow = Read-Host "Would you like to run the built executable now? (y/n) [Default: y]"
                if ($runNow -ne "n" -and $runNow -ne "N") {
                    Start-Process $binPath
                }
            } else {
                Write-Host "`n[ERROR] Binary compilation failed." -ForegroundColor Red
            }
        }
        "0" {
            Write-Host "`n[INFO] Exiting launcher." -ForegroundColor Cyan
            exit 0
        }
        "3" {
            Write-Host "`n[INFO] Exiting launcher." -ForegroundColor Cyan
            exit 0
        }
        Default {
            Write-Host "`n[INFO] Starting CF IP Tester GUI..." -ForegroundColor Green
            # Run GUI synchronously and wait so when user closes the app, it loops back to the launcher menu
            $guiProc = Start-Process -FilePath $venvPython -ArgumentList "main.py" -NoNewWindow -Wait -PassThru
            Write-Host "[INFO] Application closed. Returning to launcher menu..." -ForegroundColor Cyan
        }
    }
}
