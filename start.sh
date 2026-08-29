#!/usr/bin/env bash
# ATLAS launcher for macOS / Linux. Double-click or run: ./start.sh
set -e
cd "$(dirname "$0")"
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then exec "$c" run.py "$@"; fi
done
echo "Python 3.10+ is required but was not found."
echo "Install it from https://python.org/downloads and run this again."
exit 1
