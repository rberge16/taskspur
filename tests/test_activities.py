import json

import numpy as np
import pytest

from app import hrv
from app.downsample import bucket_mean
from tests.fitgen import build_fit

HDR = {"X-Requested-With": "taktspur"}


def rr_series(n=1800, seed=3, artifacts=0):
    rng = np.random.default_rng(seed)
    rr = 480 + rng.normal(0, 14, n)
    for k in range(artifacts):
        rr[100 + k * 60] = 140          # Fehlerkennung (Doppelschlag)
    return rr.tolist()


def upload(client, data, name="Test_Lauf.fit"):
    return client.post(f"/api/activities?filename={name}", content=data, headers={**HDR, "Content-Type": "application/octet-stream"})


def test_import_with_hrv_end_to_end(client):
    r = upload(client, build_fit(1200, rr_series(artifacts=8)))
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["name"] == "Test_Lauf" and a["sport"] == "running" and a["has_rr"] is True
    assert a["duration_s"] == 1200 and abs(a["distance_m"] - 3_700) < 400 and a["avg_hr"] == 140
    d = client.get(f"/api/activities/{a['id']}").json()
    keys = {c["key"] for c in d["channels"]}
    assert {"heart_rate", "power", "speed", "altitude", "distance", "cadence"} <= keys
    assert len(d["t"]) == 1200 and all(len(v) == 1200 for v in d["data"].values())      # volle Auflösung
    assert d["data"]["cadence"][0] == 156                                                # Doppelschritte → Schritte/min
    assert len(d["laps"]) == 3
    assert [b["from_s"] for b in d["lap_bounds"]] == [0.0, 400.0, 800.0]   # gleiche Zeitachse wie die Diagramme
    # keine Profil-/GPS-Daten gespeichert
    assert "position_lat" not in json.dumps(d) and "friendly_name" not in json.dumps(d)
    h = client.get(f"/api/activities/{a['id']}/hrv").json()
    assert [lap["index"] for lap in h["laps"]] == [0, 1, 2] and all("alpha1_mean" in lap for lap in h["laps"])
    assert h["available"] and h["stats"]["artifacts"] >= 8 and 0.2 < h["stats"]["alpha1_mean"] < 0.9
    assert h["method"]["lambda"] == 500 and h["reference"] == {"HRVT1": 0.75, "HRVT2": 0.5}
    assert h["thresholds"]["reliable"] is False and h["thresholds"]["reason"]          # kein Stufentest → ausdrücklich nicht belastbar


def test_duplicate_invalid_and_no_rr(client):
    data = build_fit(300)
    first = upload(client, data)
    assert first.status_code == 201
    assert first.json()["has_rr"] is False
    assert upload(client, data).status_code == 409
    assert upload(client, b"das ist keine fit datei, nur text, lang genug").status_code == 422
    assert upload(client, b"").status_code == 422
    h = client.get(f"/api/activities/{first.json()['id']}/hrv").json()
    assert h["available"] is False and "RR" in h["reason"]


def test_guard_requires_header_for_upload(client):
    assert client.post("/api/activities", content=build_fit(60), headers={"X-Requested-With": ""}).status_code == 403


def test_table_csv_rename_delete(client):
    a = upload(client, build_fit(600, rr_series(900))).json()
    t = client.get(f"/api/activities/{a['id']}/table?bucket=60").json()
    assert len(t["rows"]) == 10 and t["rows"][0]["from_s"] == 0
    assert all(r["pace_s_per_km"] and 300 < r["pace_s_per_km"] < 420 for r in t["rows"])
    assert any(c["key"] == "alpha1" for c in t["columns"])
    assert client.get(f"/api/activities/{a['id']}/table?bucket=5").status_code == 422
    csv = client.get(f"/api/activities/{a['id']}/export.csv")
    assert csv.status_code == 200 and csv.text.splitlines()[0].startswith("time_s,") and len(csv.text.splitlines()) == 601
    assert client.put(f"/api/activities/{a['id']}", json={"name": "Neuer Name"}, headers=HDR).json()["name"] == "Neuer Name"
    assert client.put(f"/api/activities/{a['id']}", json={"name": " "}, headers=HDR).status_code == 422
    assert client.delete(f"/api/activities/{a['id']}", headers=HDR).status_code == 204
    assert client.get(f"/api/activities/{a['id']}").status_code == 404
    assert client.get("/api/activities").json() == []


def test_max_points_downsampling(client):
    a = upload(client, build_fit(1200)).json()
    d = client.get(f"/api/activities/{a['id']}?max_points=300").json()
    assert 250 <= len(d["t"]) <= 320 and all(len(v) == len(d["t"]) for v in d["data"].values())


# ---------- HRV: Verfahren ----------
def test_dfa_reference_signals():
    rng = np.random.default_rng(7)
    white = [hrv.dfa_alpha1(400 + 20 * rng.normal(size=300)) for _ in range(20)]
    walk = [hrv.dfa_alpha1(400 + 3 * np.cumsum(rng.normal(size=300))) for _ in range(20)]
    assert 0.4 < np.mean(white) < 0.7          # weißes Rauschen ≈ 0,5
    assert np.mean(walk) > 1.2                 # Random Walk ≈ 1,5


def test_artifacts_detected_and_replaced():
    rr = np.array(rr_series(400, artifacts=3))
    fixed, bad = hrv.correct(rr)
    assert bad.sum() >= 3 and fixed.min() > 400 and len(fixed) == len(rr)


def test_windows_with_too_many_artifacts_are_invalid():
    rr = rr_series(1000)
    for i in range(100, 400, 6):
        rr[i] = 150
    res = hrv.analyse(rr)
    invalid = [a for a, s in zip(res["alpha1"]["value"], res["alpha1"]["artifact_percent"]) if s > 5]
    assert invalid and all(a is None for a, s in zip(res["alpha1"]["value"], res["alpha1"]["artifact_percent"]) if s > 5)


def test_threshold_estimate_on_synthetic_ramp():
    t = list(range(120, 1800, 5))
    hr = {x: 110 + 70 * x / 1800 for x in t}
    alpha = [round(1.3 - (hr[x] - 110) * 0.0125, 3) for x in t]      # fallend mit der HF
    out = hrv.threshold_estimate(t, alpha, lambda x: hr[x])
    assert out["reliable"] and abs(out["hr_at_075"] - (110 + (1.3 - 0.75) / 0.0125)) < 1.5


def test_bucket_mean_keeps_small_series():
    t, c = bucket_mean([0, 1, 2], {"a": [1, 2, None]}, 10)
    assert t == [0, 1, 2] and c["a"] == [1, 2, None]


def test_migration_v1_to_v2_keeps_data_and_makes_backup(tmp_path):
    import sqlite3

    from app import db
    path = tmp_path / "old.sqlite3"
    raw = sqlite3.connect(path)
    raw.executescript(db.MIGRATIONS[0])
    raw.execute("INSERT INTO plans (id,name,status,color,created_at,updated_at) VALUES ('p1','Alt','active',1,'x','x')")
    raw.execute("PRAGMA user_version=1"); raw.commit(); raw.close()
    conn = db.open_database(path)
    assert db.schema_version(conn) == len(db.MIGRATIONS) >= 2
    assert conn.execute("SELECT name FROM plans WHERE id='p1'").fetchone()["name"] == "Alt"
    assert conn.execute("SELECT count(*) c FROM activities").fetchone()["c"] == 0
    assert list(tmp_path.glob("**/*.sqlite3")) and len(list(tmp_path.rglob("*"))) >= 3        # Backup neben der DB angelegt


def test_lap_alpha1_assigns_windows_by_midpoint_and_leaves_short_laps_empty():
    import json

    from app import activities, hrv

    laps = [
        {"start_time": "2026-01-01T10:00:00", "total_elapsed_time": 300},
        {"start_time": "2026-01-01T10:05:00", "total_elapsed_time": 60},   # kürzer als ein Fenster, keine Fenstermitte darin
        {"start_time": "2026-01-01T10:06:00+00:00", "total_elapsed_time": 300},
        {"start_time": None, "total_elapsed_time": 10},
    ]
    row = {"start_time": "2026-01-01T10:00:00", "laps_json": json.dumps(laps)}
    half = hrv.WINDOW_S / 2
    # Fenster-Enden so, dass die Mitten bei 100 s, 200 s (Runde 1) und 400 s (Runde 3) liegen; None = ungültiges Fenster
    alpha1 = {"t": [100 + half, 200 + half, 250 + half, 400 + half], "value": [1.0, 0.8, None, 0.4]}
    result = activities.lap_alpha1(row, alpha1)
    assert result[0]["alpha1_mean"] == 0.9 and result[0]["windows"] == 2
    assert result[1]["alpha1_mean"] is None and result[1]["windows"] == 0
    assert result[2]["alpha1_mean"] == 0.4 and result[2]["from_s"] == 360.0
    assert result[3]["from_s"] is None and result[3]["alpha1_mean"] is None
