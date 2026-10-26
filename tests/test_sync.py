import gzip
import sqlite3
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import sync
from app.main import create_app
from tests.conftest import SECRET, connect
from tests.fitgen import build_fit

HDR = {"X-Requested-With": "taktspur"}


def rr(n=900, seed=1):
    return (470 + np.random.default_rng(seed).normal(0, 15, n)).tolist()


def act(ext, name="Lauf", start="2026-10-25T16:05:07Z", **over):
    return {"id": ext, "name": name, "type": "Run", "start_date": start, "start_date_local": start.replace("Z", ""), "moving_time": 1800, "distance": 5000,
            "average_heartrate": 140, "icu_training_load": 45, **over}


def wait_done(client, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        st = client.get("/api/intervals/sync").json()
        if not st["running"] and st["last"]:
            return st
        time.sleep(0.05)
    raise AssertionError("Abgleich wurde nicht fertig")


def start_and_wait(client):
    assert client.post("/api/intervals/sync", json={}).status_code == 202
    return wait_done(client)


def test_sync_imports_new_activities_read_only(client, fake):
    connect(client)
    fake.activities = [act("i1", "Dresden Laufen"), act("i2", "Rad", type="Ride", start="2026-10-24T08:00:00Z")]
    fake.files = {"i1": build_fit(600, rr()), "i2": build_fit(300)}
    last = start_and_wait(client)["last"]
    assert (last["found"], last["imported"], last["summary_only"], last["failed"], last["error"]) == (2, 2, 0, [], None)
    lst = client.get("/api/activities").json()
    assert {a["name"] for a in lst} == {"Dresden Laufen", "Rad"} and all(a["source"] == "intervals" for a in lst)
    assert {a["external_id"] for a in lst} == {"i1", "i2"}
    assert any(a["has_rr"] for a in lst)
    assert {c.method for c in fake.calls if "/activit" in c.url.path} == {"GET"}          # nur lesend
    assert not fake.posts() and not fake.events                                           # nichts an Intervals.icu gesendet
    assert fake.list_params[-1]["oldest"] < fake.list_params[-1]["newest"]


def test_second_sync_adds_only_new_ones_and_respects_history_days(client, fake):
    connect(client)
    assert client.put("/api/settings", json={"intervals_history_days": 7}).json()["intervals_history_days"] == 7
    fake.activities = [act("i1")]
    fake.files = {"i1": build_fit(300)}
    start_and_wait(client)
    n_calls = len([c for c in fake.calls if c.url.path.endswith("/fit-file")])
    fake.activities = [act("i1"), act("i3", "Neu")]
    fake.files["i3"] = build_fit(400)
    last = start_and_wait(client)["last"]
    assert (last["found"], last["imported"], last["already"]) == (2, 1, 1)
    assert len([c for c in fake.calls if c.url.path.endswith("/fit-file")]) == n_calls + 1       # i1 wurde nicht erneut geladen
    from datetime import date, timedelta
    assert fake.list_params[-1]["oldest"] == (date.today() - timedelta(days=7)).isoformat()
    assert len(client.get("/api/activities").json()) == 2


def test_activity_without_file_keeps_summary(client, fake):
    connect(client)
    fake.activities = [act("i9", "Manuell", icu_average_watts=210)]
    fake.files = {}                                  # beide Datei-Endpunkte → 404
    last = start_and_wait(client)["last"]
    assert last["summary_only"] == 1 and last["imported"] == 0
    a = client.get("/api/activities").json()[0]
    assert a["name"] == "Manuell" and a["has_data"] is False and a["avg_hr"] == 140 and a["avg_power"] == 210
    d = client.get(f"/api/activities/{a['id']}").json()
    assert d["t"] == [] and d["session"]["training_stress_score"] == 45
    assert client.get(f"/api/activities/{a['id']}/table").json()["rows"] == []
    assert client.get(f"/api/activities/{a['id']}/hrv").json()["available"] is False


def test_gzip_file_and_garbage_file(client, fake):
    connect(client)
    fake.activities = [act("i1"), act("i2", start="2026-10-24T08:00:00Z")]
    fake.files = {"i1": gzip.compress(build_fit(300)), "i2": b"das ist kein FIT-Inhalt, nur Text zum Testen"}
    last = start_and_wait(client)["last"]
    assert last["imported"] == 1 and last["summary_only"] == 1


def test_locally_deleted_activity_is_not_fetched_again(client, fake):
    connect(client)
    fake.activities = [act("i1")]
    fake.files = {"i1": build_fit(300)}
    start_and_wait(client)
    aid = client.get("/api/activities").json()[0]["id"]
    assert client.delete(f"/api/activities/{aid}").status_code == 204
    last = start_and_wait(client)["last"]
    assert last["imported"] == 0 and last["already"] == 1 and client.get("/api/activities").json() == []


def test_manual_import_with_intervals_filename_prevents_duplicate_sync(client, fake):
    connect(client)
    data = build_fit(300, rr())
    r = client.post("/api/activities?filename=i7700_Dresden_Laufen.fit", content=data, headers={**HDR, "Content-Type": "application/octet-stream"})
    assert r.status_code == 201 and r.json()["external_id"] == "i7700"
    fake.activities = [act("i7700")]
    fake.files = {"i7700": build_fit(500)}
    last = start_and_wait(client)["last"]
    assert last["imported"] == 0 and last["already"] == 1 and len(client.get("/api/activities").json()) == 1


def test_same_file_gets_external_id_assigned(client, fake):
    connect(client)
    data = build_fit(300)
    assert client.post("/api/activities?filename=export.fit", content=data, headers={**HDR, "Content-Type": "application/octet-stream"}).status_code == 201
    fake.activities = [act("i5")]
    fake.files = {"i5": data}                        # identische Datei
    last = start_and_wait(client)["last"]
    assert last["already"] == 1 and last["imported"] == 0
    assert client.get("/api/activities").json()[0]["external_id"] == "i5"


@pytest.mark.parametrize("mode,text", [("401", "API-Schlüssel abgelehnt"), ("500", "Serverfehler"), ("timeout", "nicht erreichbar")])
def test_sync_errors_are_clear_and_leak_no_secret(client, fake, mode, text):
    connect(client)
    fake.mode = mode
    last = start_and_wait(client)["last"]
    assert text in last["error"] and SECRET not in str(last)
    assert SECRET not in client.get("/api/intervals/log").text


def test_sync_requires_connection_and_rejects_bad_ids(client, fake):
    assert client.post("/api/intervals/sync", json={}).status_code == 409
    connect(client)
    fake.activities = [act("../../etc/passwd"), act("i1 2"), act("i8")]
    fake.files = {"i8": build_fit(300)}
    last = start_and_wait(client)["last"]
    assert last["imported"] == 1 and last["found"] == 3
    assert all("passwd" not in str(c.url) for c in fake.calls)


def test_rate_limit_stops_with_partial_result(client, fake):
    connect(client)
    fake.activities = [act("i1"), act("i2", start="2026-10-26T08:00:00Z")]
    fake.files = {"i1": build_fit(300), "i2": 429}
    last = start_and_wait(client)["last"]
    assert last["imported"] == 1 and "begrenzt" in last["error"]


def test_sync_on_start_runs_automatically_and_can_be_disabled(datadir, fake):
    app = create_app(datadir / "t.sqlite3")
    with TestClient(app, base_url="http://127.0.0.1:8775", headers=HDR) as c:
        connect(c)
        fake.activities = [act("i1")]
        fake.files = {"i1": build_fit(300)}
        assert c.put("/api/settings", json={"intervals_sync_on_start": True}).json()["intervals_sync_on_start"] is True
    with TestClient(create_app(datadir / "t.sqlite3"), base_url="http://127.0.0.1:8775", headers=HDR) as c2:      # „Neustart“
        st = wait_done(c2)
        assert st["last"]["imported"] == 1
    fake.activities = [act("i1"), act("i2", start="2026-10-26T08:00:00Z")]
    fake.files["i2"] = build_fit(300)
    with TestClient(create_app(datadir / "t.sqlite3"), base_url="http://127.0.0.1:8775", headers=HDR) as c3:
        c3.put("/api/settings", json={"intervals_sync_on_start": False})
    n = len([x for x in fake.calls if x.url.path.endswith("/activities")])
    with TestClient(create_app(datadir / "t.sqlite3"), base_url="http://127.0.0.1:8775", headers=HDR) as c4:
        time.sleep(0.5)
        assert len([x for x in fake.calls if x.url.path.endswith("/activities")]) == n      # deaktiviert → kein Abgleich
        assert len(c4.get("/api/activities").json()) == 1


def test_status_reports_saved_key_without_exposing_it(client, fake):
    connect(client)
    st = client.get("/api/intervals").json()
    assert st["has_key"] is True and SECRET not in str(st)
    fake.mode = "401"
    assert client.put("/api/intervals", json={"athlete_id": "i12345", "api_key": "anderer-schluessel-123"}).status_code == 422
    assert client.get("/api/intervals").json()["has_key"] is True        # fehlgeschlagener Versuch löscht den alten Schlüssel nicht
