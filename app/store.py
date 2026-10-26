"""Datenzugriff und Geschäftsregeln für Pläne, Phasen, Workouts und Koppeleinheiten."""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from . import logic
from .db import now_iso
from .schemas import BrickIn, PhaseIn, PlanIn, WorkoutIn


class NotFound(Exception):
    pass


class Rejected(Exception):
    """Fachliche Ablehnung mit verständlicher Meldung (wird zu HTTP 4xx)."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message = message
        self.status = status


# ---------- Einstellungen ----------

def get_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}
    return {
        "intervals_auto_send": rows.get("intervals_auto_send") == "true",  # nur ausdrücklich aktiviert
        "ftp": int(rows["ftp"]) if rows.get("ftp") else None,
        "lthr": int(rows["lthr"]) if rows.get("lthr") else None,
        "intervals_history_days": int(rows["intervals_history_days"]) if rows.get("intervals_history_days") else 30,
        "intervals_sync_on_start": rows.get("intervals_sync_on_start") != "false",   # Standard: an
    }


def set_settings(conn: sqlite3.Connection, values: dict[str, Any]) -> dict[str, Any]:
    for key, value in values.items():
        if value is None:
            continue
        stored = ("true" if value else "false") if isinstance(value, bool) else str(value)
        conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, stored))
    return get_settings(conn)


# ---------- Workouts ----------

def _row_to_workout(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "plan_id": row["plan_id"],
        "phase_id": row["phase_id"],
        "date": row["date"],
        "start_time": row["start_time"],
        "sport": row["sport"],
        "title": row["title"],
        "description": row["description"],
        "kind": row["kind"],
        "duration_min": row["duration_min"],
        "tss": row["tss"],
        "steps": json.loads(row["steps_json"]),
        "link_group": row["link_group"],
        "link_order": row["link_order"],
        "origin": row["origin"],
        "read_only": row["origin"] != "taktspur",
        "ext_id": row["ext_id"],
        "sync_status": row["sync_status"],
        "sync_error": row["sync_error"],
        "synced_at": row["synced_at"],
    }


def get_workout(conn: sqlite3.Connection, workout_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM workouts WHERE id=?", (workout_id,)).fetchone()
    if row is None:
        raise NotFound("Einheit nicht gefunden.")
    return _row_to_workout(row)


def list_workouts(conn: sqlite3.Connection, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
    sql, args = "SELECT * FROM workouts", []
    if start and end:
        sql += " WHERE (date BETWEEN ? AND ?) OR date IS NULL"
        args = [start, end]
    sql += " ORDER BY COALESCE(date,'9999-12-31'), COALESCE(start_time,''), COALESCE(link_order,0), created_at"
    return [_row_to_workout(r) for r in conn.execute(sql, args)]


def partner_of(conn: sqlite3.Connection, workout: dict[str, Any]) -> dict[str, Any] | None:
    if not workout["link_group"]:
        return None
    row = conn.execute("SELECT * FROM workouts WHERE link_group=? AND id<>?", (workout["link_group"], workout["id"])).fetchone()
    return _row_to_workout(row) if row else None


def _check_assignment(conn: sqlite3.Connection, data: WorkoutIn) -> None:
    if data.plan_id and not data.phase_id:
        raise Rejected("Bitte eine Phase des Trainingsplans auswählen.")
    if data.phase_id:
        phase = conn.execute("SELECT * FROM phases WHERE id=?", (data.phase_id,)).fetchone()
        if phase is None or phase["plan_id"] != data.plan_id:
            raise Rejected("Die gewählte Phase gehört nicht zum gewählten Plan.")
        if not data.date:
            raise Rejected("Für eine Planeinheit wird ein Datum benötigt.")
        if not (phase["start_date"] <= data.date <= phase["end_date"]):
            raise Rejected("Das Datum liegt außerhalb der gewählten Phase.")


def _computed(conn: sqlite3.Connection, data: WorkoutIn) -> tuple[int, int, str]:
    settings = get_settings(conn)
    steps = [s.model_dump() for s in data.steps]
    if steps:
        minutes, tss = logic.structure_totals(steps, data.sport, settings["ftp"], settings["lthr"])
    else:
        minutes, tss = (data.duration_min or 0), 0
    return minutes, tss, json.dumps(steps, ensure_ascii=False)


def _insert(conn: sqlite3.Connection, data: WorkoutIn, *, link_group=None, link_order=None, date=None, start_time=None, plan_id=None, phase_id=None) -> str:
    minutes, tss, steps_json = _computed(conn, data)
    workout_id = str(uuid.uuid4())
    stamp = now_iso()
    conn.execute(
        """INSERT INTO workouts(id,plan_id,phase_id,date,start_time,sport,title,description,kind,duration_min,tss,steps_json,
                                link_group,link_order,origin,ext_id,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'taktspur',?,?,?)""",
        (workout_id, plan_id, phase_id, date, start_time, data.sport, data.title, data.description, data.kind, minutes, tss, steps_json,
         link_group, link_order, external_id(workout_id), stamp, stamp),
    )
    return workout_id


def external_id(workout_id: str) -> str:
    """Stabile externe ID: hängt nur an der Taktspur-ID und ändert sich nie."""
    return f"taktspur-workout-{workout_id}"


def create_workout(conn: sqlite3.Connection, data: WorkoutIn) -> dict[str, Any]:
    _check_assignment(conn, data)
    conn.execute("BEGIN")
    try:
        workout_id = _insert(conn, data, date=data.date, start_time=data.start_time, plan_id=data.plan_id, phase_id=data.phase_id)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return get_workout(conn, workout_id)


def create_brick(conn: sqlite3.Connection, data: BrickIn) -> list[dict[str, Any]]:
    first, second = data.part1, data.part2
    _check_assignment(conn, first)
    if not first.date:
        raise Rejected("Für eine Koppeleinheit wird ein Datum benötigt.")
    group = f"brick-{uuid.uuid4()}"
    conn.execute("BEGIN")
    try:
        id1 = _insert(conn, first, link_group=group, link_order=1, date=first.date, start_time=first.start_time, plan_id=first.plan_id, phase_id=first.phase_id)
        w1 = _row_to_workout(conn.execute("SELECT * FROM workouts WHERE id=?", (id1,)).fetchone())
        id2 = _insert(conn, second, link_group=group, link_order=2, date=first.date,
                      start_time=logic.add_minutes(first.start_time, w1["duration_min"]), plan_id=first.plan_id, phase_id=first.phase_id)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return [get_workout(conn, id1), get_workout(conn, id2)]


def _follow_up(conn: sqlite3.Connection, group: str) -> None:
    """Teil 2 beginnt immer direkt nach Teil 1 (gleiches Datum, gleiche Zuordnung)."""
    rows = {r["link_order"]: r for r in conn.execute("SELECT * FROM workouts WHERE link_group=?", (group,))}
    if 1 in rows and 2 in rows:
        first = rows[1]
        conn.execute(
            "UPDATE workouts SET date=?, start_time=?, plan_id=?, phase_id=?, updated_at=? WHERE id=?",
            (first["date"], logic.add_minutes(first["start_time"], first["duration_min"]), first["plan_id"], first["phase_id"], now_iso(), rows[2]["id"]),
        )


def update_workout(conn: sqlite3.Connection, workout_id: str, data: WorkoutIn) -> dict[str, Any]:
    current = get_workout(conn, workout_id)
    if current["read_only"]:
        raise Rejected("Aus Intervals.icu importierte oder absolvierte Einheiten sind schreibgeschützt.", 403)
    if current["link_order"] == 2:
        # Teil 2 folgt Teil 1: Datum, Zeit und Plan-Zuordnung kommen von Teil 1.
        first = partner_of(conn, current)
        data = data.model_copy(update={"date": first["date"], "start_time": logic.add_minutes(first["start_time"], first["duration_min"]),
                                       "plan_id": first["plan_id"], "phase_id": first["phase_id"]})
    _check_assignment(conn, data)
    minutes, tss, steps_json = _computed(conn, data)
    conn.execute("BEGIN")
    try:
        conn.execute(
            """UPDATE workouts SET plan_id=?,phase_id=?,date=?,start_time=?,sport=?,title=?,description=?,kind=?,duration_min=?,tss=?,
                                   steps_json=?,sync_status=CASE WHEN sync_status='sent' THEN 'none' ELSE sync_status END,updated_at=? WHERE id=?""",
            (data.plan_id, data.phase_id, data.date, data.start_time, data.sport, data.title, data.description, data.kind, minutes, tss, steps_json, now_iso(), workout_id),
        )
        if current["link_group"] and current["link_order"] == 1:
            _follow_up(conn, current["link_group"])
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return get_workout(conn, workout_id)


def unlink(conn: sqlite3.Connection, workout_id: str) -> list[dict[str, Any]]:
    current = get_workout(conn, workout_id)
    if not current["link_group"]:
        raise Rejected("Diese Einheit ist nicht mit einer anderen verknüpft.")
    group = current["link_group"]
    ids = [r["id"] for r in conn.execute("SELECT id FROM workouts WHERE link_group=?", (group,))]
    conn.execute("UPDATE workouts SET link_group=NULL, link_order=NULL, updated_at=? WHERE link_group=?", (now_iso(), group))
    return [get_workout(conn, i) for i in ids]


def link(conn: sqlite3.Connection, first_id: str, second_id: str) -> list[dict[str, Any]]:
    """Verbindet zwei vorhandene Einzeleinheiten zu einer Koppeleinheit (first = Teil 1, second = Teil 2).
    Teil 2 übernimmt Datum, Startzeit (direkt nach Teil 1) und Plan-Zuordnung von Teil 1."""
    if first_id == second_id:
        raise Rejected("Eine Einheit kann nicht mit sich selbst gekoppelt werden.")
    first, second = get_workout(conn, first_id), get_workout(conn, second_id)
    for w in (first, second):
        if w["read_only"]:
            raise Rejected("Aus Intervals.icu importierte oder absolvierte Einheiten sind schreibgeschützt.", 403)
        if w["link_group"]:
            raise Rejected(f"„{w['title']}“ ist bereits Teil einer Koppeleinheit. Bitte zuerst die Verknüpfung lösen.")
    if not first["date"]:
        raise Rejected("Teil 1 braucht ein Datum, damit Teil 2 direkt danach beginnen kann.")
    group = f"brick-{uuid.uuid4()}"
    conn.execute("BEGIN")
    try:
        stamp = now_iso()
        conn.execute("UPDATE workouts SET link_group=?, link_order=1, updated_at=? WHERE id=?", (group, stamp, first_id))
        # Teil 2 ändert Zeit/Datum: eine bereits übertragene Fassung in Intervals.icu ist damit veraltet.
        conn.execute("UPDATE workouts SET link_group=?, link_order=2, updated_at=?, "
                     "sync_status=CASE WHEN sync_status='sent' THEN 'none' ELSE sync_status END WHERE id=?", (group, stamp, second_id))
        _follow_up(conn, group)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return [get_workout(conn, first_id), get_workout(conn, second_id)]


def delete_workout(conn: sqlite3.Connection, workout_id: str, *, cascade: bool = False) -> list[dict[str, Any]]:
    """Löscht lokal. Ohne cascade wird der Koppel-Partner entkoppelt (keine verwaiste Teil-2-Einheit).
    Gibt die gelöschten Datensätze zurück (für das Löschen in Intervals.icu)."""
    current = get_workout(conn, workout_id)
    if current["read_only"]:
        raise Rejected("Aus Intervals.icu importierte oder absolvierte Einheiten sind schreibgeschützt.", 403)
    partner = partner_of(conn, current)
    deleted = [current]
    conn.execute("BEGIN")
    try:
        if partner and cascade:
            deleted.append(partner)
            conn.execute("DELETE FROM workouts WHERE id=?", (partner["id"],))
        elif partner:
            conn.execute("UPDATE workouts SET link_group=NULL, link_order=NULL, updated_at=? WHERE id=?", (now_iso(), partner["id"]))
        conn.execute("DELETE FROM workouts WHERE id=?", (workout_id,))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return deleted


# ---------- Pläne / Phasen ----------

def _plan_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    phases = conn.execute("SELECT * FROM phases WHERE plan_id=? ORDER BY position, start_date", (row["id"],)).fetchall()
    return {
        "id": row["id"], "name": row["name"], "goal_date": row["goal_date"], "status": row["status"], "color": row["color"],
        "phases": [{"id": p["id"], "name": p["name"], "start_date": p["start_date"], "end_date": p["end_date"], "description": p["description"]} for p in phases],
    }


def list_plans(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [_plan_dict(conn, r) for r in conn.execute("SELECT * FROM plans ORDER BY created_at")]


def create_plan(conn: sqlite3.Connection, data: PlanIn) -> dict[str, Any]:
    if data.status == "active" and conn.execute("SELECT COUNT(*) FROM plans WHERE status='active'").fetchone()[0] >= 3:
        raise Rejected("Es können höchstens 3 Pläne gleichzeitig aktiv sein.")
    plan_id, stamp = str(uuid.uuid4()), now_iso()
    conn.execute("INSERT INTO plans(id,name,goal_date,status,color,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                 (plan_id, data.name.strip(), data.goal_date, data.status, data.color, stamp, stamp))
    return _plan_dict(conn, conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone())


def update_plan(conn: sqlite3.Connection, plan_id: str, data: PlanIn) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
    if row is None:
        raise NotFound("Plan nicht gefunden.")
    if data.status == "active" and row["status"] != "active" and conn.execute("SELECT COUNT(*) FROM plans WHERE status='active'").fetchone()[0] >= 3:
        raise Rejected("Es können höchstens 3 Pläne gleichzeitig aktiv sein.")
    conn.execute("UPDATE plans SET name=?,goal_date=?,status=?,color=?,updated_at=? WHERE id=?",
                 (data.name.strip(), data.goal_date, data.status, data.color, now_iso(), plan_id))
    return _plan_dict(conn, conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone())


def delete_plan(conn: sqlite3.Connection, plan_id: str) -> None:
    """Löscht Plan und Phasen. Einheiten bleiben als freie Einheiten erhalten (nichts geht verloren)."""
    if conn.execute("SELECT 1 FROM plans WHERE id=?", (plan_id,)).fetchone() is None:
        raise NotFound("Plan nicht gefunden.")
    conn.execute("DELETE FROM plans WHERE id=?", (plan_id,))


def add_phase(conn: sqlite3.Connection, plan_id: str, data: PhaseIn) -> dict[str, Any]:
    if conn.execute("SELECT 1 FROM plans WHERE id=?", (plan_id,)).fetchone() is None:
        raise NotFound("Plan nicht gefunden.")
    if data.end_date < data.start_date:
        raise Rejected("Das Ende der Phase liegt vor dem Anfang.")
    position = conn.execute("SELECT COALESCE(MAX(position),-1)+1 FROM phases WHERE plan_id=?", (plan_id,)).fetchone()[0]
    conn.execute("INSERT INTO phases(id,plan_id,name,start_date,end_date,description,position) VALUES(?,?,?,?,?,?,?)",
                 (str(uuid.uuid4()), plan_id, data.name.strip(), data.start_date, data.end_date, data.description.strip(), position))
    return _plan_dict(conn, conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone())


def update_phase(conn: sqlite3.Connection, phase_id: str, data: PhaseIn) -> dict[str, Any]:
    phase = conn.execute("SELECT * FROM phases WHERE id=?", (phase_id,)).fetchone()
    if phase is None:
        raise NotFound("Phase nicht gefunden.")
    if data.end_date < data.start_date:
        raise Rejected("Das Ende der Phase liegt vor dem Anfang.")
    outside = conn.execute("SELECT COUNT(*) FROM workouts WHERE phase_id=? AND (date<? OR date>?)", (phase_id, data.start_date, data.end_date)).fetchone()[0]
    if outside:
        raise Rejected(f"{outside} Einheit(en) lägen außerhalb der neuen Phase. Bitte erst verschieben, damit nichts aus dem Kalender verschwindet.")
    conn.execute("UPDATE phases SET name=?,start_date=?,end_date=?,description=? WHERE id=?",
                 (data.name.strip(), data.start_date, data.end_date, data.description.strip(), phase_id))
    return _plan_dict(conn, conn.execute("SELECT * FROM plans WHERE id=?", (phase["plan_id"],)).fetchone())


def delete_phase(conn: sqlite3.Connection, phase_id: str) -> None:
    if conn.execute("SELECT 1 FROM phases WHERE id=?", (phase_id,)).fetchone() is None:
        raise NotFound("Phase nicht gefunden.")
    conn.execute("DELETE FROM phases WHERE id=?", (phase_id,))
