"""The recording form: what the person types before pressing Record, and the live label state.

People appear only as pseudonyms ``P1``, ``P2``, ... (CLAUDE.md, D-008). Anything else is refused, and the refused
text is never echoed in an error message or stored.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .naming import slugify

PSEUDONYM_RE = re.compile(r"^P\d+$")
RECORDABLE_STREAMS = ("adc_raw", "accel")  # D-020: adc_dec is not recorded
DEFAULT_PROTOCOL = "walk-pass-v1"
LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9 _.-]{0,39}$")
MAX_PERSONS = 12
FORBIDDEN_NOTES_PREFIX = "rzlab:"

Pace = Literal["slow", "normal", "fast"]


def check_pseudonym(value: str) -> str:
    if not isinstance(value, str) or not PSEUDONYM_RE.match(value):
        # the rejected text is deliberately not part of the message
        raise ValueError("people are pseudonyms P1, P2, ... only (a capital P and digits); never write a name")
    return value


def check_label(value: str) -> str:
    v = value.strip().lower()
    if not LABEL_RE.match(v):
        raise ValueError("label: 1-40 characters, lower-case letters, digits, space, dot, dash, underscore")
    return v


def list_protocols(repo_root: Path | None) -> list[str]:
    """Protocol names: the files in ``docs/protocols/*.md`` (default first). Falls back to the default only."""
    names: list[str] = []
    if repo_root is not None:
        folder = repo_root / "docs" / "protocols"
        if folder.is_dir():
            names = sorted(p.stem for p in folder.glob("*.md"))
    if DEFAULT_PROTOCOL in names:
        names.remove(DEFAULT_PROTOCOL)
    return [DEFAULT_PROTOCOL, *names]


class Sensor(BaseModel):
    """Where one channel (or, without ``ch``, every channel of the stream not listed on its own) sits."""

    model_config = ConfigDict(extra="forbid")

    stream: Literal["adc_raw", "accel"]
    ch: int | None = Field(default=None, ge=0, le=7, description="channel in the stream; omit = all unlisted channels")
    position_m: list[float] = Field(min_length=2, max_length=3, description="x, y[, z] in metres")
    port: int | None = Field(default=None, ge=1, le=4)
    head: str | None = Field(default=None, max_length=64, description="e.g. geophone/sm24; default from the node")
    serial: str | None = Field(default=None, max_length=32)
    mount: str | None = Field(default=None, max_length=32)

    @field_validator("position_m")
    @classmethod
    def _finite(cls, v: list[float]) -> list[float]:
        if any(not math.isfinite(x) or abs(x) > 1000 for x in v):
            raise ValueError("positions are finite numbers of metres (at most 1000)")
        return v


class SessionForm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site: str = Field(min_length=1, max_length=64, description="e.g. home-a; stored as a [a-z0-9-] slug in the name")
    room: str = Field(min_length=1, max_length=64)
    floor: str | None = Field(default=None, max_length=40, description="floor covering/level; goes into notes")
    surface: str | None = Field(default=None, max_length=120, description="e.g. laminate on concrete slab")
    persons: list[str] = Field(default_factory=list, max_length=MAX_PERSONS, description="pseudonyms P1, P2, ...")
    protocol: str = Field(default=DEFAULT_PROTOCOL, min_length=1, max_length=64)
    streams: list[Literal["adc_raw", "accel"]] | None = Field(default=None, description="omit = adc_raw and accel")
    sensors: list[Sensor] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=500, description="free text, no names")
    marker: bool = Field(default=True, description="start the phone marker listener")
    marker_host: str | None = Field(
        default=None,
        max_length=64,
        description="the one address the marker listens on (and the QR code names); one of options.marker.hosts. "
        "Omit = options.marker.bind",
    )

    @field_validator("persons")
    @classmethod
    def _persons(cls, v: list[str]) -> list[str]:
        for p in v:
            check_pseudonym(p)
        if len(set(v)) != len(v):
            raise ValueError("each pseudonym once")
        return v

    @field_validator("site", "room")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not slugify(v):
            raise ValueError("needs at least one letter or digit (a-z, 0-9)")
        return v

    @field_validator("protocol")
    @classmethod
    def _protocol(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", v):
            raise ValueError("protocol names use letters, digits, dot, dash and underscore")
        return v

    @field_validator("notes")
    @classmethod
    def _notes(cls, v: str | None) -> str | None:
        if v is not None and any(line.strip().lower().startswith(FORBIDDEN_NOTES_PREFIX) for line in v.splitlines()):
            raise ValueError("notes may not start a line with 'rzlab:' (the lab writes those lines itself)")
        return v

    @field_validator("floor", "surface")
    @classmethod
    def _no_separators(cls, v: str | None) -> str | None:
        if v is not None and any(c in v for c in ";\r\n"):
            raise ValueError("no ';' or line breaks here")
        return v

    @model_validator(mode="after")
    def _streams_unique(self) -> SessionForm:
        if self.streams is not None:
            if not self.streams:
                raise ValueError("streams: choose at least one, or leave it out for all")
            if len(set(self.streams)) != len(self.streams):
                raise ValueError("streams: each stream once")
        return self


class LabelState(BaseModel):
    """What a mark carries: the label text and who/how. Taken from here when a mark starts."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(default="walk", description="e.g. walk, silence")
    person: str | None = Field(default=None, description="pseudonym P1, P2, ...")
    pace: Pace | None = None
    shoes: bool | None = None

    @field_validator("label")
    @classmethod
    def _label(cls, v: str) -> str:
        return check_label(v)

    @field_validator("person")
    @classmethod
    def _person(cls, v: str | None) -> str | None:
        return None if v is None else check_pseudonym(v)


class LabelOverrides(BaseModel):
    """A mark request may override single fields of the current label state for this mark only."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = None
    person: str | None = None
    pace: Pace | None = None
    shoes: bool | None = None

    @field_validator("label")
    @classmethod
    def _label(cls, v: str | None) -> str | None:
        return None if v is None else check_label(v)

    @field_validator("person")
    @classmethod
    def _person(cls, v: str | None) -> str | None:
        return None if v is None else check_pseudonym(v)
