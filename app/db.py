"""SQLite-Schicht: Verbindung, versionierte Migrationen, Backup.

Regeln:
- Eine vorhandene Datenbank wird niemals ersetzt oder geleert. Migrationen sind rein additiv
  und werden über PRAGMA user_version nachgehalten.
- Vor jeder Migration, die etwas ändert, entsteht ein konsistentes Backup (SQLite-Backup-API).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config

MIGRATIONS: list[str] = [
    # 1: Kern
    """
    CREATE TABLE plans (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        goal_date TEXT,
        status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('draft','active','inactive')),
        color INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE phases (
        id TEXT PRIMARY KEY,
        plan_id TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        position INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX idx_phases_plan ON phases(plan_id);
    CREATE TABLE workouts (
        id TEXT PRIMARY KEY,
        plan_id TEXT REFERENCES plans(id) ON DELETE SET NULL,
        phase_id TEXT REFERENCES phases(id) ON DELETE SET NULL,
        date TEXT,
        start_time TEXT,
        sport TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT 'normal' CHECK (kind IN ('normal','important','test')),
        duration_min INTEGER NOT NULL DEFAULT 0,
        tss INTEGER NOT NULL DEFAULT 0,
        steps_json TEXT NOT NULL DEFAULT '[]',
        link_group TEXT,
        link_order INTEGER CHECK (link_order IN (1,2)),
        origin TEXT NOT NULL DEFAULT 'taktspur' CHECK (origin IN ('taktspur','intervals','completed')),
        ext_id TEXT,
        sync_status TEXT NOT NULL DEFAULT 'none' CHECK (sync_status IN ('none','sending','sent','error')),
        sync_error TEXT,
        synced_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_workouts_date ON workouts(date);
    CREATE INDEX idx_workouts_link ON workouts(link_group);
    CREATE UNIQUE INDEX idx_workouts_link_unique ON workouts(link_group, link_order) WHERE link_group IS NOT NULL;
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE integration (
        provider TEXT PRIMARY KEY,
        athlete_id TEXT NOT NULL,
        encrypted_key TEXT NOT NULL,
        verified_at TEXT,
        last_error TEXT
    );
    CREATE TABLE integration_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        level TEXT NOT NULL,
        action TEXT NOT NULL,
        message TEXT NOT NULL,
        workout_id TEXT
    );
    """,
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    target = str(path if path is not None else config.db_path())
    conn = sqlite3.connect(target, timeout=5.0, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    if target != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def backup(path: Path, keep: int = config.BACKUP_KEEP) -> Path | None:
    """Konsistentes Backup inkl. noch nicht zusammengeführter WAL-Daten. Alte Backups werden begrenzt."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    folder = path.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    target = folder / f"{path.stem}-{stamp}.sqlite3"
    src = sqlite3.connect(str(path))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    existing = sorted(folder.glob(f"{path.stem}-*.sqlite3"))
    for old in existing[:-keep] if keep > 0 else []:
        try:
            old.unlink()
        except OSError:
            pass
    return target


def migrate(conn: sqlite3.Connection) -> int:
    """Spielt fehlende Migrationen ein. Jede läuft in einer Transaktion."""
    current = schema_version(conn)
    if current > len(MIGRATIONS):
        raise RuntimeError(
            f"Die Datenbank hat Schema-Version {current}, diese Taktspur-Version kennt nur {len(MIGRATIONS)}. "
            "Bitte Taktspur aktualisieren; es wurde nichts verändert."
        )
    for version in range(current + 1, len(MIGRATIONS) + 1):
        conn.execute("BEGIN")
        try:
            for statement in _split(MIGRATIONS[version - 1]):
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version={version}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return schema_version(conn)


def _split(script: str) -> list[str]:
    return [part.strip() for part in script.split(";") if part.strip()]


def open_database(path: Path | None = None, *, make_backup: bool = True) -> sqlite3.Connection:
    """Öffnet die Datenbank (legt sie nur an, wenn sie fehlt), sichert und migriert."""
    target = Path(path) if path is not None else config.db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists() and target.stat().st_size > 0
    if existed and make_backup:
        backup(target)  # bei jedem Start, immer vor einer Migration
    conn = connect(target)
    migrate(conn)
    return conn
