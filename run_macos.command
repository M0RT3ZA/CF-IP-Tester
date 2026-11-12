#!/usr/bin/env bash
set -e

# Change directory to project root directory
cd "$(dirname "$0")"

echo "============================================================"
echo "                CF IP Tester Launcher (macOS)"
echo "============================================================"
echo ""

# 1. Detect Python 3.11+
PY_CMD=""
for cand in python3 python3.13 python3.12 python3.11 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >/dev/null 2>&1; then
            PY_CMD="$cand"
            break
        fi
    fi
done

# Check common macOS paths
if [ -z "$PY_CMD" ]; then
    for cand in /opt/homebrew/bin/python3 /usr/local/bin/python3 /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 /Library/Frameworks/Python.framework/Versions/3.12/bin/python3; do
        if [ -x "$cand" ]; then
            if "$cand" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >/dev/null 2>&1; then
                PY_CMD="$cand"
                break
            fi
        fi
    done
fi

# If Python 3.11+ is not found, offer automated installation with user permission
if [ -z "$PY_CMD" ]; then
    echo "[PROMPT] Python 3.11+ was not detected on your system."
    echo "Python 3.11 or higher is required to run CF IP Tester."
    echo ""
    read -r -p "Would you like to automatically install Python 3.11 now? (y/n) [Default: y]: " INSTALL_CHOICE
    INSTALL_CHOICE=${INSTALL_CHOICE:-y}

    if [ "$INSTALL_CHOICE" = "y" ] || [ "$INSTALL_CHOICE" = "Y" ]; then
        if command -v brew >/dev/null 2>&1; then
            echo "[INFO] Installing Python 3.11 via Homebrew..."
            brew install python@3.11
            PY_CMD="$(brew --prefix)/bin/python3.11"
        else
            echo "[INFO] Homebrew not found. Downloading official macOS Python installer..."
            PKG_PATH="/tmp/python-3.11.9-macos11.pkg"
            curl -fsSL "https://www.python.org/ftp/python/3.11.9/python-3.11.9-macos11.pkg" -o "$PKG_PATH"
            echo "[INFO] Running installer (administrator password may be requested)..."
            sudo installer -pkg "$PKG_PATH" -target /
            rm -f "$PKG_PATH"
            PY_CMD="/usr/local/bin/python3"
        fi
    fi

    if [ -z "$PY_CMD" ] || ! [ -x "$PY_CMD" ]; then
        echo "[ERROR] Python 3.11+ could not be detected. Exiting."
        read -r -p "Press Enter to exit..."
        exit 1
    fi
fi

echo "[INFO] Using Python: $PY_CMD"

# 2. Virtual environment management
if [ ! -d ".venv" ]; then
    echo "[INFO] Creating virtual environment (.venv)..."
    $PY_CMD -m venv .venv
    echo "[INFO] Virtual environment created successfully."
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# 3. Check and install dependencies
if ! python -c "import PySide6, openpyxl, xlrd, xlwt" >/dev/null 2>&1; then
    echo "[INFO] Installing required dependencies from requirements.txt..."
    python -m pip install --upgrade pip >/dev/null 2>&1 || true
    python -m pip install -r requirements.txt
    echo "[INFO] Dependencies installed successfully."
    echo ""
fi

# 4. Interactive menu loop
while true; do
    echo ""
    echo "============================================================"
    echo " [1] Launch CF IP Tester GUI (Default)"
    echo " [2] Build Standalone Application (PyInstaller .app/binary)"
    echo " [0] Exit"
    echo "============================================================"
    read -r -p "Enter selection [1, 2, or 0] (Default: 1): " USER_CHOICE
    USER_CHOICE=${USER_CHOICE:-1}

    case "$USER_CHOICE" in
        2)
            echo ""
            echo "[INFO] Checking PyInstaller..."
            if ! python -c "import PyInstaller" >/dev/null 2>&1; then
                echo "[INFO] Installing PyInstaller..."
                python -m pip install pyinstaller
            fi

            echo "[INFO] Building standalone binary for macOS..."
            pyinstaller --noconsole --onefile --name "CF-IP-Tester" --clean main.py

            echo ""
            echo "============================================================"
            echo "[SUCCESS] Standalone binary created at:"
            echo " dist/CF-IP-Tester"
            echo "============================================================"
            echo ""
            open -R "dist/CF-IP-Tester" 2>/dev/null || open "dist"
            read -r -p "Would you like to run the built application now? (y/n) [Default: y]: " RUN_NOW
            RUN_NOW=${RUN_NOW:-y}
            if [ "$RUN_NOW" != "n" ] && [ "$RUN_NOW" != "N" ]; then
                chmod +x dist/CF-IP-Tester
                open dist/CF-IP-Tester
            fi
            ;;
        0|3)
            echo ""
            echo "[INFO] Exiting launcher."
            exit 0
            ;;
        *)
            echo ""
            echo "[INFO] Starting CF IP Tester GUI..."
            python main.py
            echo ""
            echo "[INFO] Application closed. Returning to launcher menu..."
            ;;
    esac
done
