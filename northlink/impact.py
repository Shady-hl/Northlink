"""Corridor/time matching, freshness and materiality. Pure functions, no I/O.

Matching rule (deliberately simple and reviewable): an event is relevant to a
delivery only when its *current* revision is active, declares the same reviewed
corridor ID, and its validity interval overlaps the travel window and has not
ended at the assessment time. No geographic inference is performed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .models import Coverage, Delivery, Event

# Demonstration policies only, not operational or safety standards.
FRESHNESS_THRESHOLD_MIN: dict[str, int] = {"demo-weather": 30, "demo-road": 15}
# Origins we expect to have checked every corridor; missing coverage is shown.
EXPECTED_ORIGINS = ["demo-weather", "demo-road"]

RESTRICTION_TYPES = {"closure", "restriction"}
ADVISORY_TYPES = {"advisory", "warning"}

# Ordered most to least urgent.
CATEGORIES = {
    "conflict": "Conflicting evidence - review needed",
    "restriction": "Reported restriction",
    "advisory": "Potential advisory impact",
    "needs_confirmation": "Incomplete record - needs confirmation",
    "no_match": "No matching records in checked sources (not a safety assessment)",
}
ATTENTION = {"conflict", "restriction", "advisory", "needs_confirmation"}

# Fields whose change alters what a reviewer relied on. Text-only edits are
# not material and do not reopen a review.
MATERIAL_FIELDS = (
    "status", "corridor_id", "valid_from", "valid_until",
    "event_type", "claim_key", "claim_value",
)


def overlaps(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> bool:
    return a0 < b1 and b0 < a1


def current_revisions(events: list[Event]) -> dict[tuple[str, str], Event]:
    """Highest revision per (origin, event_id). Version order, not arrival or
    publication order, decides which record is authoritative."""
    cur: dict[tuple[str, str], Event] = {}
    for e in events:
        if e.key not in cur or e.revision > cur[e.key].revision:
            cur[e.key] = e
    return cur


@dataclass
class CoverageState:
    origin: str
    scope_id: str
    last_success: datetime | None
    last_failure: datetime | None
    age_min: float | None
    threshold_min: int | None
    future: list = field(default_factory=list)

    @property
    def stale(self) -> bool:
        if self.last_success is None:
            return True
        return self.threshold_min is not None and self.age_min > self.threshold_min

    @property
    def label(self) -> str:
        if self.last_success is None:
            return "never successfully checked" + (" (future-dated record ignored)" if self.future else "")
        age = f"{self.age_min:.0f} min old"
        if self.threshold_min is None:
            return f"{age} (no freshness threshold defined)"
        return f"{age} - {'STALE' if self.stale else 'current'} (demo threshold {self.threshold_min} min)"


def coverage_states(coverage: list[Coverage], now: datetime) -> dict[tuple[str, str], CoverageState]:
    """Latest successful source_retrieved_at per origin/scope. Failed attempts are
    recorded separately and never erase or renew the last success."""
    out: dict[tuple[str, str], CoverageState] = {}
    for c in coverage:
        k = (c.origin, c.scope_id)
        s = out.setdefault(k, CoverageState(c.origin, c.scope_id, None, None, None,
                                            FRESHNESS_THRESHOLD_MIN.get(c.origin)))
        if c.source_retrieved_at > now:
            s.future.append(c.source_retrieved_at)  # not yet valid at this scenario time
        elif c.successful:
            if s.last_success is None or c.source_retrieved_at > s.last_success:
                s.last_success = c.source_retrieved_at
        elif s.last_failure is None or c.source_retrieved_at > s.last_failure:
            s.last_failure = c.source_retrieved_at
    for s in out.values():
        if s.last_success is not None:
            s.age_min = (now - s.last_success).total_seconds() / 60
    return out


@dataclass
class Assessment:
    delivery: Delivery
    category: str
    reasons: list[str]
    evidence: list[Event]            # relevant current event versions
    conflicts: dict[str, list[Event]]
    coverage: list[CoverageState]    # for this delivery's corridor
    missing_origins: list[str]
    incomplete: list[Event] = field(default_factory=list)

    @property
    def stale(self) -> bool:
        """Coverage that was checked but is now too old (or never succeeded)."""
        return any(c.stale for c in self.coverage)

    @property
    def stale_reasons(self) -> list[str]:
        return [f"{c.origin}/{c.scope_id}: {c.label}" for c in self.coverage if c.stale]

    @property
    def gap_reasons(self) -> list[str]:
        """Expected sources with no coverage record at all for this corridor."""
        return [f"{o}/{self.delivery.corridor_id}: not checked" for o in self.missing_origins]


def assess(delivery: Delivery, events: list[Event], coverage: list[Coverage], now: datetime) -> Assessment:
    cur = current_revisions(events)
    d = delivery
    relevant: list[Event] = []
    incomplete: list[Event] = []
    for e in cur.values():
        if e.status != "active":
            continue
        if e.corridor_id is None:
            # Unlocated: cannot be matched, so it cannot be ruled out either.
            if e.valid_until is None or e.valid_until > now:
                incomplete.append(e)
            continue
        if e.corridor_id != d.corridor_id:
            continue
        if e.valid_from is None or e.valid_until is None:
            incomplete.append(e)
            continue
        if e.valid_until <= now:
            continue  # ended; no longer provides current coverage
        if overlaps(e.valid_from, e.valid_until, d.window_start, d.window_end):
            relevant.append(e)
    relevant.sort(key=lambda e: (e.origin, e.event_id))

    claims: dict[str, list[Event]] = {}
    for e in relevant:
        if e.claim_key:
            claims.setdefault(e.claim_key, []).append(e)
    conflicts = {k: v for k, v in claims.items() if len({e.claim_value for e in v}) > 1}

    reasons: list[str] = []
    for k, v in conflicts.items():
        parts = ", ".join(f"{e.origin} {e.event_id} says {e.claim_value}" for e in v)
        reasons.append(f"Unresolved conflict on {k}: {parts}. No authority precedence is declared.")
    conflicted_ids = {e.key for v in conflicts.values() for e in v}
    restr = [e for e in relevant if e.key not in conflicted_ids and
             (e.event_type in RESTRICTION_TYPES or e.claim_value == "reported_closed")]
    adv = [e for e in relevant if e.key not in conflicted_ids and e.event_type in ADVISORY_TYPES]
    for e in restr:
        reasons.append(f"{e.event_id} ({e.origin}): reported {e.event_type} on {e.corridor_id} "
                       f"{e.valid_from:%d %b %H:%M}–{e.valid_until:%d %b %H:%M} UTC overlaps travel window.")
    for e in adv:
        reasons.append(f"{e.event_id} ({e.origin}): {e.event_type} on {e.corridor_id} "
                       f"{e.valid_from:%d %b %H:%M}–{e.valid_until:%d %b %H:%M} UTC overlaps travel window.")
    other = [e for e in relevant if e.key not in conflicted_ids and e not in restr and e not in adv]
    for e in other:
        what = f"reports {e.claim_value} ({e.claim_key})" if e.claim_key else f"{e.event_type} record"
        reasons.append(f"{e.event_id} ({e.origin}) {what} on {e.corridor_id} overlaps travel window - "
                       "single unclassified record, needs confirmation (not a safety assessment).")
    for e in incomplete:
        if e.corridor_id is None:
            reasons.append(f"{e.event_id} ({e.origin}) has no corridor/location - cannot be ruled out, needs confirmation.")
        else:
            reasons.append(f"{e.event_id} ({e.origin}) on {e.corridor_id} has no validity interval - needs confirmation.")

    if conflicts:
        cat = "conflict"
    elif restr:
        cat = "restriction"
    elif adv:
        cat = "advisory"
    elif incomplete or other:
        cat = "needs_confirmation"
    else:
        cat = "no_match"
        reasons.append("No active record from imported sources overlaps this corridor and window. "
                       "This does not mean the route is safe.")

    states = coverage_states(coverage, now)
    corr_cov = sorted((s for (o, sc), s in states.items() if sc == d.corridor_id), key=lambda s: s.origin)
    have = {s.origin for s in corr_cov}
    expected = (["met-metalerts-recorded"] if d.corridor_id.startswith("FN-") else EXPECTED_ORIGINS)
    missing = [o for o in expected if o not in have]
    return Assessment(d, cat, reasons, relevant, conflicts, corr_cov, missing, incomplete)


def material_fingerprint(a: Assessment) -> list[dict]:
    """What a review relied on, reduced to material fields. A review reopens when
    this changes (event retired/changed/newly applicable)."""
    return sorted(
        ({"origin": e.origin, "event_id": e.event_id,
          **{f: (getattr(e, f).isoformat() if isinstance(getattr(e, f), datetime) else getattr(e, f))
             for f in MATERIAL_FIELDS}}
         for e in a.evidence + a.incomplete),
        key=lambda x: (x["origin"], x["event_id"]),
    )


def describe_change(old: list[dict], new: list[dict]) -> str:
    o = {(x["origin"], x["event_id"]): x for x in old}
    n = {(x["origin"], x["event_id"]): x for x in new}
    parts = []
    for k in sorted(o.keys() - n.keys()):
        parts.append(f"{k[1]} ({k[0]}) no longer applies")
    for k in sorted(n.keys() - o.keys()):
        parts.append(f"{k[1]} ({k[0]}) newly applies")
    for k in sorted(o.keys() & n.keys()):
        changed = [f for f in MATERIAL_FIELDS if o[k][f] != n[k][f]]
        if changed:
            parts.append(f"{k[1]} ({k[0]}) changed: {', '.join(changed)}")
    return "; ".join(parts) or "evidence changed"
