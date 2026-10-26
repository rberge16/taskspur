"""FastAPI-Anwendung: API unter /api, Frontend unter /."""
from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from . import config, db, intervals, store
from .schemas import BrickIn, ConnectionIn, LinkIn, PhaseIn, PlanIn, SettingsIn, WorkoutIn

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class Guard(BaseHTTPMiddleware):
    """Host-Prüfung (DNS-Rebinding), Same-Origin-Pflicht für schreibende Aufrufe, Sicherheits-Header."""

    async def dispatch(self, request: Request, call_next):
        host = request.headers.get("host", "")
        if host not in config.allowed_hosts():
            return JSONResponse({"detail": "Unzulässiger Host."}, status_code=421)
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None and origin.split("://", 1)[-1] != host:
                return JSONResponse({"detail": "Anfragen von fremden Seiten sind nicht erlaubt."}, status_code=403)
            if request.headers.get("x-requested-with") != "taktspur":
                return JSONResponse({"detail": "Fehlender Taktspur-Header."}, status_code=403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response


def create_app(database_path: Path | None = None) -> FastAPI:
    holder: dict[str, sqlite3.Connection] = {}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        holder["conn"] = db.open_database(database_path)
        yield
        holder["conn"].close()

    app = FastAPI(title="Taktspur", version="2.0.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(Guard)

    def conn() -> sqlite3.Connection:
        return holder["conn"]

    @app.exception_handler(store.NotFound)
    async def _nf(_r: Request, exc: store.NotFound):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(store.Rejected)
    async def _rej(_r: Request, exc: store.Rejected):
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.exception_handler(intervals.IntegrationError)
    async def _ie(_r: Request, exc: intervals.IntegrationError):
        return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=exc.status)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "schema": db.schema_version(conn()), "port": config.PORT}

    # ----- Einstellungen -----
    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return store.get_settings(conn())

    @app.put("/api/settings")
    def put_settings(payload: SettingsIn) -> dict[str, Any]:
        return store.set_settings(conn(), payload.model_dump(exclude_none=True))

    @app.post("/api/preview")
    def preview(payload: WorkoutIn) -> dict[str, Any]:
        """Dauer und TSS aus der Struktur (Live-Vorschau im Editor, ohne zu speichern)."""
        minutes, tss, _ = store._computed(conn(), payload)
        return {"duration_min": minutes, "tss": tss}

    # ----- Pläne -----
    @app.get("/api/plans")
    def plans() -> list[dict[str, Any]]:
        return store.list_plans(conn())

    @app.post("/api/plans", status_code=201)
    def plan_create(payload: PlanIn) -> dict[str, Any]:
        return store.create_plan(conn(), payload)

    @app.put("/api/plans/{plan_id}")
    def plan_update(plan_id: str, payload: PlanIn) -> dict[str, Any]:
        return store.update_plan(conn(), plan_id, payload)

    @app.delete("/api/plans/{plan_id}", status_code=204)
    def plan_delete(plan_id: str) -> None:
        store.delete_plan(conn(), plan_id)

    @app.post("/api/plans/{plan_id}/phases", status_code=201)
    def phase_add(plan_id: str, payload: PhaseIn) -> dict[str, Any]:
        return store.add_phase(conn(), plan_id, payload)

    @app.put("/api/phases/{phase_id}")
    def phase_update(phase_id: str, payload: PhaseIn) -> dict[str, Any]:
        return store.update_phase(conn(), phase_id, payload)

    @app.delete("/api/phases/{phase_id}", status_code=204)
    def phase_delete(phase_id: str) -> None:
        store.delete_phase(conn(), phase_id)

    # ----- Workouts -----
    def auto_send(ids: list[str]) -> dict[str, Any]:
        """Automatische Übertragung: nur wenn ausdrücklich aktiviert; gleicher Schutz wie manuell."""
        if not store.get_settings(conn())["intervals_auto_send"]:
            return {"auto": False}
        results = []
        for wid in ids:
            try:
                intervals.send_workout(conn(), wid, automatic=True)
                results.append({"id": wid, "ok": True})
            except intervals.IntegrationError as exc:
                results.append({"id": wid, "ok": False, "code": exc.code, "message": exc.message})
        return {"auto": True, "results": results}

    def with_sync(workouts: list[dict[str, Any]], ids: list[str]) -> dict[str, Any]:
        info = auto_send(ids)
        fresh = [store.get_workout(conn(), w["id"]) for w in workouts]
        return {"workouts": fresh, "auto_send": info}

    @app.get("/api/workouts")
    def workouts(start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"), end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
        return store.list_workouts(conn(), start, end)

    @app.post("/api/workouts", status_code=201)
    def workout_create(payload: WorkoutIn) -> dict[str, Any]:
        created = store.create_workout(conn(), payload)
        return with_sync([created], [created["id"]])

    @app.post("/api/workouts/brick", status_code=201)
    def brick_create(payload: BrickIn) -> dict[str, Any]:
        parts = store.create_brick(conn(), payload)
        return with_sync(parts, [p["id"] for p in parts])

    @app.get("/api/workouts/{workout_id}")
    def workout_get(workout_id: str) -> dict[str, Any]:
        return store.get_workout(conn(), workout_id)

    @app.put("/api/workouts/{workout_id}")
    def workout_update(workout_id: str, payload: WorkoutIn) -> dict[str, Any]:
        updated = store.update_workout(conn(), workout_id, payload)
        affected = [updated]
        partner = store.partner_of(conn(), updated)
        if partner and updated["link_order"] == 1:
            affected.append(partner)
        # Nur bereits übertragene Einheiten werden bei automatischer Übertragung aktualisiert bzw. neue gesendet.
        return with_sync(affected, [w["id"] for w in affected])

    @app.post("/api/workouts/{workout_id}/send")
    def workout_send(workout_id: str) -> dict[str, Any]:
        return intervals.send_workout(conn(), workout_id)

    @app.post("/api/workouts/{workout_id}/unlink")
    def workout_unlink(workout_id: str) -> list[dict[str, Any]]:
        return store.unlink(conn(), workout_id)

    @app.post("/api/workouts/{workout_id}/link")
    def workout_link(workout_id: str, body: LinkIn) -> list[dict[str, Any]]:
        """workout_id = Teil 1, body.second_id = Teil 2."""
        return store.link(conn(), workout_id, body.second_id)

    @app.delete("/api/workouts/{workout_id}")
    def workout_delete(workout_id: str, cascade: bool = False) -> dict[str, Any]:
        target = store.get_workout(conn(), workout_id)
        victims = [target]
        partner = store.partner_of(conn(), target)
        if cascade and partner:
            victims.append(partner)
        remote_deleted = []
        for victim in victims:  # erst extern löschen; schlägt das fehl, bleibt lokal alles erhalten
            if victim["synced_at"] and not victim["read_only"]:
                intervals.delete_remote(conn(), victim)
                remote_deleted.append(victim["id"])
        store.delete_workout(conn(), workout_id, cascade=cascade)
        return {"deleted": [v["id"] for v in victims], "remote_deleted": remote_deleted}

    # ----- Intervals.icu -----
    @app.get("/api/intervals")
    def intervals_status() -> dict[str, Any]:
        return intervals.status(conn())

    @app.post("/api/intervals/verify")
    def intervals_verify() -> dict[str, Any]:
        return intervals.verify(conn())

    @app.put("/api/intervals")
    def intervals_connect(payload: ConnectionIn) -> dict[str, Any]:
        return intervals.connect(conn(), payload.athlete_id, payload.api_key)

    @app.delete("/api/intervals", status_code=204)
    def intervals_disconnect() -> None:
        intervals.disconnect(conn())

    @app.get("/api/intervals/log")
    def intervals_log() -> list[dict[str, Any]]:
        return intervals.logs(conn())

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
