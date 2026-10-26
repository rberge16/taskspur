"""Konfiguration. Alle Pfade und Ports an einer Stelle.

Port 8765 gehört der Waterkotte-App und wird von Taktspur niemals benutzt.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PORT = 8775
FORBIDDEN_PORTS = {8765}
DB_FILENAME = "taktspur2.sqlite3"  # bewusst anderer Name als die Datei der Vorgängerversion
BACKUP_KEEP = 14


def data_dir() -> Path:
    override = os.environ.get("TAKTSPUR_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "Taktspur" / "data"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Taktspur" / "data"
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "taktspur" / "data"


def db_path() -> Path:
    return data_dir() / DB_FILENAME


def bind_host() -> str:
    """Standard: nur lokal. Für den Raspberry Pi im Heimnetz per TAKTSPUR_HOST=0.0.0.0."""
    return os.environ.get("TAKTSPUR_HOST", "127.0.0.1")


def allowed_hosts() -> set[str]:
    """Erlaubte Host-Header (Schutz gegen DNS-Rebinding)."""
    hosts = {f"127.0.0.1:{PORT}", f"localhost:{PORT}", "127.0.0.1", "localhost"}
    extra = os.environ.get("TAKTSPUR_ALLOWED_HOSTS", "")
    for item in extra.split(","):
        item = item.strip()
        if item:
            hosts.add(item)
            hosts.add(f"{item}:{PORT}")
    return hosts
