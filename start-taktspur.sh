#!/usr/bin/env sh
cd "$(dirname "$0")" || exit 1
[ -x .venv/bin/python ] || { python3 -m venv .venv && .venv/bin/pip install -r requirements.txt; } || exit 1
echo "Taktspur läuft auf http://127.0.0.1:8775"
exec .venv/bin/python scripts/run_local.py
