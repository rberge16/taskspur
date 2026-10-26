"""HRV-Auswertung aus echten RR-Intervallen (FIT-Nachricht `hrv`) – keine Schätzung aus der Herzfrequenz.

Methodik (Literatur):
- DFA, kurzfristiger Skalierungsexponent α1 über Boxgrößen 4 ≤ n ≤ 16 Schläge (Peng et al. 1995).
- Vorverarbeitung wie in Kubios HRV: Trend-Entfernung per „smoothness priors“ mit λ = 500 (Tarvainen et al. 2002).
- Gleitendes 120-s-Fenster (üblich in der Sportphysiologie, z. B. Gronwald et al.; Rogers et al. 2021).
- Orientierungswerte aus Stufentests gesunder, trainierter Erwachsener: α1 ≈ 0,75 ↔ erste Schwelle (HRVT1),
  α1 ≈ 0,5 ↔ zweite Schwelle (HRVT2). Das sind Populationsmittel mit individueller Streuung, keine Diagnose.
- Artefakte (Fehl-/Doppelerkennung, Extrasystolen) verfälschen α1 stark. Erkennung hier einfach und nachvollziehbar:
  Abweichung > 20 % vom lokalen Median (11 Schläge) oder physiologisch unmöglicher Wert; Ersatz per linearer Interpolation.
  Fenster mit mehr als 5 % Artefakten werden als ungültig markiert (konservative Konvention, kein Normwert).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

import numpy as np

WINDOW_S = 120.0
STEP_S = 5.0
LAMBDA = 500
N_MIN, N_MAX = 4, 16
MAX_ARTIFACT_SHARE = 0.05
RR_MIN_MS, RR_MAX_MS = 250.0, 2500.0
DEV_LIMIT = 0.20
THRESHOLDS = {"HRVT1": 0.75, "HRVT2": 0.5}


def detect_artifacts(rr_ms: np.ndarray) -> np.ndarray:
    """True = Schlag unplausibel."""
    n = len(rr_ms)
    bad = (rr_ms < RR_MIN_MS) | (rr_ms > RR_MAX_MS)
    if n < 5:
        return bad
    pad = np.pad(rr_ms, 5, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(pad, 11)[:n]
    med = np.median(windows, axis=1)
    return bad | (np.abs(rr_ms - med) > DEV_LIMIT * med)


def correct(rr_ms: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Gibt (korrigierte RR, Artefaktmaske) zurück; die Länge bleibt gleich (Interpolation über den Schlagindex)."""
    bad = detect_artifacts(rr_ms)
    if not bad.any():
        return rr_ms.astype(float).copy(), bad
    good = ~bad
    if good.sum() < 2:
        return rr_ms.astype(float).copy(), bad
    idx = np.arange(len(rr_ms))
    return np.interp(idx, idx[good], rr_ms[good]), bad


@lru_cache(maxsize=512)
def _detrend_matrix(n: int) -> np.ndarray:
    """Matrix M mit detrendet = M @ z   (M = I − (I + λ²·D2ᵀD2)⁻¹)."""
    if n < 3:
        return np.eye(n)
    d2 = np.zeros((n - 2, n))
    for i in range(n - 2):
        d2[i, i:i + 3] = (1.0, -2.0, 1.0)
    inv = np.linalg.inv(np.eye(n) + (LAMBDA ** 2) * (d2.T @ d2))
    return np.eye(n) - inv


def dfa_alpha1(rr_ms: np.ndarray) -> float | None:
    """α1 eines RR-Abschnitts (bereits artefaktkorrigiert). None, wenn zu kurz oder degeneriert."""
    n = len(rr_ms)
    if n < 2 * N_MAX:
        return None
    z = _detrend_matrix(n) @ rr_ms
    y = np.cumsum(z - z.mean())
    sizes, flucts = [], []
    for box in range(N_MIN, N_MAX + 1):
        count = n // box
        if count < 2:
            continue
        seg = y[: count * box].reshape(count, box)
        x = np.arange(box, dtype=float)
        xm = x.mean()
        sxx = ((x - xm) ** 2).sum()
        slope = ((seg - seg.mean(axis=1, keepdims=True)) * (x - xm)).sum(axis=1) / sxx
        resid = seg - seg.mean(axis=1, keepdims=True) - slope[:, None] * (x - xm)
        f = float(np.sqrt((resid ** 2).mean()))
        if f > 0:
            sizes.append(box); flucts.append(f)
    if len(sizes) < 5:
        return None
    return float(np.polyfit(np.log(sizes), np.log(flucts), 1)[0])


def analyse(rr_ms_raw: list[float]) -> dict[str, Any]:
    """Komplette HRV-Auswertung einer Aktivität."""
    raw = np.asarray(rr_ms_raw, dtype=float)
    if len(raw) < 40:
        return {"available": False, "reason": "Zu wenige RR-Intervalle in der Datei."}
    fixed, bad = correct(raw)
    t = np.cumsum(raw) / 1000.0                       # Zeit seit Aufzeichnungsbeginn (s), am Ende jedes Schlags
    tc = np.cumsum(fixed) / 1000.0
    # --- DFA a1 im gleitenden Fenster ---
    times, alpha, share = [], [], []
    start = 0.0
    total = tc[-1]
    while start + WINDOW_S <= total + 1e-9:
        lo, hi = np.searchsorted(tc, start, side="right"), np.searchsorted(tc, start + WINDOW_S, side="right")
        seg_bad = bad[lo:hi]
        a = dfa_alpha1(fixed[lo:hi]) if hi - lo >= 2 * N_MAX else None
        s = float(seg_bad.mean()) if len(seg_bad) else 1.0
        times.append(round(start + WINDOW_S, 1))
        share.append(round(s * 100, 1))
        alpha.append(None if (a is None or s > MAX_ARTIFACT_SHARE) else round(a, 3))
        start += STEP_S
    valid = [a for a in alpha if a is not None]
    # --- Kennzahlen über die ganze Aktivität (auf korrigierten RR) ---
    diff = np.diff(fixed)
    stats = {
        "beats": int(len(raw)), "artifacts": int(bad.sum()), "artifact_percent": round(float(bad.mean()) * 100, 2),
        "mean_rr_ms": round(float(fixed.mean()), 1), "mean_hr": round(60000.0 / float(fixed.mean()), 1),
        "sdnn_ms": round(float(fixed.std(ddof=1)), 1), "rmssd_ms": round(float(np.sqrt((diff ** 2).mean())), 1),
        "pnn50_percent": round(float((np.abs(diff) > 50).mean()) * 100, 1),
        "alpha1_valid_windows": len(valid), "alpha1_total_windows": len(alpha),
        "alpha1_mean": round(float(np.mean(valid)), 3) if valid else None,
        "alpha1_min": min(valid) if valid else None, "alpha1_max": max(valid) if valid else None,
    }
    # --- Zeitliche Anteile unter/über den Orientierungswerten ---
    if valid:
        v = np.asarray(valid)
        stats["share_above_075_percent"] = round(float((v > 0.75).mean()) * 100, 1)
        stats["share_075_to_05_percent"] = round(float(((v <= 0.75) & (v >= 0.5)).mean()) * 100, 1)
        stats["share_below_05_percent"] = round(float((v < 0.5).mean()) * 100, 1)
    return {
        "available": True, "method": {"window_s": WINDOW_S, "step_s": STEP_S, "lambda": LAMBDA, "box": [N_MIN, N_MAX],
                                      "max_artifact_percent": MAX_ARTIFACT_SHARE * 100, "artifact_rule": f">{int(DEV_LIMIT * 100)} % vom lokalen Median (11 Schläge)"},
        "stats": stats,
        "rr": {"t": [round(float(x), 2) for x in t], "ms": [round(float(x)) for x in raw], "artifact": [int(b) for b in bad]},
        "alpha1": {"t": times, "value": alpha, "artifact_percent": share},
    }


def threshold_estimate(alpha_t: list[float], alpha: list[float | None], hr_by_time: Any) -> dict[str, Any]:
    """Herzfrequenz bei α1 = 0,75 / 0,5 per linearer Regression α1 ~ HF über gültige Fenster.
    Nur belastbar bei breitem α1-Bereich (Stufentest); sonst ausdrücklich „nicht belastbar“."""
    xs, ys = [], []
    for t, a in zip(alpha_t, alpha):
        if a is None:
            continue
        hr = hr_by_time(t)
        if hr is not None:
            xs.append(hr); ys.append(a)
    out: dict[str, Any] = {"windows": len(xs), "reliable": False, "reason": ""}
    if len(xs) < 30:
        out["reason"] = "Zu wenige gültige Fenster (mindestens 30)."; return out
    x, y = np.asarray(xs), np.asarray(ys)
    if np.ptp(x) < 20 or y.min() > 0.75 or y.max() < 0.75:
        out["reason"] = "Die Belastung deckt den Bereich um α1 = 0,75 nicht ab (kein Stufentest)."; return out
    slope, icpt = np.polyfit(x, y, 1)
    r2 = float(np.corrcoef(x, y)[0, 1] ** 2)
    out["r2"] = round(r2, 3)
    if slope >= 0 or r2 < 0.5:
        out["reason"] = f"Kein ausreichend klarer Zusammenhang zwischen Herzfrequenz und α1 (R² = {r2:.2f})."; return out
    out["reliable"] = True
    out["hr_at_075"] = round(float((0.75 - icpt) / slope), 1)
    out["hr_at_05"] = round(float((0.5 - icpt) / slope), 1) if y.min() < 0.5 else None
    return out
