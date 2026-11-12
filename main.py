#!/usr/bin/env python3
"""
CF IP Tester: Production-grade Cloudflare edge IP and proxy domain benchmarking suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is present on sys.path for direct script execution
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.ui.main_window import launch


def main() -> None:
    launch()


if __name__ == "__main__":
    main()
