"""Before/after differences between stored revisions of the same event. Pure, no I/O.

Every displayed difference is read from stored canonical event fields; nothing is
inferred from identifiers or prose. "Overlaps window" compares the record's
validity with the delivery window at the delivery's own scope; it is the same
time rule the assessment uses, without the scenario-clock "already ended" check.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .impact import MATERIAL_FIELDS, overlaps
from .models import Delivery, Event

LABELS = {"status": "Status", "corridor_id": "Scope", "valid_from": "Valid from",
          "valid_until": "Valid until", "event_type": "Type", "claim_key": "Claim",
          "claim_value": "Claimed value"}


def fmt(value) -> str:
    if value is None:
        return "missing"
    if isinstance(value, datetime):
        return f"{value:%d %b %H:%M} UTC"
    if isinstance(value, str) and value.startswith("OUTSIDE:"):
        return "outside warning area"
    if isinstance(value, str) and value.startswith("FN-"):
        return "inside warning area"
    return str(value)


def overlaps_window(e: Event, d: Delivery) -> bool:
    return (e.status == "active" and e.corridor_id == d.corridor_id
            and e.valid_from is not None and e.valid_until is not None
            and overlaps(e.valid_from, e.valid_until, d.window_start, d.window_end))


@dataclass(frozen=True)
class Change:
    origin: str
    event_id: str
    from_revision: int
    to_revision: int
    published_at: datetime
    fields: tuple[tuple[str, str, str], ...]   # (label, before, after)
    overlap_before: bool
    overlap_after: bool

    @property
    def material(self) -> bool:
        return bool(self.fields)

    @property
    def summary(self) -> str:
        if self.overlap_before != self.overlap_after:
            return ("Now overlaps this delivery window" if self.overlap_after
                    else "No longer overlaps this delivery window")
        if not self.material:
            return "Text or publication details only; no material field changed"
        return "Material fields changed; overlap with this delivery window unchanged"


def for_delivery(d: Delivery, events: list[Event]) -> list[Change]:
    """Consecutive stored revisions of every event that ever referred to this
    delivery's scope (including the recorded 'outside' mapping), oldest first."""
    scopes = {d.corridor_id, "OUTSIDE:" + d.corridor_id}
    chains: dict[tuple[str, str], list[Event]] = {}
    for e in events:
        chains.setdefault(e.key, []).append(e)
    out = []
    for revs in chains.values():
        revs.sort(key=lambda e: e.revision)
        if not any(e.corridor_id in scopes for e in revs):
            continue
        for old, new in zip(revs, revs[1:]):
            fields = tuple((LABELS[f], fmt(getattr(old, f)), fmt(getattr(new, f)))
                           for f in MATERIAL_FIELDS if getattr(old, f) != getattr(new, f))
            out.append(Change(new.origin, new.event_id, old.revision, new.revision, new.published_at,
                              fields, overlaps_window(old, d), overlaps_window(new, d)))
    out.sort(key=lambda c: (c.published_at, c.event_id, c.to_revision))
    return out
