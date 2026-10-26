"""FIT-Datei → strukturierte Daten. Nutzt nur die Datei selbst; GPS-Koordinaten und Profildaten
(Name, Gewicht, Geschlecht, Ruhepuls) werden bewusst NICHT übernommen (Datenschutz, für die Auswertung nicht nötig)."""
from __future__ import annotations

import io
import math
from datetime import datetime
from typing import Any

import fitdecode

MAX_BYTES = 30 * 1024 * 1024

# Bekannte Kanäle: Feld → (Schlüssel, Anzeigename, Einheit, Umrechnung)
KNOWN: dict[str, tuple[str, str, str, float]] = {
    "heart_rate": ("heart_rate", "Herzfrequenz", "bpm", 1.0),
    "power": ("power", "Leistung", "W", 1.0),
    "enhanced_speed": ("speed", "Geschwindigkeit", "m/s", 1.0),
    "enhanced_altitude": ("altitude", "Höhe", "m", 1.0),
    "temperature": ("temperature", "Temperatur", "°C", 1.0),
    "enhanced_respiration_rate": ("respiration", "Atemfrequenz", "1/min", 1.0),
    "vertical_oscillation": ("vertical_oscillation", "Vertikale Oszillation", "mm", 1.0),
    "vertical_ratio": ("vertical_ratio", "Vertikalverhältnis", "%", 1.0),
    "step_length": ("step_length", "Schrittlänge", "m", 0.001),
    "stance_time": ("stance_time", "Bodenkontaktzeit", "ms", 1.0),
    "distance": ("distance", "Distanz", "m", 1.0),
    "grade": ("grade", "Steigung", "%", 1.0),
    "left_right_balance": ("balance", "Links/Rechts-Balance", "", 1.0),
}
# Doppelte/abgeleitete Felder, die nicht zusätzlich als eigener Kanal erscheinen sollen
SKIP = {"timestamp", "position_lat", "position_long", "speed", "altitude", "cadence", "RunCadence", "fractional_cadence",
        "respiration_rate", "unknown"}


class FitError(Exception):
    pass


def _clean(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else round(value, 4)
    if isinstance(value, (int, str, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return str(value)


def _plain(frame: Any, drop: set[str] = frozenset()) -> dict[str, Any]:
    out = {}
    for f in frame.fields:
        if f.value is None or f.name.startswith("unknown") or f.name in drop:
            continue
        out[f.name] = _clean(f.value)
    return out


def parse(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_BYTES:
        raise FitError("Die Datei ist größer als 30 MB.")
    if len(data) < 14 or data[8:12] != b".FIT":
        raise FitError("Das ist keine FIT-Datei.")
    records: list[dict[str, Any]] = []
    laps: list[dict[str, Any]] = []
    session: dict[str, Any] = {}
    sport: dict[str, Any] = {}
    rr: list[float] = []
    try:
        with fitdecode.FitReader(io.BytesIO(data)) as reader:
            for frame in reader:
                if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                    continue
                name = frame.name
                if name == "record":
                    rec = {f.name: f.value for f in frame.fields if f.value is not None}
                    if "timestamp" in rec:
                        records.append(rec)
                elif name == "lap":
                    laps.append(_plain(frame))
                elif name == "session" and not session:
                    session = _plain(frame, drop={"message_index"})
                elif name == "sport" and not sport:
                    sport = _plain(frame)
                elif name == "hrv":
                    vals = frame.get_value("time", fallback=None)
                    if vals is None:
                        continue
                    for v in (vals if isinstance(vals, (list, tuple)) else [vals]):
                        if v is not None and 0 < v < 10:
                            rr.append(float(v) * 1000.0)
    except Exception as exc:                                    # fitdecode wirft verschiedene Fehlertypen bei defekten Dateien
        raise FitError("Die FIT-Datei ist beschädigt oder wird nicht unterstützt.") from None
    if not records:
        raise FitError("Die FIT-Datei enthält keine Aufzeichnungspunkte (Records).")

    records.sort(key=lambda r: r["timestamp"])
    t0 = records[0]["timestamp"]
    t = [round((r["timestamp"] - t0).total_seconds(), 1) for r in records]
    sport_name = str(session.get("sport") or sport.get("sport") or "")
    channels: dict[str, dict[str, Any]] = {}

    def add(key: str, label: str, unit: str, values: list[float | None]) -> None:
        if any(v is not None for v in values):
            channels[key] = {"key": key, "label": label, "unit": unit, "values": values}

    def column(field: str, factor: float = 1.0) -> list[float | None]:
        col: list[float | None] = []
        for r in records:
            v = r.get(field)
            col.append(round(float(v) * factor, 4) if isinstance(v, (int, float)) and not isinstance(v, bool) and not math.isnan(float(v)) else None)
        return col

    for field, (key, label, unit, factor) in KNOWN.items():
        add(key, label, unit, column(field, factor))
    if "speed" not in channels:
        add("speed", "Geschwindigkeit", "m/s", column("speed"))
    if "altitude" not in channels:
        add("altitude", "Höhe", "m", column("altitude"))
    # Kadenz: Laufen = Schritte/min (FIT „cadence“ zählt Doppelschritte), Rad = U/min
    if sport_name == "running":
        steps = column("RunCadence")
        if not any(v for v in steps):
            steps = [None if v is None else v * 2 for v in column("cadence")]
        add("cadence", "Schrittfrequenz", "spm", steps)
    else:
        add("cadence", "Trittfrequenz", "rpm", column("cadence"))
    # weitere numerische Felder, die wir nicht kennen: nicht verlieren
    used = {f for f in KNOWN} | SKIP
    for field in sorted({k for r in records for k in r} - used):
        col = column(field)
        if sum(v is not None for v in col) >= max(3, len(col) // 10):
            add(f"x_{field}", field, "", col)

    start = records[0]["timestamp"]
    return {
        "start_time": start.isoformat() if isinstance(start, datetime) else None,
        "sport": sport_name, "sub_sport": str(session.get("sub_sport") or sport.get("sub_sport") or ""),
        "session": session, "laps": laps, "t": t, "channels": channels, "rr_ms": rr,
    }
