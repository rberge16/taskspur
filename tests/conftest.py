import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import intervals
from app.main import create_app

HDR = {"X-Requested-With": "taktspur"}
SECRET = "geheimer-api-key-98765"


class FakeIntervals:
    """Simuliertes Intervals.icu. Zeichnet jede Anfrage auf; es verlässt nie ein echtes Paket den Prozess."""

    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.mode = "ok"      # ok | 401 | 404 | 422 | 500 | timeout | connect
        self.events: dict[str, dict] = {}
        self.activities: list[dict] = []          # Antwort von /athlete/{id}/activities
        self.files: dict[str, bytes | int | None] = {}   # id → FIT-Bytes | HTTP-Status | None (404)
        self.list_params: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.mode == "timeout":
            raise httpx.ReadTimeout("zeitüberschreitung", request=request)
        if self.mode == "connect":
            raise httpx.ConnectError("keine verbindung", request=request)
        if self.mode != "ok":
            return httpx.Response(int(self.mode), json={"error": "x"}, request=request)
        path = request.url.path
        if request.method == "GET" and path.endswith("/activities") and "/athlete/" in path:
            self.list_params.append(dict(request.url.params))
            return httpx.Response(200, json=self.activities, request=request)
        if request.method == "GET" and "/activity/" in path and (path.endswith("/fit-file") or path.endswith("/file")):
            ext = path.split("/activity/")[1].split("/")[0]
            payload = self.files.get(ext)
            if isinstance(payload, bytes):
                return httpx.Response(200, content=payload, request=request)
            return httpx.Response(payload if isinstance(payload, int) else 404, request=request)
        if request.method == "GET" and path.startswith("/api/v1/athlete/"):
            return httpx.Response(200, json={"id": path.rsplit("/", 1)[-1], "name": "Test"}, request=request)
        if request.method == "POST" and path.endswith("/events/bulk"):
            body = json.loads(request.content)
            for ev in body:
                self.events[ev["external_id"]] = ev  # Upsert über external_id
            return httpx.Response(200, json=[{"id": 1}], request=request)
        if request.method == "PUT" and path.endswith("/events/bulk-delete"):
            for item in json.loads(request.content):
                self.events.pop(item["external_id"], None)
            return httpx.Response(200, json={"deleted": 1}, request=request)
        return httpx.Response(404, request=request)

    def posts(self):
        return [c for c in self.calls if c.method == "POST"]


@pytest.fixture()
def fake(monkeypatch):
    f = FakeIntervals()
    monkeypatch.setattr(
        intervals, "client_factory",
        lambda key: httpx.Client(base_url=intervals.BASE_URL, transport=httpx.MockTransport(f.handler), auth=("API_KEY", key)),
    )
    return f


@pytest.fixture()
def datadir(tmp_path, monkeypatch):
    monkeypatch.setenv("TAKTSPUR_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture()
def client(datadir, fake):
    app = create_app(datadir / "t.sqlite3")
    with TestClient(app, base_url="http://127.0.0.1:8775", headers=HDR) as c:
        yield c


def workout(**over):
    base = {
        "title": "Test GA1", "date": "2026-11-02", "start_time": "07:00", "sport": "Radfahren", "kind": "normal",
        "steps": [{"type": "warmup", "duration": {"value": 10, "unit": "min"}, "target": {"type": "power", "zone": "Z1"}}],
    }
    base.update(over)
    return base


def cycle_steps():
    return [
        {"type": "warmup", "duration": {"value": 15, "unit": "min"}, "target": {"type": "heart_rate", "zone": "Z1"}},
        {"type": "cycle", "repeats": 4,
         "work": {"duration": {"value": 4, "unit": "min"}, "target": {"type": "power", "zone": "Z5", "min": 280, "max": 300}},
         "recovery": {"duration": {"value": 3, "unit": "min"}, "target": {"type": "power", "zone": "Z1"}}},
        {"type": "cooldown", "duration": {"value": 10, "unit": "min"}, "target": {"type": "open"}},
    ]


def connect(client):
    r = client.put("/api/intervals", json={"athlete_id": "i12345", "api_key": SECRET})
    assert r.status_code == 200, r.text
    return r
