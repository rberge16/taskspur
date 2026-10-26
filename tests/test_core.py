"""Datenbank, Backup, Kalender-/Plan-/Einheitenlogik, Koppeleinheiten, Sicherheits-Guard."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.main import create_app
from tests.conftest import HDR, cycle_steps, workout


# ---------- Port / Start ----------

def test_port_is_8775_and_never_8765():
    assert config.PORT == 8775
    assert 8765 in config.FORBIDDEN_PORTS and config.PORT not in config.FORBIDDEN_PORTS
    assert config.bind_host() == "127.0.0.1"


def test_health_reports_port(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["port"] == 8775


# ---------- Datenbank / Migration / Backup ----------

def test_existing_database_is_never_overwritten(datadir):
    path = datadir / "x.sqlite3"
    conn = db.open_database(path)
    conn.execute("INSERT INTO plans(id,name,status,color,created_at,updated_at) VALUES('p1','Mein Plan','active',1,'t','t')")
    conn.close()
    again = db.open_database(path)  # "Neuinstallation" / Update
    assert again.execute("SELECT name FROM plans WHERE id='p1'").fetchone()[0] == "Mein Plan"
    assert db.schema_version(again) == len(db.MIGRATIONS)
    again.close()


def test_backup_created_before_start_and_limited(datadir):
    path = datadir / "b.sqlite3"
    db.open_database(path).close()
    for _ in range(4):
        db.open_database(path).close()
    backups = list((datadir / "backups").glob("*.sqlite3"))
    assert 1 <= len(backups) <= config.BACKUP_KEEP
    probe = sqlite3.connect(backups[0])
    assert probe.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
    probe.close()


def test_newer_schema_is_refused_without_change(datadir):
    path = datadir / "n.sqlite3"
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE keep(x)")
    raw.execute("INSERT INTO keep VALUES(1)")
    raw.execute(f"PRAGMA user_version={len(db.MIGRATIONS) + 5}")
    raw.commit()
    raw.close()
    with pytest.raises(RuntimeError, match="aktualisieren"):
        db.open_database(path)
    check = sqlite3.connect(path)
    assert check.execute("SELECT x FROM keep").fetchone()[0] == 1
    check.close()


def test_data_survives_restart(datadir, fake):
    path = datadir / "r.sqlite3"
    with TestClient(create_app(path), base_url="http://127.0.0.1:8775", headers=HDR) as c:
        c.post("/api/workouts", json=workout(title="Bleibt"))
        plan = c.post("/api/plans", json={"name": "Plan A", "status": "active"}).json()
        c.post(f"/api/plans/{plan['id']}/phases", json={"name": "Basis", "start_date": "2026-11-01", "end_date": "2026-11-30"})
    with TestClient(create_app(path), base_url="http://127.0.0.1:8775", headers=HDR) as c:  # vollständiger Neustart
        items = c.get("/api/workouts").json()
        assert [w["title"] for w in items] == ["Bleibt"]  # genau einmal
        plans = c.get("/api/plans").json()
        assert plans[0]["name"] == "Plan A" and plans[0]["phases"][0]["name"] == "Basis"


# ---------- Einheiten: anlegen, ändern, löschen, keine Dubletten ----------

def test_create_once_and_repeated_save_updates_same_record(client):
    created = client.post("/api/workouts", json=workout()).json()["workouts"][0]
    wid = created["id"]
    for _ in range(3):  # wiederholtes Speichern
        assert client.put(f"/api/workouts/{wid}", json=workout(title="Test GA1")).status_code == 200
    items = client.get("/api/workouts").json()
    assert len(items) == 1 and items[0]["id"] == wid


def test_kinds_and_structure_calculation(client):
    for kind in ("normal", "important", "test"):
        r = client.post("/api/workouts", json=workout(title=kind, kind=kind, steps=cycle_steps()))
        w = r.json()["workouts"][0]
        assert w["kind"] == kind
    assert w["duration_min"] == 15 + 4 * 4 + 4 * 3 + 10  # 53
    assert w["tss"] > 0


def test_validation_rejects_bad_input(client):
    assert client.post("/api/workouts", json=workout(sport="Golf")).status_code == 422
    assert client.post("/api/workouts", json=workout(date="02.11.2026")).status_code == 422
    assert client.post("/api/workouts", json=workout(title="")).status_code == 422
    assert client.post("/api/workouts", json=workout(extra="x")).status_code == 422
    bad = workout(steps=[{"type": "warmup", "duration": {"value": 0, "unit": "min"}}])
    assert client.post("/api/workouts", json=bad).status_code == 422


def test_unicode_and_html_are_stored_verbatim_not_executed(client):
    evil = '<img src=x onerror=alert(1)> "Ä"'
    r = client.post("/api/workouts", json=workout(title=evil, description=evil))
    assert r.json()["workouts"][0]["title"] == evil  # Maskierung passiert beim Anzeigen (textContent)


def test_plan_assignment_rules_and_phase_shrink(client):
    plan = client.post("/api/plans", json={"name": "P", "status": "active"}).json()
    plan = client.post(f"/api/plans/{plan['id']}/phases", json={"name": "Basis", "start_date": "2026-11-01", "end_date": "2026-11-30"}).json()
    ph = plan["phases"][0]["id"]
    ok = client.post("/api/workouts", json=workout(plan_id=plan["id"], phase_id=ph, date="2026-11-10"))
    assert ok.status_code == 201
    out = client.post("/api/workouts", json=workout(plan_id=plan["id"], phase_id=ph, date="2026-12-10"))
    assert out.status_code == 422 and "außerhalb" in out.json()["detail"]
    shrink = client.put(f"/api/phases/{ph}", json={"name": "Basis", "start_date": "2026-11-01", "end_date": "2026-11-05"})
    assert shrink.status_code == 422  # Einheit würde sonst unsichtbar
    assert len(client.get("/api/workouts").json()) == 1


def test_deleting_plan_keeps_workouts(client):
    plan = client.post("/api/plans", json={"name": "P", "status": "active"}).json()
    plan = client.post(f"/api/plans/{plan['id']}/phases", json={"name": "B", "start_date": "2026-11-01", "end_date": "2026-11-30"}).json()
    client.post("/api/workouts", json=workout(plan_id=plan["id"], phase_id=plan["phases"][0]["id"], date="2026-11-10"))
    assert client.delete(f"/api/plans/{plan['id']}").status_code == 204
    items = client.get("/api/workouts").json()
    assert len(items) == 1 and items[0]["plan_id"] is None


def test_max_three_active_plans(client):
    for i in range(3):
        assert client.post("/api/plans", json={"name": f"P{i}", "status": "active"}).status_code == 201
    assert client.post("/api/plans", json={"name": "P4", "status": "active"}).status_code == 422


# ---------- Koppeleinheiten ----------

def make_brick(client, **over):
    p1 = workout(title="Rad", steps=cycle_steps(), start_time="07:00")
    p2 = workout(title="Lauf", sport="Laufen", steps=[{"type": "free", "duration": {"value": 30, "unit": "min"}, "target": {"type": "heart_rate", "zone": "Z2"}}])
    p1.update(over)
    r = client.post("/api/workouts/brick", json={"part1": p1, "part2": p2})
    assert r.status_code == 201, r.text
    return r.json()["workouts"]


def test_brick_parts_are_separate_complete_and_linked(client):
    a, b = make_brick(client)
    assert a["link_group"] == b["link_group"] and (a["link_order"], b["link_order"]) == (1, 2)
    assert (a["sport"], b["sport"]) == ("Radfahren", "Laufen")          # eigene Sportart
    assert a["steps"] != b["steps"] and b["steps"]                       # eigene Intervalle/Ziele
    assert a["tss"] > 0 and b["tss"] > 0 and a["tss"] != b["tss"]        # eigene Belastung
    assert b["date"] == a["date"] and b["start_time"] == "07:53"         # direkt nach Teil 1 (07:00 + 53 min)


def test_brick_part2_follows_part1_changes(client):
    a, b = make_brick(client)
    client.put(f"/api/workouts/{a['id']}", json=workout(title="Rad", steps=cycle_steps(), start_time="08:00", date="2026-11-04"))
    b2 = client.get(f"/api/workouts/{b['id']}").json()
    assert (b2["date"], b2["start_time"]) == ("2026-11-04", "08:53")
    # Dauer von Teil 1 ändern → Teil 2 rückt nach
    longer = cycle_steps(); longer[0]["duration"]["value"] = 45
    client.put(f"/api/workouts/{a['id']}", json=workout(title="Rad", steps=longer, start_time="08:00", date="2026-11-04"))
    assert client.get(f"/api/workouts/{b['id']}").json()["start_time"] == "09:23"


def test_brick_part2_cannot_drift_from_part1(client):
    a, b = make_brick(client)
    client.put(f"/api/workouts/{b['id']}", json=workout(title="Lauf", sport="Laufen", date="2027-01-01", start_time="03:00", steps=b["steps"]))
    b2 = client.get(f"/api/workouts/{b['id']}").json()
    assert (b2["date"], b2["start_time"]) == (a["date"], "07:53")


def test_deleting_part1_unlinks_part2_no_orphan(client):
    a, b = make_brick(client)
    client.delete(f"/api/workouts/{a['id']}")
    b2 = client.get(f"/api/workouts/{b['id']}").json()
    assert b2["link_group"] is None and b2["link_order"] is None


def test_cascade_delete_removes_both(client):
    a, b = make_brick(client)
    r = client.delete(f"/api/workouts/{a['id']}?cascade=true")
    assert sorted(r.json()["deleted"]) == sorted([a["id"], b["id"]])
    assert client.get("/api/workouts").json() == []


def test_unlink_endpoint(client):
    a, b = make_brick(client)
    r = client.post(f"/api/workouts/{a['id']}/unlink")
    assert all(w["link_group"] is None for w in r.json())


# ---------- Sicherheits-Guard ----------

def test_foreign_host_is_rejected(client):
    assert client.get("/api/health", headers={"Host": "evil.example:8775"}).status_code == 421


def test_cross_site_write_is_rejected(client):
    r = client.post("/api/workouts", json=workout(), headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    r = client.post("/api/workouts", json=workout(), headers={"X-Requested-With": ""})
    assert r.status_code == 403
    assert client.get("/api/workouts").json() == []


def test_security_headers(client):
    r = client.get("/api/health")
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"


def test_no_openapi_or_docs_exposed(client):
    assert client.get("/docs").status_code in (404, 405) or "text/html" not in client.get("/docs").headers.get("content-type", "")
    assert client.get("/openapi.json").status_code in (404, 405) or "openapi" not in client.get("/openapi.json").text[:50]
