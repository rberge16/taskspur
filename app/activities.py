"""Importierte Aktivitäten (FIT): Speicherung, Abfrage, Auswertung (Tabellen, HRV/DFA a1, CSV)."""
from __future__ import annotations

import csv
import hashlib
import io
import json
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
            "has_rr": bool(row["has_rr"])}


def import_fit(conn: sqlite3.Connection, data: bytes, filename: str) -> dict[str, Any]:
    digest = hashlib.sha256(data).hexdigest()
    existing = conn.execute("SELECT id FROM activities WHERE sha256=?", (digest,)).fetchone()
    if existing:
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
                                   session_json,laps_json,channels_json,data_blob,hrv_blob,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (activity_id, digest, name, parsed["sport"], parsed["sub_sport"], parsed["start_time"],
         float(session.get("total_timer_time") or session.get("total_elapsed_time") or (t[-1] if t else 0)), float(session.get("total_distance") or 0),
         session.get("avg_heart_rate") or (sum(hr_vals) / len(hr_vals) if hr_vals else None), session.get("avg_power"),
         1 if analysis.get("available") else 0, json.dumps(session), json.dumps(parsed["laps"]), json.dumps(channels_meta),
         _pack({"t": t, "channels": {k: c["values"] for k, c in parsed["channels"].items()}}), _pack(analysis), now_iso()),
    )
    return _summary(_row(conn, activity_id))


def list_activities(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [_summary(r) for r in conn.execute("SELECT * FROM activities ORDER BY start_time DESC, created_at DESC")]


def delete_activity(conn: sqlite3.Connection, activity_id: str) -> None:
    _row(conn, activity_id)
    conn.execute("DELETE FROM activities WHERE id=?", (activity_id,))


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
    t, cols = bucket_mean(data["t"], data["channels"], max_points)
    return {**_summary(row), "session": json.loads(row["session_json"]), "laps": json.loads(row["laps_json"]),
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
    return analysis


def table(conn: sqlite3.Connection, activity_id: str, bucket_s: int = 60) -> dict[str, Any]:
    """Werte je Zeitabschnitt (Standard: pro Minute) als Tabelle; Pace wird aus der mittleren Geschwindigkeit berechnet."""
    if not 10 <= bucket_s <= 900:
        raise Rejected("Der Zeitabschnitt muss zwischen 10 und 900 Sekunden liegen.")
    row = _row(conn, activity_id)
    data = _data(row)
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
