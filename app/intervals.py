"""Intervals.icu-Anbindung – ausschließlich serverseitig.

- Der API-Schlüssel wird verschlüsselt gespeichert und verlässt das Backend nie (nicht in Antworten, Logs, Fehlertexten).
- Geschrieben/gelöscht wird nur, was in der eigenen Datenbank als origin='taktspur' existiert.
  Die externe ID wird serverseitig aus der Workout-ID gebildet – der Browser kann keine fremde ID einschleusen.
- Der HTTP-Client ist austauschbar (Tests nutzen httpx.MockTransport, es gehen keine echten Daten raus).
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Callable

import httpx
from cryptography.fernet import Fernet, InvalidToken

from . import config, store
from .db import now_iso

BASE_URL = "https://intervals.icu/api/v1"
SPORT_TYPES = {"Radfahren": "Ride", "Laufen": "Run", "Schwimmen": "Swim", "Kraft / Mobility": "WeightTraining", "Recovery": "Other"}

# Austauschbar für Tests: liefert einen httpx.Client
client_factory: Callable[[str], httpx.Client] = lambda api_key: httpx.Client(base_url=BASE_URL, timeout=15.0, auth=("API_KEY", api_key))


class IntegrationError(Exception):
    """Fehler mit verständlicher, für die Oberfläche bestimmter Meldung (nie mit Schlüssel)."""

    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


# ---------- Verschlüsselung ----------

def _key_file():
    return config.data_dir() / "secret.key"


def _fernet() -> Fernet:
    env = os.environ.get("TAKTSPUR_SECRET_KEY")
    if env:
        return Fernet(env.encode())
    path = _key_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(Fernet.generate_key())
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return Fernet(path.read_bytes().strip())


def encrypt(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise IntegrationError("key_unreadable", "Der gespeicherte API-Schlüssel kann nicht gelesen werden (Schlüsseldatei fehlt oder wurde ersetzt). Bitte neu verbinden.", 409) from exc


# ---------- Fehlerübersetzung ----------

def translate_http(exc: httpx.HTTPError, *, context: str) -> IntegrationError:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return IntegrationError("bad_credentials", "Intervals.icu hat den API-Schlüssel abgelehnt. Bitte Schlüssel prüfen und neu verbinden.")
        if code == 404:
            return IntegrationError("athlete_not_found", "Intervals.icu kennt diese Athleten-ID nicht. Bitte die ID (Format i12345) prüfen.")
        if code == 429:
            return IntegrationError("rate_limited", "Intervals.icu begrenzt gerade die Anfragen. Bitte in einer Minute erneut versuchen.", 503)
        if 500 <= code <= 599:
            return IntegrationError("provider_down", f"Intervals.icu hat einen Serverfehler gemeldet (HTTP {code}). Bitte später erneut versuchen.", 503)
        if context == "sync":
            return IntegrationError("rejected", f"Intervals.icu hat die Anfrage abgelehnt (HTTP {code}).")
        return IntegrationError("rejected", f"Intervals.icu hat das Workout abgelehnt (HTTP {code}). Bitte Struktur und Datum prüfen.")
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError)):
        return IntegrationError("unreachable", "Intervals.icu ist nicht erreichbar. Bitte Internetverbindung prüfen und erneut versuchen.", 503)
    return IntegrationError("unreachable", "Die Verbindung zu Intervals.icu ist fehlgeschlagen.", 503)


def _log(conn: sqlite3.Connection, level: str, action: str, message: str, workout_id: str | None = None) -> None:
    conn.execute("INSERT INTO integration_log(at,level,action,message,workout_id) VALUES(?,?,?,?,?)", (now_iso(), level, action, message[:500], workout_id))
    conn.execute("DELETE FROM integration_log WHERE id NOT IN (SELECT id FROM integration_log ORDER BY id DESC LIMIT 200)")


# ---------- Verbindung ----------

def status(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM integration WHERE provider='intervals_icu'").fetchone()
    if row is None:
        return {"connected": False}
    # has_key: ein Schlüssel ist gespeichert (der Schlüssel selbst verlässt das Backend nie)
    return {"connected": row["last_error"] is None, "athlete_id": row["athlete_id"], "verified_at": row["verified_at"], "last_error": row["last_error"], "has_key": True}


def connect(conn: sqlite3.Connection, athlete_id: str, api_key: str) -> dict[str, Any]:
    try:
        with client_factory(api_key) as client:
            response = client.get(f"/athlete/{athlete_id}")
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise translate_http(exc, context="connect") from None  # `from None`: kein Schlüssel in Tracebacks
    stamp = now_iso()
    conn.execute(
        """INSERT INTO integration(provider,athlete_id,encrypted_key,verified_at,last_error) VALUES('intervals_icu',?,?,?,NULL)
           ON CONFLICT(provider) DO UPDATE SET athlete_id=excluded.athlete_id, encrypted_key=excluded.encrypted_key,
                                               verified_at=excluded.verified_at, last_error=NULL""",
        (athlete_id, encrypt(api_key), stamp),
    )
    _log(conn, "success", "connect", "Intervals.icu verbunden")
    return status(conn)


def verify(conn: sqlite3.Connection) -> dict[str, Any]:
    """Erneute Prüfung (z. B. nach einem Neustart). Meldet verständlich, wenn Intervals.icu nicht antwortet."""
    row = conn.execute("SELECT * FROM integration WHERE provider='intervals_icu'").fetchone()
    if row is None:
        return {"connected": False}
    try:
        key = decrypt(row["encrypted_key"])
        with client_factory(key) as client:
            client.get(f"/athlete/{row['athlete_id']}").raise_for_status()
    except IntegrationError as exc:
        conn.execute("UPDATE integration SET last_error=? WHERE provider='intervals_icu'", (exc.message,))
        return status(conn)
    except httpx.HTTPError as exc:
        err = translate_http(exc, context="verify")
        conn.execute("UPDATE integration SET last_error=? WHERE provider='intervals_icu'", (err.message,))
        return status(conn)
    conn.execute("UPDATE integration SET verified_at=?, last_error=NULL WHERE provider='intervals_icu'", (now_iso(),))
    return status(conn)


def disconnect(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM integration WHERE provider='intervals_icu'")
    _log(conn, "success", "disconnect", "Intervals.icu getrennt")


# ---------- Workout → Intervals-Ereignis ----------

def _dur(d: dict) -> str:
    unit = {"sec": "s", "min": "m", "km": "km"}[d["unit"]]
    return f"{d['value']}{unit}"


def _target(t: dict, ftp: int | None, lthr: int | None) -> str:
    if t["type"] == "open":
        return ""
    low, high = t.get("min"), t.get("max")
    if low and high:
        if t["type"] == "power":
            return f" {low}-{high}w"
        if lthr:
            return f" {round(low / lthr * 100)}-{round(high / lthr * 100)}% LTHR"
    return f" {t.get('zone') or 'Z1'}" + (" HR" if t["type"] == "heart_rate" else "")


def build_description(workout: dict[str, Any], ftp: int | None, lthr: int | None) -> str:
    lines: list[str] = []
    if workout["description"]:
        lines += [workout["description"], ""]
    for step in workout["steps"]:
        if step["type"] == "cycle":
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"{step['repeats']}x")
            lines.append(f"- {_dur(step['work']['duration'])}{_target(step['work']['target'], ftp, lthr)} intensity=interval")
            lines.append(f"- {_dur(step['recovery']['duration'])}{_target(step['recovery']['target'], ftp, lthr)} intensity=recovery")
            lines.append("")
        else:
            extra = {"warmup": " intensity=warmup", "cooldown": " intensity=cooldown"}.get(step["type"], "")
            lines.append(f"- {_dur(step['duration'])}{_target(step['target'], ftp, lthr)}{extra}")
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _target_kind(steps: list[dict]) -> str | None:
    kinds = []
    for step in steps:
        blocks = [step["work"], step["recovery"]] if step["type"] == "cycle" else [step]
        kinds += [b["target"]["type"] for b in blocks]
    return "POWER" if "power" in kinds else "HR" if "heart_rate" in kinds else None


def build_event(workout: dict[str, Any], ftp: int | None, lthr: int | None) -> dict[str, Any]:
    event: dict[str, Any] = {
        "category": "WORKOUT",
        "type": SPORT_TYPES.get(workout["sport"], "Other"),
        "name": workout["title"],
        "start_date_local": f"{workout['date']}T{workout['start_time'] or '00:00'}:00",
        "description": build_description(workout, ftp, lthr),
        "moving_time": workout["duration_min"] * 60,
        "icu_training_load": workout["tss"],
        "external_id": store.external_id(workout["id"]),
    }
    target = _target_kind(workout["steps"])
    if target:
        event["target"] = target
    return event


# ---------- Senden / Löschen ----------

def validate_sendable(workout: dict[str, Any]) -> None:
    if workout["read_only"]:
        raise IntegrationError("read_only", "Aus Intervals.icu importierte oder absolvierte Einheiten sind schreibgeschützt und werden nie zurückgeschrieben.", 403)
    if not workout["date"]:
        raise IntegrationError("date_missing", "Datum fehlt. Bitte zuerst ein Datum für die Einheit festlegen.")
    if not workout["steps"]:
        raise IntegrationError("steps_missing", "Abschnitt fehlt. Bitte mindestens einen strukturierten Abschnitt hinzufügen.")


def _credentials(conn: sqlite3.Connection) -> tuple[str, str]:
    row = conn.execute("SELECT * FROM integration WHERE provider='intervals_icu'").fetchone()
    if row is None:
        raise IntegrationError("not_connected", "Intervals.icu ist nicht verbunden. Bitte zuerst in den Einstellungen verbinden.", 409)
    return row["athlete_id"], decrypt(row["encrypted_key"])


def send_workout(conn: sqlite3.Connection, workout_id: str, *, automatic: bool = False) -> dict[str, Any]:
    """Überträgt genau diese Einheit (Upsert über die stabile externe ID). Setzt den Status sichtbar:
    sending → sent | error."""
    workout = store.get_workout(conn, workout_id)
    try:
        validate_sendable(workout)
        athlete_id, key = _credentials(conn)
    except IntegrationError as exc:
        _mark(conn, workout_id, "error", exc.message)
        _log(conn, "error", "send", f"{workout['title']}: {exc.message}", workout_id)
        raise
    _mark(conn, workout_id, "sending", None)
    settings = store.get_settings(conn)
    event = build_event(workout, settings["ftp"], settings["lthr"])
    try:
        with client_factory(key) as client:
            response = client.post(f"/athlete/{athlete_id}/events/bulk", params={"upsert": "true"}, json=[event])
            response.raise_for_status()
    except httpx.HTTPError as exc:
        err = translate_http(exc, context="send")
        _mark(conn, workout_id, "error", err.message)
        _log(conn, "error", "send", f"{workout['title']}: {err.message}", workout_id)
        raise err from None
    conn.execute("UPDATE workouts SET sync_status='sent', sync_error=NULL, synced_at=? WHERE id=?", (now_iso(), workout_id))
    _log(conn, "success", "send_auto" if automatic else "send", f"{workout['title']} übertragen", workout_id)
    return store.get_workout(conn, workout_id)


def delete_remote(conn: sqlite3.Connection, workout: dict[str, Any]) -> None:
    """Löscht den extern übertragenen Datensatz – nur Taktspur-eigene, nur wenn er übertragen wurde."""
    if workout["read_only"]:
        raise IntegrationError("read_only", "Importierte oder absolvierte Einträge werden nie extern gelöscht.", 403)
    if workout["sync_status"] != "sent" and not workout["synced_at"]:
        return  # nie übertragen → extern nichts zu löschen
    athlete_id, key = _credentials(conn)
    ext = store.external_id(workout["id"])
    try:
        with client_factory(key) as client:
            response = client.put(f"/athlete/{athlete_id}/events/bulk-delete", json=[{"external_id": ext}])
            response.raise_for_status()
    except httpx.HTTPError as exc:
        err = translate_http(exc, context="delete")
        _log(conn, "error", "delete", f"{workout['title']}: {err.message}", workout["id"])
        raise err from None
    _log(conn, "success", "delete", f"{workout['title']} in Intervals.icu gelöscht", workout["id"])


def _mark(conn: sqlite3.Connection, workout_id: str, state: str, error: str | None) -> None:
    conn.execute("UPDATE workouts SET sync_status=?, sync_error=? WHERE id=?", (state, error, workout_id))


def logs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT at,level,action,message,workout_id FROM integration_log ORDER BY id DESC LIMIT 100")]
