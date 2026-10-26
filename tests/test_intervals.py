"""Intervals.icu: Verbindung, Export, Fehlerfälle, Schreibschutz, Geheimnisschutz. Alles gegen simulierte Antworten."""
import json
import sqlite3

import pytest

from app import config, db
from tests.conftest import SECRET, connect, cycle_steps, workout


def create(client, **over):
    return client.post("/api/workouts", json=workout(**over)).json()["workouts"][0]


# ---------- Verbindung ----------

def test_status_starts_disconnected(client):
    assert client.get("/api/intervals").json() == {"connected": False}


def test_connect_saves_id_encrypted_key_and_reverifies_after_restart(client, fake, datadir):
    connect(client)
    st = client.get("/api/intervals").json()
    assert st["connected"] is True and st["athlete_id"] == "i12345"
    raw = sqlite3.connect(datadir / "t.sqlite3").execute("SELECT encrypted_key FROM integration").fetchone()[0]
    assert SECRET not in raw and len(raw) > 40
    assert SECRET not in json.dumps(st)
    assert client.post("/api/intervals/verify").json()["connected"] is True  # erneute Prüfung
    assert any(c.method == "GET" for c in fake.calls)


def test_verify_reports_unreachable_without_forgetting_credentials(client, fake):
    connect(client)
    fake.mode = "connect"
    st = client.post("/api/intervals/verify").json()
    assert st["connected"] is False and "nicht erreichbar" in st["last_error"]
    fake.mode = "ok"
    assert client.post("/api/intervals/verify").json()["connected"] is True


def test_disconnect_removes_credentials(client, datadir):
    connect(client)
    assert client.delete("/api/intervals").status_code == 204
    assert client.get("/api/intervals").json() == {"connected": False}
    assert sqlite3.connect(datadir / "t.sqlite3").execute("SELECT COUNT(*) FROM integration").fetchone()[0] == 0


@pytest.mark.parametrize("mode,text", [
    ("401", "API-Schlüssel abgelehnt"), ("404", "Athleten-ID"), ("timeout", "nicht erreichbar"), ("connect", "nicht erreichbar"),
])
def test_connect_errors_are_clear_and_leak_no_secret(client, fake, mode, text):
    fake.mode = mode
    r = client.put("/api/intervals", json={"athlete_id": "i12345", "api_key": SECRET})
    assert r.status_code in (422, 503) and text in r.json()["detail"]
    assert SECRET not in r.text
    assert client.get("/api/intervals").json() == {"connected": False}  # nichts halb gespeichert


def test_athlete_id_format_is_validated(client):
    for bad in ("../../etc", "i12/../x", "abc", "i1 2", "i" + "9" * 30):
        assert client.put("/api/intervals", json={"athlete_id": bad, "api_key": SECRET}).status_code == 422


# ---------- Export ----------

def test_export_sends_exactly_once_with_stable_id_and_all_fields(client, fake):
    connect(client)
    w = create(client, title="VO2 Block", sport="Radfahren", start_time="06:30", description="Fokus", steps=cycle_steps())
    n = len(fake.posts())
    r = client.post(f"/api/workouts/{w['id']}/send")
    assert r.status_code == 200 and r.json()["sync_status"] == "sent"
    assert len(fake.posts()) == n + 1  # genau ein Aufruf
    ev = fake.events[f"taktspur-workout-{w['id']}"]
    assert ev["category"] == "WORKOUT" and ev["type"] == "Ride" and ev["name"] == "VO2 Block"
    assert ev["start_date_local"] == "2026-11-02T06:30:00"
    assert ev["moving_time"] == w["duration_min"] * 60 and ev["icu_training_load"] == w["tss"]
    assert ev["target"] == "POWER"
    assert "Fokus" in ev["description"] and "4x" in ev["description"]
    assert "280-300w" in ev["description"] and "intensity=interval" in ev["description"] and "intensity=recovery" in ev["description"]
    assert "intensity=warmup" in ev["description"] and "Z1 HR" in ev["description"]


def test_repeated_save_and_send_updates_same_external_record(client, fake):
    connect(client)
    w = create(client)
    for _ in range(3):
        client.put(f"/api/workouts/{w['id']}", json=workout(title="Geändert"))
        client.post(f"/api/workouts/{w['id']}/send")
    assert list(fake.events) == [f"taktspur-workout-{w['id']}"]  # keine Dublette
    assert fake.events[f"taktspur-workout-{w['id']}"]["name"] == "Geändert"
    assert all(c.url.params.get("upsert") == "true" for c in fake.posts())


@pytest.mark.parametrize("sport,expected", [("Radfahren", "Ride"), ("Laufen", "Run"), ("Schwimmen", "Swim"), ("Kraft / Mobility", "WeightTraining")])
def test_sport_mapping_does_not_turn_everything_into_ride(client, fake, sport, expected):
    connect(client)
    w = create(client, sport=sport)
    client.post(f"/api/workouts/{w['id']}/send")
    assert fake.events[f"taktspur-workout-{w['id']}"]["type"] == expected


def test_status_values_visible_in_workout(client, fake):
    connect(client)
    client.put("/api/settings", json={"intervals_auto_send": False})
    w = create(client)
    assert w["sync_status"] == "none"
    client.post(f"/api/workouts/{w['id']}/send")
    got = client.get(f"/api/workouts/{w['id']}").json()
    assert got["sync_status"] == "sent" and got["synced_at"]
    fake.mode = "500"
    client.post(f"/api/workouts/{w['id']}/send")
    assert client.get(f"/api/workouts/{w['id']}").json()["sync_status"] == "error"


# ---------- Fehlerfälle: jede Meldung verständlich und von der UI anzeigbar ----------

def test_error_not_connected(client):
    w = create(client)
    r = client.post(f"/api/workouts/{w['id']}/send")
    assert r.status_code == 409 and r.json()["code"] == "not_connected" and "nicht verbunden" in r.json()["detail"]
    assert client.get(f"/api/workouts/{w['id']}").json()["sync_error"]


def test_error_date_missing(client, fake):
    connect(client)
    w = create(client, date=None)
    r = client.post(f"/api/workouts/{w['id']}/send")
    assert r.json()["code"] == "date_missing" and "Datum fehlt" in r.json()["detail"]
    assert fake.posts() == []


def test_error_step_missing_shows_abschnitt_fehlt(client, fake):
    connect(client)
    w = create(client, steps=[])
    r = client.post(f"/api/workouts/{w['id']}/send")
    assert r.json()["code"] == "steps_missing" and "Abschnitt fehlt" in r.json()["detail"]
    assert fake.posts() == []


@pytest.mark.parametrize("mode,code,text", [
    ("404", "athlete_not_found", "Athleten-ID"),
    ("401", "bad_credentials", "API-Schlüssel"),
    ("timeout", "unreachable", "nicht erreichbar"),
    ("422", "rejected", "abgelehnt"),
    ("500", "provider_down", "Serverfehler"),
])
def test_send_error_matrix(client, fake, mode, code, text):
    connect(client)
    w = create(client)
    fake.mode = mode
    r = client.post(f"/api/workouts/{w['id']}/send")
    assert r.json()["code"] == code and text in r.json()["detail"]
    assert SECRET not in r.text
    assert client.get(f"/api/workouts/{w['id']}").json()["sync_status"] == "error"
    logs = client.get("/api/intervals/log").json()
    assert SECRET not in json.dumps(logs) and any(l["level"] == "error" for l in logs)


# ---------- Schreibschutz ----------

def insert_foreign(datadir, origin):
    conn = sqlite3.connect(datadir / "t.sqlite3")
    conn.execute(
        "INSERT INTO workouts(id,date,sport,title,origin,ext_id,created_at,updated_at,steps_json) VALUES(?,?,?,?,?,?,?,?,?)",
        (f"foreign-{origin}", "2026-11-02", "Laufen", "Fremd", origin, "intervals-777", "t", "t", '[{"type":"free","duration":{"value":10,"unit":"min"},"target":{"type":"open"}}]'),
    )
    conn.commit()
    conn.close()
    return f"foreign-{origin}"


@pytest.mark.parametrize("origin", ["intervals", "completed"])
def test_imported_and_completed_are_never_written_changed_or_deleted(client, fake, datadir, origin):
    connect(client)
    wid = insert_foreign(datadir, origin)
    calls_before = len(fake.calls)
    assert client.post(f"/api/workouts/{wid}/send").status_code == 403
    assert client.put(f"/api/workouts/{wid}", json=workout()).status_code == 403
    assert client.delete(f"/api/workouts/{wid}").status_code == 403
    assert len(fake.calls) == calls_before  # kein einziger Aufruf nach außen
    assert client.get(f"/api/workouts/{wid}").json()["read_only"] is True


def test_browser_cannot_inject_foreign_external_id(client, fake):
    connect(client)
    r = client.post("/api/workouts", json=workout(**{"external_id": "intervals-777"}))
    assert r.status_code == 422  # unbekanntes Feld abgelehnt
    w = create(client)
    client.post(f"/api/workouts/{w['id']}/send")
    assert all(k.startswith("taktspur-workout-") for k in fake.events)


# ---------- Löschen ----------

def test_delete_removes_remote_and_local(client, fake):
    connect(client)
    w = create(client)
    client.post(f"/api/workouts/{w['id']}/send")
    r = client.delete(f"/api/workouts/{w['id']}")
    assert r.json()["remote_deleted"] == [w["id"]] and fake.events == {}
    assert client.get("/api/workouts").json() == []


def test_delete_keeps_local_when_remote_fails(client, fake):
    connect(client)
    w = create(client)
    client.post(f"/api/workouts/{w['id']}/send")
    fake.mode = "timeout"
    r = client.delete(f"/api/workouts/{w['id']}")
    assert r.status_code == 503 and "nicht erreichbar" in r.json()["detail"]
    assert len(client.get("/api/workouts").json()) == 1  # nichts geht verloren


def test_delete_never_sent_workout_makes_no_remote_call(client, fake):
    connect(client)
    client.put("/api/settings", json={"intervals_auto_send": False})
    w = create(client)
    n = len(fake.calls)
    client.delete(f"/api/workouts/{w['id']}")
    assert len(fake.calls) == n


# ---------- Automatische Übertragung ----------

def test_sync_default_on_send_update_delete(client, fake):
    """Geplante Workouts: senden, bei Änderung aktualisieren, beim Löschen entfernen."""
    connect(client)
    assert client.get("/api/settings").json()["intervals_auto_send"] is True
    w = client.post("/api/workouts", json=workout(title="a")).json()["workouts"][0]
    assert len(fake.posts()) == 1 and w["sync_status"] == "sent"
    r = client.put(f"/api/workouts/{w['id']}", json=workout(title="b")).json()
    assert len(fake.posts()) == 2 and r["workouts"][0]["sync_status"] == "sent"
    assert fake.events[f"taktspur-workout-{w['id']}"]["name"] == "b"
    client.delete(f"/api/workouts/{w['id']}")
    assert fake.events == {}


def test_sync_off_still_updates_already_sent_but_never_sends_new(client, fake):
    connect(client)
    client.put("/api/settings", json={"intervals_auto_send": False})
    w = create(client)
    client.put(f"/api/workouts/{w['id']}", json=workout(title="x"))
    assert fake.posts() == []  # neue Einheit wird bei "aus" nicht gesendet
    client.post(f"/api/workouts/{w['id']}/send")
    posts = len(fake.posts())
    client.put(f"/api/workouts/{w['id']}", json=workout(title="y"))
    assert len(fake.posts()) == posts + 1  # bereits übertragene Einheit bleibt aktuell


def test_sync_without_connection_does_nothing_quietly(client, fake):
    r = client.post("/api/workouts", json=workout())
    assert r.status_code == 201 and r.json()["workouts"][0]["sync_status"] == "none" and fake.calls == []


def test_auto_send_when_enabled_uses_same_protection(client, fake):
    connect(client)
    client.put("/api/settings", json={"intervals_auto_send": True})
    r = client.post("/api/workouts", json=workout())
    assert r.json()["auto_send"]["results"][0]["ok"] is True and len(fake.posts()) == 1
    r = client.post("/api/workouts", json=workout(steps=[]))  # gleicher Schutz: Abschnitt fehlt
    assert r.json()["auto_send"]["results"][0]["code"] == "steps_missing"
    assert len(fake.posts()) == 1


def test_auto_send_failure_does_not_lose_workout(client, fake):
    connect(client)
    client.put("/api/settings", json={"intervals_auto_send": True})
    fake.mode = "timeout"
    r = client.post("/api/workouts", json=workout())
    assert r.status_code == 201 and r.json()["workouts"][0]["sync_status"] == "error"
    assert len(client.get("/api/workouts").json()) == 1


def test_brick_both_parts_sent_separately_with_own_ids(client, fake):
    connect(client)
    client.put("/api/settings", json={"intervals_auto_send": True})
    p1 = workout(title="Rad", steps=cycle_steps())
    p2 = workout(title="Lauf", sport="Laufen", steps=[{"type": "free", "duration": {"value": 20, "unit": "min"}, "target": {"type": "heart_rate", "zone": "Z2"}}])
    parts = client.post("/api/workouts/brick", json={"part1": p1, "part2": p2}).json()["workouts"]
    assert len(fake.events) == 2
    types = {fake.events[f"taktspur-workout-{p['id']}"]["type"] for p in parts}
    assert types == {"Ride", "Run"}


# ---------- Geheimnisse ----------

def test_api_key_never_appears_anywhere(client, fake, datadir, caplog):
    connect(client)
    w = create(client)
    client.post(f"/api/workouts/{w['id']}/send")
    fake.mode = "401"
    client.post(f"/api/workouts/{w['id']}/send")
    blobs = [client.get(p).text for p in ("/api/intervals", "/api/intervals/log", "/api/settings", "/api/workouts", "/api/health")]
    assert all(SECRET not in b for b in blobs) and SECRET not in caplog.text
    on_disk = (datadir / "t.sqlite3").read_bytes()
    assert SECRET.encode() not in on_disk
    wal = datadir / "t.sqlite3-wal"
    if wal.exists():
        assert SECRET.encode() not in wal.read_bytes()


def test_secret_key_file_is_outside_database_and_ignored_by_git():
    ignore = open(config.__file__.replace("app/config.py", ".gitignore")).read()
    for pattern in ("*.sqlite3", "*.sqlite3-wal", "*.sqlite3-shm", "backups/", "secret.key", ".env"):
        assert pattern in ignore


def test_unreadable_key_gives_clear_message(client, fake, datadir):
    connect(client)
    (datadir / "secret.key").unlink()  # Schlüsseldatei verloren
    w = create(client)
    r = client.post(f"/api/workouts/{w['id']}/send")
    assert r.json()["code"] == "key_unreadable" and "neu verbinden" in r.json()["detail"]
