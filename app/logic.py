"""Reine Fachlogik ohne Datenbank: Dauer, TSS, Zeitberechnung."""
from __future__ import annotations

# Intensitätsfaktor je Zone (grobe, dokumentierte Schätzung – ersetzt keine Messung).
ZONE_IF = {"Z1": 0.55, "Z2": 0.70, "Z3": 0.85, "Z4": 0.95, "Z5": 1.05, "Z6": 1.15, "Z7": 1.30}
DEFAULT_IF = 0.65  # offener Abschnitt ohne Ziel
KM_MIN_PER_KM = {"Radfahren": 2.4, "Laufen": 5.5, "Schwimmen": 18.0}  # Minuten je km, nur Schätzwert


def block_minutes(duration: dict, sport: str) -> float:
    value = float(duration["value"])
    unit = duration.get("unit", "min")
    if unit == "sec":
        return value / 60.0
    if unit == "km":
        return value * KM_MIN_PER_KM.get(sport, 5.0)
    return value


def intensity(target: dict, ftp: int | None, lthr: int | None) -> float:
    ttype = target.get("type", "open")
    low, high = target.get("min"), target.get("max")
    reference = ftp if ttype == "power" else lthr if ttype == "heart_rate" else None
    if ttype != "open" and low and high and reference:
        return max(0.3, min(1.5, ((low + high) / 2) / reference))
    zone = target.get("zone")
    if zone in ZONE_IF:
        return ZONE_IF[zone]
    return DEFAULT_IF


def structure_totals(steps: list[dict], sport: str, ftp: int | None = None, lthr: int | None = None) -> tuple[int, int]:
    """Liefert (Minuten, TSS) aus der Struktur. TSS = Stunden * IF^2 * 100."""
    minutes = 0.0
    tss = 0.0

    def add(block: dict, times: int = 1) -> None:
        nonlocal minutes, tss
        m = block_minutes(block["duration"], sport) * times
        minutes += m
        tss += (m / 60.0) * (intensity(block.get("target", {}), ftp, lthr) ** 2) * 100.0

    for step in steps:
        if step["type"] == "cycle":
            add(step["work"], step["repeats"])
            add(step["recovery"], step["repeats"])
        else:
            add(step)
    return int(round(minutes)), int(round(tss))


def add_minutes(time_hhmm: str | None, minutes: int) -> str | None:
    if not time_hhmm:
        return None
    hours, mins = (int(part) for part in time_hhmm.split(":"))
    total = (hours * 60 + mins + max(0, minutes)) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"
