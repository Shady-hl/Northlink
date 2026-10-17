"""Validated data contracts for Northlink (schema_version 1).

All datetimes must carry a timezone and are normalised to UTC so that the
canonical representation used for integrity checks is stable.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

SCHEMA_VERSION = 1


def _to_utc(d: datetime) -> datetime:
    return d.astimezone(timezone.utc)


UTCDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]
NonEmpty = Annotated[str, Field(min_length=1, max_length=200)]

EventType = Literal["advisory", "warning", "closure", "restriction", "report", "other"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Coverage(_Strict):
    """One origin's claim to have checked a scope (corridor/region) at a time."""

    origin: NonEmpty
    scope_id: NonEmpty
    source_retrieved_at: UTCDatetime
    successful: bool


class Event(_Strict):
    event_id: NonEmpty
    revision: int = Field(ge=1)
    origin: NonEmpty
    # Optional so that incomplete reports can be imported and flagged
    # "needs confirmation" instead of being silently dropped.
    corridor_id: str | None = None
    published_at: UTCDatetime
    valid_from: UTCDatetime | None = None
    valid_until: UTCDatetime | None = None
    event_type: EventType
    status: Literal["active", "cancelled"]
    claim_key: str | None = None
    claim_value: str | None = None
    supersedes_revision: int | None = Field(default=None, ge=1)
    source_url: str | None = None
    text: str = ""

    @model_validator(mode="after")
    def _check(self) -> "Event":
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        if (self.claim_key is None) != (self.claim_value is None):
            raise ValueError("claim_key and claim_value must be given together")
        if self.supersedes_revision is not None and self.supersedes_revision >= self.revision:
            raise ValueError("supersedes_revision must be lower than revision")
        return self

    @property
    def key(self) -> tuple[str, str]:
        return (self.origin, self.event_id)


class Packet(_Strict):
    schema_version: Literal[1]
    packet_id: NonEmpty
    kind: Literal["live", "recorded", "synthetic"]
    retrieved_at: UTCDatetime
    label: str | None = None
    coverage: list[Coverage] = []
    events: list[Event] = []

    @model_validator(mode="after")
    def _check(self) -> "Packet":
        seen: set[tuple[str, str, int]] = set()
        for e in self.events:
            ident = (e.origin, e.event_id, e.revision)
            if ident in seen:
                raise ValueError(f"duplicate event identity in packet: {ident}")
            seen.add(ident)
            demo = e.origin.startswith("demo-")
            if demo != (self.kind == "synthetic"):
                raise ValueError(
                    f"event {e.event_id}: origin '{e.origin}' does not match packet kind '{self.kind}' "
                    "(demo-* origins must be in synthetic packets, and synthetic packets may only use demo-* origins)")
            if self.kind == "synthetic" and e.source_url:
                raise ValueError(
                    f"synthetic event {e.event_id} must not carry a source_url "
                    "(synthetic records must not imitate official sources)"
                )
        for c in self.coverage:
            if c.origin.startswith("demo-") != (self.kind == "synthetic"):
                raise ValueError(f"coverage origin '{c.origin}' does not match packet kind '{self.kind}'")
            if c.source_retrieved_at > self.retrieved_at:
                raise ValueError(
                    f"coverage {c.origin}/{c.scope_id}: source_retrieved_at is later than the packet's retrieved_at")
        return self


class Delivery(_Strict):
    delivery_id: NonEmpty
    corridor_id: NonEmpty
    window_start: UTCDatetime
    window_end: UTCDatetime
    priority: Literal["High", "Medium", "Normal"]
    deadline: UTCDatetime
    requirements: list[str] = []

    @model_validator(mode="after")
    def _check(self) -> "Delivery":
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        return self


class DeliveryPlan(_Strict):
    schema_version: Literal[1]
    plan_id: NonEmpty
    kind: Literal["synthetic", "recorded"]
    label: str | None = None
    deliveries: list[Delivery]

    @model_validator(mode="after")
    def _check(self) -> "DeliveryPlan":
        ids = [d.delivery_id for d in self.deliveries]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate delivery_id(s): {sorted(dupes)}")
        return self


DECISIONS = [
    "Proceed as planned",
    "Hold for confirmation",
    "Delay departure",
    "Escalate",
    "Other (see note)",
]


class ReviewInput(_Strict):
    delivery_id: NonEmpty
    person: NonEmpty
    decision: Literal[tuple(DECISIONS)]  # type: ignore[valid-type]
    note: str = Field(default="", max_length=4000)


def canonical(model: BaseModel) -> str:
    """Stable JSON used for identity/integrity comparisons."""
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def content_hash(model: BaseModel) -> str:
    return hashlib.sha256(canonical(model).encode()).hexdigest()


def format_validation_error(exc: ValidationError) -> list[str]:
    """Human-readable, one line per problem, with the location in the file."""
    lines = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(top level)"
        msg = err["msg"].removeprefix("Value error, ")
        lines.append(f"{loc}: {msg}")
    return lines
