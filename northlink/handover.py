"""Offline handover export/import (local JSON snapshot, no network).

Export contains the raw source packets and plans (canonical form, so their
content hashes can be re-checked), the full review history, review case
states, audit log, the scenario clock, and a human-readable assessment
summary including stale flags.

Import:
- Into an empty database: full restore (round trip preserves history).
- Into a non-empty database: packets/plans are merged under the normal
  integrity rules; the other laptop's reviews are stored as *foreign* reviews
  for display only. The local presenter laptop stays authoritative; no
  automatic consensus is claimed.
"""
from __future__ import annotations

import json

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator, model_validator

from . import store
from .impact import CATEGORIES, assess
from .models import DECISIONS, DeliveryPlan, EventType, NonEmpty, Packet, content_hash
from .reconcile import import_packet_tx, import_plan_tx

FORMAT = "northlink-handover"
VERSION = 1

def _rows(conn, sql) -> list[dict]:
    return [dict(r) for r in conn.execute(sql)]


def export(conn, exported_by: str = "") -> dict:
    now = store.scenario_time(conn)
    events, cov = store.all_events(conn), store.all_coverage(conn)
    cases = store.review_cases(conn)
    summary = []
    for d in store.deliveries(conn):
        a = assess(d, events, cov, now)
        c = cases.get(d.delivery_id)
        summary.append({
            "delivery_id": d.delivery_id, "corridor_id": d.corridor_id,
            "assessment": CATEGORIES[a.category], "reasons": a.reasons,
            "evidence": [f"{e.origin}/{e.event_id} r{e.revision}" for e in a.evidence],
            "evidence_stale_recheck": a.stale, "stale_reasons": a.stale_reasons, "coverage_gaps": a.gap_reasons,
            "review_state": c["state"] if c else "open",
            "current_review_id": c["current_review_id"] if c else None,
            "reopened_reason": c["reopened_reason"] if c else None,
        })
    body = {
        "format": FORMAT, "version": VERSION,
        "exported_wall": store.iso(store.now_wall()), "exported_by": exported_by,
        "scenario_time": store.iso(now),
        "notice": "Decision-support snapshot. Synthetic records are labelled by packet kind. "
                  "'No matching records' is not a route-safety assessment.",
        "summary": summary,
        "packets": [json.loads(r["canonical"]) for r in _rows(conn, "SELECT canonical FROM packets ORDER BY imported_at, packet_id")],
        "packet_imports": _rows(conn, "SELECT packet_id, imported_at FROM packets ORDER BY imported_at, packet_id"),
        "plans": [json.loads(r["canonical"]) for r in _rows(conn, "SELECT canonical FROM plans ORDER BY plan_id")],
        "plan_imports": _rows(conn, "SELECT plan_id, imported_at FROM plans ORDER BY plan_id"),
        "reviews": _rows(conn, "SELECT * FROM reviews ORDER BY created_wall, review_id"),
        "foreign_reviews": _rows(conn, "SELECT * FROM foreign_reviews ORDER BY handover_id, review_id"),
        "review_cases": _rows(conn, "SELECT * FROM review_cases ORDER BY delivery_id"),
        "audit": _rows(conn, "SELECT * FROM audit ORDER BY id"),
    }
    body["handover_id"] = "H-" + content_hash_dict(body)[:12]
    return body


def content_hash_dict(d: dict) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


REVIEW_COLS = ("review_id", "delivery_id", "person", "decision", "note", "created_wall", "scenario_time",
               "category", "evidence", "fingerprint", "stale_at_review", "previous_review_id")
CASE_COLS = ("delivery_id", "state", "current_review_id", "reopened_reason", "updated_wall", "updated_scenario")


def _json_text(v: str, kind: type) -> str:
    if not isinstance(json.loads(v), kind):
        raise ValueError(f"must be a JSON {kind.__name__}")
    return v


def _ts(v: str) -> str:
    if store.parse(v).utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return v


class _Row(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceRow(_Row):
    origin: NonEmpty
    event_id: NonEmpty
    revision: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class FingerprintRow(_Row):
    origin: NonEmpty
    event_id: NonEmpty
    status: Literal["active", "cancelled"]
    corridor_id: str | None
    valid_from: str | None
    valid_until: str | None
    event_type: EventType
    claim_key: str | None
    claim_value: str | None

    @field_validator("valid_from", "valid_until")
    @classmethod
    def _t(cls, v):
        return _ts(v) if v is not None else None


class ReviewRow(_Row):
    review_id: str = Field(pattern=r"^R[0-9]+$")
    delivery_id: str = Field(min_length=1)
    person: str = Field(min_length=1)
    decision: Literal[tuple(DECISIONS)]  # type: ignore[valid-type]
    note: str
    created_wall: str
    scenario_time: str
    category: Literal[tuple(CATEGORIES)]  # type: ignore[valid-type]
    evidence: str
    fingerprint: str
    stale_at_review: str
    previous_review_id: str | None

    @field_validator("created_wall", "scenario_time")
    @classmethod
    def _t(cls, v):
        return _ts(v)

    @field_validator("evidence")
    @classmethod
    def _e(cls, v):
        TypeAdapter(list[EvidenceRow]).validate_json(v)
        return v

    @field_validator("fingerprint")
    @classmethod
    def _f(cls, v):
        TypeAdapter(list[FingerprintRow]).validate_json(v)
        return v

    @field_validator("stale_at_review")
    @classmethod
    def _s(cls, v):
        TypeAdapter(list[str]).validate_json(v)
        return v


class ForeignReviewRow(_Row):
    handover_id: NonEmpty
    review_id: str
    delivery_id: str
    payload: str
    imported_at: str

    @field_validator("imported_at")
    @classmethod
    def _t(cls, v):
        return _ts(v)

    @model_validator(mode="after")
    def _payload(self):
        review = ReviewRow.model_validate_json(self.payload)
        if (review.review_id, review.delivery_id) != (self.review_id, self.delivery_id):
            raise ValueError("foreign review identity disagrees with its payload")
        return self


class CaseRow(_Row):
    delivery_id: str = Field(min_length=1)
    state: Literal["reviewed", "reopened"]
    current_review_id: str
    reopened_reason: str | None
    updated_wall: str
    updated_scenario: str

    @field_validator("updated_wall", "updated_scenario")
    @classmethod
    def _t(cls, v):
        return _ts(v)


class AuditRow(BaseModel):
    model_config = ConfigDict(extra="ignore")  # 'id' is reassigned locally
    wall_time: str
    scenario_time: str
    action: str
    subject: str | None
    detail: str

    @field_validator("wall_time", "scenario_time")
    @classmethod
    def _t(cls, v):
        return _ts(v)

    @field_validator("detail")
    @classmethod
    def _j(cls, v):
        return _json_text(v, dict)


class Handover(BaseModel):
    model_config = ConfigDict(extra="ignore")
    format: Literal["northlink-handover"]
    version: Literal[1]
    handover_id: str = "H-unknown"
    scenario_time: str
    packets: list[Packet]
    packet_imports: list[dict] = []
    plans: list[DeliveryPlan]
    plan_imports: list[dict] = []
    reviews: list[ReviewRow]
    foreign_reviews: list[ForeignReviewRow] = []
    review_cases: list[CaseRow]
    audit: list[AuditRow]

    @field_validator("scenario_time")
    @classmethod
    def _t(cls, v):
        return _ts(v)

    @model_validator(mode="after")
    def _refs(self):
        ids = [r.review_id for r in self.reviews]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate review_id in handover")
        known = set(ids)
        by_id = {r.review_id: r for r in self.reviews}
        deliveries = {d.delivery_id for p in self.plans for d in p.deliveries}
        events = {(e.origin, e.event_id, e.revision): e for p in self.packets for e in p.events}
        for r in self.reviews + [ReviewRow.model_validate_json(f.payload) for f in self.foreign_reviews]:
            if r.delivery_id not in deliveries:
                raise ValueError(f"review {r.review_id} references unknown delivery")
            for evidence in TypeAdapter(list[EvidenceRow]).validate_json(r.evidence):
                event = events.get((evidence.origin, evidence.event_id, evidence.revision))
                if event is None or content_hash(event) != evidence.content_hash:
                    raise ValueError(f"review {r.review_id} references missing or changed evidence")
        for r in self.reviews:
            if r.previous_review_id is not None and r.previous_review_id not in known:
                raise ValueError(f"review {r.review_id} references unknown previous review")
            seen = {r.review_id}
            prev = r.previous_review_id
            while prev is not None:
                if prev in seen or by_id[prev].delivery_id != r.delivery_id:
                    raise ValueError("invalid review history chain")
                seen.add(prev)
                prev = by_id[prev].previous_review_id
                if prev is not None and prev not in known:
                    raise ValueError("review history references unknown previous review")
        if len({c.delivery_id for c in self.review_cases}) != len(self.review_cases):
            raise ValueError("duplicate delivery case in handover")
        for c in self.review_cases:
            if c.current_review_id not in known:
                raise ValueError(f"case {c.delivery_id} references unknown review {c.current_review_id}")
            if by_id[c.current_review_id].delivery_id != c.delivery_id:
                raise ValueError("case and review refer to different deliveries")
        return self


def _is_empty(conn) -> bool:
    """Restore only into a database with no imported data or decisions.
    Audit rows are never deleted, so a clock-only database is still 'empty'."""
    return all(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0
               for t in ("packets", "plans", "reviews", "review_cases"))


def import_handover(conn, data: dict) -> str:
    """Validate everything first, then write in one transaction with fixed columns."""
    try:
        h = Handover.model_validate(data)
    except ValidationError as exc:
        e = exc.errors()[0]
        loc = ".".join(str(x) for x in e["loc"])
        raise ValueError(f"Invalid handover file ({len(exc.errors())} problem(s)); first: {loc}: "
                         f"{e['msg'].removeprefix('Value error, ')}. Nothing was imported.") from exc
    hid = h.handover_id
    with store.transaction(conn):
        restore = _is_empty(conn)
        plan_at = {r.get("plan_id"): r.get("imported_at") for r in h.plan_imports}
        for pl in h.plans:
            import_plan_tx(conn, pl)
            if restore and plan_at.get(pl.plan_id):
                conn.execute("UPDATE plans SET imported_at=? WHERE plan_id=?", (_ts(plan_at[pl.plan_id]), pl.plan_id))
        pkt_at = {r.get("packet_id"): r.get("imported_at") for r in h.packet_imports}
        for p in h.packets:
            import_packet_tx(conn, p, from_connector=True)  # already validated once; may be live
            if restore and pkt_at.get(p.packet_id):
                t = _ts(pkt_at[p.packet_id])
                for tbl in ("packets", "events", "coverage"):
                    conn.execute(f"UPDATE {tbl} SET imported_at=? WHERE packet_id=?", (t, p.packet_id))
        if restore:
            # A single wall-clock second may contain R1 through R10. Lexical
            # ordering puts R10 before R2; insert parents before their children.
            pending = {r.review_id: r for r in h.reviews}
            ordered = []
            while pending:
                ready = [r for r in pending.values() if r.previous_review_id not in pending]
                for r in ready:
                    ordered.append(r)
                    del pending[r.review_id]
            for r in ordered:
                conn.execute(f"INSERT INTO reviews ({','.join(REVIEW_COLS)}) VALUES ({','.join('?' * len(REVIEW_COLS))})",
                             tuple(getattr(r, c) for c in REVIEW_COLS))
            for f in h.foreign_reviews:
                _merge_foreign(conn, f.handover_id, ReviewRow.model_validate_json(f.payload), f.imported_at)
            for c in h.review_cases:
                conn.execute(f"INSERT INTO review_cases ({','.join(CASE_COLS)}) VALUES ({','.join('?' * len(CASE_COLS))})",
                             tuple(getattr(c, k) for k in CASE_COLS))
            # Local audit rows are kept; the exported log is appended after them.
            for a in h.audit:
                conn.execute("INSERT INTO audit (wall_time, scenario_time, action, subject, detail) VALUES (?,?,?,?,?)",
                             (a.wall_time, a.scenario_time, a.action, a.subject, a.detail))
            conn.execute("UPDATE meta SET value=? WHERE key='scenario_time'", (h.scenario_time,))
            store.audit(conn, "handover_restored", hid, {"reviews": len(h.reviews)})
            return f"Restored handover {hid}: {len(h.packets)} packet(s), {len(h.reviews)} review(s), clock {h.scenario_time}."
        n = 0
        for r in h.reviews:
            n += _merge_foreign(conn, hid, r)
        for f in h.foreign_reviews:
            n += _merge_foreign(conn, f.handover_id, ReviewRow.model_validate_json(f.payload), f.imported_at)
        if n:
            store.audit(conn, "handover_merged", hid, {"foreign_reviews": n})
        return (f"Merged handover {hid}: packets checked under integrity rules; {n} new review(s) from the other "
                "laptop stored for comparison only (local reviews unchanged).")


def _merge_foreign(conn, hid: str, r: ReviewRow, imported_at: str | None = None) -> int:
    payload = json.dumps(r.model_dump(), sort_keys=True)
    local = store.review(conn, r.review_id)
    if local is not None and json.dumps(dict(local), sort_keys=True) == payload:
        return 0
    if conn.execute("SELECT 1 FROM foreign_reviews WHERE review_id=? AND payload=?",
                    (r.review_id, payload)).fetchone():
        return 0
    existing = conn.execute("SELECT 1 FROM foreign_reviews WHERE handover_id=? AND review_id=?",
                            (hid, r.review_id)).fetchone()
    if existing:
        raise ValueError("Foreign review identity reused with changed content; nothing was imported")
    conn.execute("INSERT INTO foreign_reviews VALUES (?,?,?,?,?)",
                 (hid, r.review_id, r.delivery_id, payload, imported_at or store.iso(store.now_wall())))
    return 1


def foreign_reviews(conn, delivery_id: str) -> list[dict]:
    return [dict(json.loads(r[0]), handover_id=r[1]) for r in conn.execute(
        "SELECT payload, handover_id FROM foreign_reviews WHERE delivery_id=? ORDER BY handover_id, review_id",
        (delivery_id,))]
