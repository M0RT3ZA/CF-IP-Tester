#!/usr/bin/env bash
set -e

# Change directory to script folder
cd "$(dirname "$0")"

echo "============================================================"
echo "                CF IP Tester Launcher (Linux)"
echo "============================================================"
echo ""

# 1. Detect Python 3.11+
PY_CMD=""
for cand in python3 python python3.13 python3.12 python3.11; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >/dev/null 2>&1; then
            PY_CMD="$cand"
            break
        fi
    fi
done

# If Python 3.11+ is not found, offer automated installation with user permission
if [ -z "$PY_CMD" ]; then
    echo "[PROMPT] Python 3.11+ was not detected on your system."
    echo "Python 3.11 or higher is required to run CF IP Tester."
    echo ""
    read -r -p "Would you like to automatically install Python 3.11 now? (y/n) [Default: y]: " INSTALL_CHOICE
    INSTALL_CHOICE=${INSTALL_CHOICE:-y}

    if [ "$INSTALL_CHOICE" = "y" ] || [ "$INSTALL_CHOICE" = "Y" ]; then
        echo ""
        echo "[INFO] Detecting system package manager..."
        if command -v apt-get >/dev/null 2>&1; then
            echo "[INFO] Running: sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip"
            sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
        elif command -v dnf >/dev/null 2>&1; then
            echo "[INFO] Running: sudo dnf install -y python3 python3-pip"
            sudo dnf install -y python3 python3-pip
        elif command -v pacman >/dev/null 2>&1; then
            echo "[INFO] Running: sudo pacman -S --noconfirm python python-pip"
            sudo pacman -S --noconfirm python python-pip
        elif command -v zypper >/dev/null 2>&1; then
            echo "[INFO] Running: sudo zypper install -y python3 python3-pip"
            sudo zypper install -y python3 python3-pip
        else
            echo "[ERROR] Supported package manager not detected. Please install Python 3.11+ manually."
            exit 1
        fi

        for cand in python3 python python3.13 python3.12 python3.11; do
            if command -v "$cand" >/dev/null 2>&1; then
                if "$cand" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >/dev/null 2>&1; then
                    PY_CMD="$cand"
                    break
                fi
            fi
        done
    fi

    if [ -z "$PY_CMD" ]; then
        echo "[ERROR] Python 3.11+ could not be detected. Exiting."
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
    echo " [2] Build Standalone Executable (PyInstaller Binary)"
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

            echo "[INFO] Building standalone binary..."
            pyinstaller --noconsole --onefile --name "CF-IP-Tester" --clean main.py

            echo ""
            echo "============================================================"
            echo "[SUCCESS] Standalone binary created at:"
            echo " dist/CF-IP-Tester"
            echo "============================================================"
            echo ""
            if command -v xdg-open >/dev/null 2>&1; then
                xdg-open dist/ >/dev/null 2>&1 &
            fi
            read -r -p "Would you like to run the built binary now? (y/n) [Default: y]: " RUN_NOW
            RUN_NOW=${RUN_NOW:-y}
            if [ "$RUN_NOW" != "n" ] && [ "$RUN_NOW" != "N" ]; then
                chmod +x dist/CF-IP-Tester
                ./dist/CF-IP-Tester &
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
