"""Aktivitäten von Intervals.icu holen – ausschließlich LESEND (es werden nur GET-Anfragen gestellt).

- Zeitraum: die letzten X Tage (Einstellung `intervals_history_days`, Standard 30).
- Bereits vorhandene Aktivitäten (gleiche Intervals-ID) werden nicht doppelt angelegt; lokal gelöschte nicht erneut geholt.
- Mit Datei (FIT, mit Messkurven und RR-Intervallen) wird voll ausgewertet; ohne abrufbare Datei bleiben die Kennzahlen.
- Läuft im Hintergrund mit eigener Datenbankverbindung, damit der Start von Taktspur nicht blockiert.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import zlib
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from . import activities, db, fit_import, intervals, store
from .db import now_iso

ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")      # die ID landet in einer URL → streng prüfen
LAST_KEY = "intervals_last_sync"
_guard = threading.Lock()
_state = {"running": False, "started_at": None}


class _NoFile(Exception):
    pass


def state(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (LAST_KEY,)).fetchone()
    return {"running": _state["running"], "started_at": _state["started_at"], "last": json.loads(row["value"]) if row else None}


def _save(conn: sqlite3.Connection, result: dict[str, Any]) -> None:
    conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (LAST_KEY, json.dumps(result)))


def _unzip(content: bytes) -> bytes:
    if content[:2] != b"\x1f\x8b":
        return content
    d = zlib.decompressobj(31)
    out = d.decompress(content, fit_import.MAX_BYTES + 1)
    if d.unconsumed_tail or len(out) > fit_import.MAX_BYTES:
        raise _NoFile()
    return out


def _download(client: httpx.Client, ext: str) -> bytes:
    for path in (f"/activity/{ext}/fit-file", f"/activity/{ext}/file"):
        try:
            resp = client.get(path)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (403, 404, 422):
                continue
            raise
        data = _unzip(resp.content)
        if len(data) > 13 and data[8:12] == b".FIT":
            return data
    raise _NoFile()


def _begin() -> bool:
    with _guard:
        if _state["running"]:
            return False
        _state.update(running=True, started_at=now_iso())
        return True


def _end() -> None:
    with _guard:
        _state.update(running=False)


def _run(conn: sqlite3.Connection, days: int | None) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM integration WHERE provider='intervals_icu'").fetchone()
    if row is None:
        raise intervals.IntegrationError("not_connected", "Intervals.icu ist nicht verbunden. Bitte unter Einstellungen verbinden.", 409)
    days = days or store.get_settings(conn)["intervals_history_days"]
    today = date.today()
    result: dict[str, Any] = {"at": now_iso(), "days": days, "found": 0, "imported": 0, "summary_only": 0, "already": 0, "failed": [], "error": None}
    try:
        key = intervals.decrypt(row["encrypted_key"])
        with intervals.client_factory(key) as client:
            try:
                resp = client.get(f"/athlete/{row['athlete_id']}/activities", params={"oldest": (today - timedelta(days=days)).isoformat(), "newest": (today + timedelta(days=1)).isoformat()})
                resp.raise_for_status()
                items = resp.json()
            except httpx.HTTPError as exc:
                raise intervals.translate_http(exc, context="sync") from None
            except ValueError:
                raise intervals.IntegrationError("bad_response", "Intervals.icu hat eine unlesbare Antwort geliefert.", 502) from None
            if not isinstance(items, list):
                raise intervals.IntegrationError("bad_response", "Intervals.icu hat eine unerwartete Antwort geliefert.", 502)
            items = [i for i in items if isinstance(i, dict)]
            result["found"] = len(items)
            for item in sorted(items, key=lambda i: str(i.get("start_date") or i.get("start_date_local") or "")):
                ext = item.get("id")
                if not isinstance(ext, str) or not ID_PATTERN.match(ext):
                    continue
                if conn.execute("SELECT 1 FROM activities WHERE external_id=?", (ext,)).fetchone() or conn.execute("SELECT 1 FROM activity_ignored WHERE external_id=?", (ext,)).fetchone():
                    result["already"] += 1
                    continue
                name = str(item.get("name") or item.get("type") or "Aktivität").replace("/", "-").replace("\\", "-")
                try:
                    try:
                        data = _download(client, ext)
                        activities.import_fit(conn, data, name, source="intervals", external_id=ext)
                        result["imported"] += 1
                    except (_NoFile, store.Rejected) as exc:
                        if isinstance(exc, store.Rejected) and exc.status == 409:
                            result["already"] += 1
                            continue
                        activities.import_summary(conn, item)         # keine (lesbare) Datei → nur Kennzahlen
                        result["summary_only"] += 1
                except httpx.HTTPError as exc:
                    err = intervals.translate_http(exc, context="sync")
                    if err.code == "rate_limited":
                        result["error"] = err.message + " Der Rest folgt beim nächsten Abgleich."
                        break
                    result["failed"].append(f"{name}: {err.message}"[:200])
                except Exception:                                      # eine kaputte Aktivität stoppt nicht den ganzen Abgleich
                    result["failed"].append(f"{name}: konnte nicht verarbeitet werden.")
    except intervals.IntegrationError as exc:
        result["error"] = exc.message
        _save(conn, result)
        intervals._log(conn, "error", "sync", exc.message)
        raise
    result["failed"] = result["failed"][:10]
    _save(conn, result)
    intervals._log(conn, "error" if result["failed"] or result["error"] else "success", "sync",
                   f"Abgleich: {result['found']} gefunden, {result['imported']} importiert, {result['summary_only']} nur Kennzahlen, {result['already']} schon vorhanden, {len(result['failed'])} Fehler")
    return result


def run(conn: sqlite3.Connection, days: int | None = None) -> dict[str, Any]:
    """Synchron ausführen (Tests, Skripte)."""
    if not _begin():
        raise store.Rejected("Ein Abgleich läuft bereits.", 409)
    try:
        return _run(conn, days)
    finally:
        _end()


def start_background(db_path: Path | None, days: int | None = None) -> bool:
    """Startet den Abgleich im Hintergrund (eigene DB-Verbindung). False, wenn schon einer läuft."""
    if not _begin():
        return False

    def worker() -> None:
        c = db.connect(db_path)
        try:
            _run(c, days)
        except Exception:                      # Fehler stehen bereits im Ergebnis/Protokoll (ohne Schlüssel)
            pass
        finally:
            c.close()
            _end()

    threading.Thread(target=worker, name="intervals-sync", daemon=True).start()
    return True


def wanted_on_start(conn: sqlite3.Connection) -> bool:
    return bool(conn.execute("SELECT 1 FROM integration WHERE provider='intervals_icu'").fetchone()) and store.get_settings(conn)["intervals_sync_on_start"]
