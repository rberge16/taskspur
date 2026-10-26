#!/usr/bin/env sh
cd "$(dirname "$0")" || exit 1
[ -x .venv/bin/python ] || python3 -m venv .venv || { echo "FEHLER: python3 -m venv fehlgeschlagen"; exit 1; }
if ! cmp -s requirements.txt .venv/installed-requirements.txt; then
  echo "Installiere benötigte Pakete ..."
  .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt || { echo "FEHLER: Paketinstallation fehlgeschlagen"; exit 1; }
  cp requirements.txt .venv/installed-requirements.txt
fi
exec .venv/bin/python scripts/run_local.py
