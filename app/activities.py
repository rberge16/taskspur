"""Importierte Aktivitäten (FIT): Speicherung, Abfrage, Auswertung (Tabellen, HRV/DFA a1, CSV)."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sqlite3
import uuid
import zlib
from typing import Any

import numpy as np

from . import fit_import, hrv
from .db import now_iso
from .downsample import bucket_mean
from .store import NotFound, Rejected

PACE_CAP_S_PER_KM = 12 * 60          # langsamer als 12 min/km gilt als Stehen/Gehen → keine Pace


def _pack(obj: Any) -> bytes:
    return zlib.compress(json.dumps(obj, separators=(",", ":")).encode(), 6)


def _unpack(blob: bytes | None) -> Any:
    return json.loads(zlib.decompress(blob).decode()) if blob else None


def _row(conn: sqlite3.Connection, activity_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM activities WHERE id=?", (activity_id,)).fetchone()
    if not row:
        raise NotFound("Aktivität nicht gefunden.")
    return row


def _summary(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "name": row["name"], "sport": row["sport"], "sub_sport": row["sub_sport"], "start_time": row["start_time"],
            "duration_s": row["duration_s"], "distance_m": row["distance_m"], "avg_hr": row["avg_hr"], "avg_power": row["avg_power"],
            "has_rr": bool(row["has_rr"]), "source": row["source"], "external_id": row["external_id"], "has_data": row["channels_json"] != "[]"}


EXTERNAL_FROM_NAME = re.compile(r"^(i\d{3,})(?:[_\-. ]|$)")      # Intervals.icu-Export: „i201565978_Dresden_Laufen.fit“


def import_fit(conn: sqlite3.Connection, data: bytes, filename: str, *, source: str = "import", external_id: str | None = None) -> dict[str, Any]:
    digest = hashlib.sha256(data).hexdigest()
    base = (filename or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if external_id is None and (m := EXTERNAL_FROM_NAME.match(base)):
        external_id = m.group(1)          # Dateiname verrät die Intervals.icu-ID → späterer Sync legt keine Dublette an
    existing = conn.execute("SELECT id, external_id FROM activities WHERE sha256=?", (digest,)).fetchone()
    if existing:
        if external_id and not existing["external_id"] and not conn.execute("SELECT 1 FROM activities WHERE external_id=?", (external_id,)).fetchone():
            conn.execute("UPDATE activities SET external_id=? WHERE id=?", (external_id, existing["id"]))
        raise Rejected("Diese Aktivität ist bereits importiert.", 409)
    if external_id and conn.execute("SELECT 1 FROM activities WHERE external_id=?", (external_id,)).fetchone():
        raise Rejected("Diese Aktivität ist bereits importiert.", 409)
    try:
        parsed = fit_import.parse(data)
    except fit_import.FitError as exc:
        raise Rejected(str(exc)) from None
    session = parsed["session"]
    t = parsed["t"]
    hr = parsed["channels"].get("heart_rate", {}).get("values", [])
    hr_vals = [v for v in hr if v is not None]
    analysis = hrv.analyse(parsed["rr_ms"]) if parsed["rr_ms"] else {"available": False, "reason": "Die Datei enthält keine RR-Intervalle (HRV). DFA a1 ist nur mit Schlag-zu-Schlag-Daten möglich."}
    name = (filename or "Aktivität").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    name = (name[:-4] if name.lower().endswith(".fit") else name).strip()[:120] or "Aktivität"
    activity_id = str(uuid.uuid4())
    channels_meta = [{"key": c["key"], "label": c["label"], "unit": c["unit"]} for c in parsed["channels"].values()]
    conn.execute(
        """INSERT INTO activities (id,sha256,name,sport,sub_sport,start_time,duration_s,distance_m,avg_hr,avg_power,has_rr,
                                   session_json,laps_json,channels_json,data_blob,hrv_blob,created_at,source,external_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (activity_id, digest, name, parsed["sport"], parsed["sub_sport"], parsed["start_time"],
         float(session.get("total_timer_time") or session.get("total_elapsed_time") or (t[-1] if t else 0)), float(session.get("total_distance") or 0),
         session.get("avg_heart_rate") or (sum(hr_vals) / len(hr_vals) if hr_vals else None), session.get("avg_power"),
         1 if analysis.get("available") else 0, json.dumps(session), json.dumps(parsed["laps"]), json.dumps(channels_meta),
         _pack({"t": t, "channels": {k: c["values"] for k, c in parsed["channels"].items()}}), _pack(analysis), now_iso(), source, external_id),
    )
    return _summary(_row(conn, activity_id))


SPORT_FROM_TYPE = {"Run": "running", "TrailRun": "running", "VirtualRun": "running", "Ride": "cycling", "VirtualRide": "cycling", "GravelRide": "cycling",
                   "MountainBikeRide": "cycling", "Swim": "swimming", "OpenWaterSwim": "swimming", "Walk": "walking", "Hike": "hiking", "WeightTraining": "training"}


def import_summary(conn: sqlite3.Connection, item: dict[str, Any]) -> dict[str, Any]:
    """Aktivität ohne abrufbare Datei (z. B. manuell eingetragen oder von Strava): nur die Kennzahlen aus Intervals.icu."""
    ext = str(item.get("id") or "")
    if not ext:
        raise Rejected("Die Aktivität hat keine Kennung.")
    num = lambda *keys: next((float(item[k]) for k in keys if isinstance(item.get(k), (int, float)) and not isinstance(item.get(k), bool)), None)
    sport = SPORT_FROM_TYPE.get(str(item.get("type") or ""), str(item.get("type") or "").lower())
    session = {k: v for k, v in {
        "sport": sport, "total_timer_time": num("moving_time", "elapsed_time"), "total_elapsed_time": num("elapsed_time"), "total_distance": num("distance"),
        "avg_heart_rate": num("average_heartrate"), "max_heart_rate": num("max_heartrate"), "avg_power": num("icu_average_watts", "average_watts"),
        "normalized_power": num("icu_weighted_avg_watts"), "training_stress_score": num("icu_training_load"), "total_ascent": num("total_elevation_gain"),
        "enhanced_avg_speed": num("average_speed"),
    }.items() if v is not None}
    start = str(item.get("start_date") or item.get("start_date_local") or "")
    name = str(item.get("name") or sport or "Aktivität").strip()[:120] or "Aktivität"
    activity_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO activities (id,sha256,name,sport,sub_sport,start_time,duration_s,distance_m,avg_hr,avg_power,has_rr,
                                   session_json,laps_json,channels_json,data_blob,hrv_blob,created_at,source,external_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,?,?,?)""",
        (activity_id, f"intervals:{ext}", name, sport, "", start or None, session.get("total_timer_time", 0), session.get("total_distance", 0),
         session.get("avg_heart_rate"), session.get("avg_power"), json.dumps(session), "[]", "[]", _pack({"t": [], "channels": {}}),
         _pack({"available": False, "reason": "Für diese Aktivität liegen keine Messdaten vor (keine Datei bei Intervals.icu abrufbar)."}),
         now_iso(), "intervals", ext),
    )
    return _summary(_row(conn, activity_id))


def list_activities(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [_summary(r) for r in conn.execute("SELECT * FROM activities ORDER BY start_time DESC, created_at DESC")]


def delete_activity(conn: sqlite3.Connection, activity_id: str) -> None:
    row = _row(conn, activity_id)
    conn.execute("BEGIN")
    try:
        if row["external_id"]:        # lokal gelöscht → der Sync holt sie nicht erneut
            conn.execute("INSERT OR IGNORE INTO activity_ignored(external_id, ignored_at) VALUES(?,?)", (row["external_id"], now_iso()))
        conn.execute("DELETE FROM activities WHERE id=?", (activity_id,))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def rename_activity(conn: sqlite3.Connection, activity_id: str, name: str) -> dict[str, Any]:
    name = name.strip()
    if not name or len(name) > 120:
        raise Rejected("Der Name muss 1 bis 120 Zeichen lang sein.")
    _row(conn, activity_id)
    conn.execute("UPDATE activities SET name=? WHERE id=?", (name, activity_id))
    return _summary(_row(conn, activity_id))


def _data(row: sqlite3.Row) -> dict[str, Any]:
    return _unpack(row["data_blob"])


def detail(conn: sqlite3.Connection, activity_id: str, max_points: int = 6000) -> dict[str, Any]:
    row = _row(conn, activity_id)
    data = _data(row)
    if not data["t"]:
        return {**_summary(row), "session": json.loads(row["session_json"]), "laps": json.loads(row["laps_json"]), "channels": [], "t": [], "data": {}, "resolution_s": 0}
    t, cols = bucket_mean(data["t"], data["channels"], max_points)
    return {**_summary(row), "session": json.loads(row["session_json"]), "laps": json.loads(row["laps_json"]), "lap_bounds": _bounds_json(row),
            "channels": json.loads(row["channels_json"]), "t": t, "data": cols, "resolution_s": round((data["t"][-1] - data["t"][0]) / max(1, len(t) - 1), 2) if len(t) > 1 else 0}


def hrv_detail(conn: sqlite3.Connection, activity_id: str) -> dict[str, Any]:
    row = _row(conn, activity_id)
    analysis = _unpack(row["hrv_blob"]) or {"available": False, "reason": "Keine HRV-Daten."}
    if not analysis.get("available"):
        return analysis
    data = _data(row)
    hr = data["channels"].get("heart_rate")
    arr_t = np.asarray(data["t"], dtype=float)
    arr_hr = np.asarray([np.nan if v is None else v for v in hr], dtype=float) if hr else None

    def hr_window(t_end: float) -> float | None:
        if arr_hr is None:
            return None
        m = (arr_t > t_end - hrv.WINDOW_S) & (arr_t <= t_end) & ~np.isnan(arr_hr)
        return float(arr_hr[m].mean()) if m.sum() >= 30 else None

    analysis = dict(analysis)
    analysis["thresholds"] = hrv.threshold_estimate(analysis["alpha1"]["t"], analysis["alpha1"]["value"], hr_window)
    analysis["reference"] = {"HRVT1": hrv.THRESHOLDS["HRVT1"], "HRVT2": hrv.THRESHOLDS["HRVT2"]}
    # α1 und Herzfrequenz je Fenster (für die Streudiagramm-/Tabellenansicht)
    analysis["alpha1"]["hr"] = [None if (h := hr_window(x)) is None else round(h, 1) for x in analysis["alpha1"]["t"]]
    analysis["laps"] = lap_alpha1(row, analysis["alpha1"])
    return analysis


def _lap_bounds(row: sqlite3.Row) -> list[tuple[float, float]]:
    """Runden als (Start, Ende) in Sekunden ab Aufzeichnungsbeginn (gleiche Achse wie die Diagramme)."""
    from datetime import datetime

    def parse(value: Any) -> datetime | None:
        try:
            dt = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
        return dt.replace(tzinfo=None) if dt.tzinfo else dt

    t0 = parse(row["start_time"])
    bounds: list[tuple[float, float]] = []
    running = 0.0   # Ersatz, falls eine Runde keine Startzeit hat: Summe der vorherigen Rundendauern
    for lap in json.loads(row["laps_json"]):
        start = parse(lap.get("start_time"))
        length = lap.get("total_elapsed_time") or lap.get("total_timer_time")
        if not length:
            bounds.append((float("nan"), float("nan")))
            continue
        offset = (start - t0).total_seconds() if (t0 is not None and start is not None) else running
        bounds.append((offset, offset + float(length)))
        running = offset + float(length)
    return bounds


def _bounds_json(row: sqlite3.Row) -> list[dict[str, Any]]:
    return [{"from_s": None if a != a else round(a, 1), "to_s": None if b != b else round(b, 1)} for a, b in _lap_bounds(row)]


def lap_alpha1(row: sqlite3.Row, alpha1: dict[str, Any]) -> list[dict[str, Any]]:
    """DFA a1 je Runde: Mittel der gültigen 120-s-Fenster, deren Mitte in der Runde liegt.
    Runden kürzer als ein Fenster können leer bleiben – dann steht dort ‚–‘ statt eines erfundenen Werts."""
    centers = [t - hrv.WINDOW_S / 2 for t in alpha1["t"]]
    out = []
    for index, (start, end) in enumerate(_lap_bounds(row)):
        values = [v for c, v in zip(centers, alpha1["value"]) if v is not None and start <= c < end] if start == start else []
        out.append({"index": index, "from_s": None if start != start else round(start, 1), "to_s": None if end != end else round(end, 1),
                    "alpha1_mean": round(float(np.mean(values)), 2) if values else None, "windows": len(values)})
    return out


def table(conn: sqlite3.Connection, activity_id: str, bucket_s: int = 60) -> dict[str, Any]:
    """Werte je Zeitabschnitt (Standard: pro Minute) als Tabelle; Pace wird aus der mittleren Geschwindigkeit berechnet."""
    if not 10 <= bucket_s <= 900:
        raise Rejected("Der Zeitabschnitt muss zwischen 10 und 900 Sekunden liegen.")
    row = _row(conn, activity_id)
    data = _data(row)
    if not data["t"]:
        return {"bucket_s": bucket_s, "columns": [], "rows": []}
    t = np.asarray(data["t"], dtype=float)
    meta = {c["key"]: c for c in json.loads(row["channels_json"])}
    idx = (t // bucket_s).astype(int)
    rows = []
    for b in range(int(idx.max()) + 1 if len(idx) else 0):
        m = idx == b
        if not m.any():
            continue
        entry: dict[str, Any] = {"from_s": b * bucket_s, "to_s": min(b * bucket_s + bucket_s, float(t[-1]))}
        for key, values in data["channels"].items():
            v = np.asarray([np.nan if x is None else x for x in values], dtype=float)[m]
            v = v[~np.isnan(v)]
            if not len(v):
                entry[key] = None
            elif key == "distance":
                entry[key] = round(float(v[-1]), 1)          # kumulativ: Wert am Ende
            else:
                entry[key] = round(float(v.mean()), 2)
        sp = entry.get("speed")
        entry["pace_s_per_km"] = round(1000.0 / sp) if sp and sp > 0 and 1000.0 / sp <= PACE_CAP_S_PER_KM else None
        rows.append(entry)
    cols = [{"key": "pace_s_per_km", "label": "Pace", "unit": "min/km"}] + [{"key": k, "label": c["label"], "unit": c["unit"]} for k, c in meta.items()]
    alpha = (_unpack(row["hrv_blob"]) or {}).get("alpha1")
    if alpha:
        at, av = np.asarray(alpha["t"], dtype=float), alpha["value"]
        for r in rows:
            vals = [a for x, a in zip(at, av) if a is not None and r["from_s"] < x <= r["to_s"] + 1e-6]
            r["alpha1"] = round(float(np.mean(vals)), 2) if vals else None
        cols.append({"key": "alpha1", "label": "DFA a1", "unit": ""})
    return {"bucket_s": bucket_s, "columns": cols, "rows": rows}


def csv_export(conn: sqlite3.Connection, activity_id: str) -> tuple[str, str]:
    row = _row(conn, activity_id)
    data = _data(row)
    meta = json.loads(row["channels_json"])
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["time_s"] + [f"{c['label']} ({c['unit']})" if c["unit"] else c["label"] for c in meta])
    for i, ts in enumerate(data["t"]):
        w.writerow([ts] + ["" if data["channels"][c["key"]][i] is None else data["channels"][c["key"]][i] for c in meta])
    safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in row["name"]).strip() or "aktivitaet"
    return out.getvalue(), f"{safe}.csv"
