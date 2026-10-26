"""Eingabe-Validierung. Alles, was der Browser schickt, läuft durch diese Modelle."""
from __future__ import annotations

import re
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
SPORTS = ("Radfahren", "Laufen", "Schwimmen", "Kraft / Mobility", "Recovery")
Text = Annotated[str, Field(max_length=2000)]


class Duration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int = Field(ge=1, le=100000)
    unit: Literal["sec", "min", "km"] = "min"


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["open", "power", "heart_rate"] = "open"
    zone: Optional[Literal["Z1", "Z2", "Z3", "Z4", "Z5", "Z6", "Z7"]] = None
    min: Optional[int] = Field(default=None, ge=1, le=2500)
    max: Optional[int] = Field(default=None, ge=1, le=2500)

    @field_validator("max")
    @classmethod
    def _range(cls, value, info):
        low = info.data.get("min")
        if value is not None and low is not None and value < low:
            raise ValueError("Der obere Zielwert darf nicht unter dem unteren liegen.")
        return value


class Block(BaseModel):
    model_config = ConfigDict(extra="forbid")
    duration: Duration
    target: Target = Target()


class SimpleStep(Block):
    type: Literal["warmup", "free", "cooldown"]


class CycleStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["cycle"] = "cycle"
    repeats: int = Field(ge=1, le=99)
    work: Block
    recovery: Block


Step = Annotated[Union[SimpleStep, CycleStep], Field(discriminator="type")]


class WorkoutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    date: Optional[str] = None
    start_time: Optional[str] = None
    sport: Literal["Radfahren", "Laufen", "Schwimmen", "Kraft / Mobility", "Recovery"]
    description: Text = ""
    kind: Literal["normal", "important", "test"] = "normal"
    duration_min: Optional[int] = Field(default=None, ge=0, le=2000)
    steps: list[Step] = Field(default_factory=list, max_length=60)
    plan_id: Optional[str] = Field(default=None, max_length=64)
    phase_id: Optional[str] = Field(default=None, max_length=64)

    @field_validator("title", "description")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("date")
    @classmethod
    def _date(cls, value):
        if value in (None, ""):
            return None
        if not DATE_RE.match(value):
            raise ValueError("Datum muss JJJJ-MM-TT sein.")
        return value

    @field_validator("start_time")
    @classmethod
    def _time(cls, value):
        if value in (None, ""):
            return None
        if not TIME_RE.match(value):
            raise ValueError("Startzeit muss HH:MM sein.")
        return value


class BrickIn(BaseModel):
    """Koppeleinheit: zwei vollständige Teile. Teil 2 bekommt Datum/Startzeit vom Server."""
    model_config = ConfigDict(extra="forbid")
    part1: WorkoutIn
    part2: WorkoutIn


class LinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    second_id: str = Field(min_length=1, max_length=64)


class SyncIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: Optional[int] = Field(default=None, ge=1, le=730)


class PlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    goal_date: Optional[str] = None
    status: Literal["draft", "active", "inactive"] = "active"
    color: int = Field(default=1, ge=1, le=6)

    @field_validator("goal_date")
    @classmethod
    def _date(cls, value):
        if value in (None, ""):
            return None
        if not DATE_RE.match(value):
            raise ValueError("Datum muss JJJJ-MM-TT sein.")
        return value


class PhaseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    start_date: str
    end_date: str
    description: Text = ""

    @field_validator("start_date", "end_date")
    @classmethod
    def _date(cls, value):
        if not DATE_RE.match(value):
            raise ValueError("Datum muss JJJJ-MM-TT sein.")
        return value


class ConnectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    athlete_id: str = Field(min_length=1, max_length=20)
    api_key: str = Field(min_length=8, max_length=200, repr=False)

    @field_validator("athlete_id")
    @classmethod
    def _athlete(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"i?\d{1,12}", value):
            raise ValueError("Athleten-ID hat das Format i12345 (oder nur Ziffern).")
        return value

    @field_validator("api_key")
    @classmethod
    def _key(cls, value: str) -> str:
        value = value.strip()
        if re.search(r"\s", value):
            raise ValueError("Der API-Schlüssel darf keine Leerzeichen enthalten.")
        return value


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intervals_auto_send: Optional[bool] = None
    ftp: Optional[int] = Field(default=None, ge=50, le=600)
    lthr: Optional[int] = Field(default=None, ge=80, le=230)
    intervals_history_days: Optional[int] = Field(default=None, ge=1, le=730)
    intervals_sync_on_start: Optional[bool] = None
