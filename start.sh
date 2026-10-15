#!/usr/bin/env bash
# Antigravity Server 1-Click Launcher (Linux / macOS)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

echo "========================================================"
echo "       Starting Antigravity Server on this Device       "
echo "========================================================"

if command -v python3 >/dev/null 2>&1; then
    python3 run.py
elif command -v python >/dev/null 2>&1; then
    python run.py
else
    echo "[!] Python 3 is required. Please install python3 first."
    exit 1
fi
