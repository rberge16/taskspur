"""Reduziert lange Zeitreihen (FIT: 1 Hz, mehrere Stunden) für Diagramme, ohne Spitzen zu verlieren.
Largest-Triangle-Three-Buckets (LTTB): behält die optische Form; der Pi liefert dem Browser nur wenige hundert Punkte."""
from __future__ import annotations

from typing import Sequence


def lttb(xs: Sequence[float], ys: Sequence[float | None], threshold: int) -> tuple[list[float], list[float | None]]:
    n = len(xs)
    if len(ys) != n:
        raise ValueError("x und y müssen gleich lang sein")
    if threshold < 3 or n <= threshold:
        return list(xs), list(ys)
    # Lücken (None) bleiben als Lücken erhalten: jedes zusammenhängende Stück wird einzeln reduziert.
    segments, start = [], 0
    for i in range(n + 1):
        if i == n or ys[i] is None:
            if i > start:
                segments.append((start, i))
            if i < n:
                segments.append((i, i + 1))     # einzelne Lücke
            start = i + 1
    real = [(a, b) for a, b in segments if ys[a] is not None]
    total = sum(b - a for a, b in real) or 1
    out_x: list[float] = []
    out_y: list[float | None] = []
    for a, b in segments:
        if ys[a] is None:
            out_x.append(xs[a]); out_y.append(None)
            continue
        share = max(3, round(threshold * (b - a) / total))
        sx, sy = _lttb_segment(xs[a:b], ys[a:b], share)  # type: ignore[arg-type]
        out_x += sx; out_y += sy
    return out_x, out_y


def _lttb_segment(xs, ys, threshold):
    n = len(xs)
    if n <= threshold:
        return list(xs), list(ys)
    sampled = [(xs[0], ys[0])]
    every = (n - 2) / (threshold - 2)
    a = 0
    for i in range(threshold - 2):
        start = int((i + 1) * every) + 1
        end = min(int((i + 2) * every) + 1, n)
        avg_x = sum(xs[start:end]) / max(1, end - start)
        avg_y = sum(ys[start:end]) / max(1, end - start)
        r_start, r_end = int(i * every) + 1, int((i + 1) * every) + 1
        best, best_i = -1.0, r_start
        ax, ay = xs[a], ys[a]
        for j in range(r_start, r_end):
            area = abs((ax - avg_x) * (ys[j] - ay) - (ax - xs[j]) * (avg_y - ay)) / 2
            if area > best:
                best, best_i = area, j
        sampled.append((xs[best_i], ys[best_i]))
        a = best_i
    sampled.append((xs[-1], ys[-1]))
    return [p[0] for p in sampled], [p[1] for p in sampled]


def bucket_mean(t: Sequence[float], columns: dict[str, Sequence[float | None]], max_points: int) -> tuple[list[float], dict[str, list[float | None]]]:
    """Gemeinsames Zeitraster für alle Kanäle: Mittelwert je Zeitfenster. Ab ≤ max_points bleibt alles unverändert (volle Auflösung)."""
    n = len(t)
    if max_points < 2 or n <= max_points:
        return list(t), {k: list(v) for k, v in columns.items()}
    width = (t[-1] - t[0]) / max_points or 1.0
    out_t: list[float] = []
    out: dict[str, list[float | None]] = {k: [] for k in columns}
    i = 0
    while i < n:
        edge = t[0] + (int((t[i] - t[0]) / width) + 1) * width
        j = i
        while j < n and t[j] < edge:
            j += 1
        j = max(j, i + 1)
        out_t.append(round(sum(t[i:j]) / (j - i), 1))
        for k, col in columns.items():
            vals = [v for v in col[i:j] if v is not None]
            out[k].append(round(sum(vals) / len(vals), 3) if vals else None)
        i = j
    return out_t, out
