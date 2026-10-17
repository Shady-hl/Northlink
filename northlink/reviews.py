"""Human review decisions and the persisted scenario clock."""
from __future__ import annotations

import json
from datetime import datetime

from . import store
from .impact import assess, material_fingerprint
from .models import ReviewInput
from .reconcile import reevaluate_reviews


def save_review(conn, inp: ReviewInput) -> str:
    """Record a decision against the exact evidence versions currently shown.
    Previous reviews are never modified; the new one links to its predecessor."""
    with store.transaction(conn):
        dels = {d.delivery_id: d for d in store.deliveries(conn)}
        if inp.delivery_id not in dels:
            raise ValueError(f"Unknown delivery {inp.delivery_id}")
        now = store.scenario_time(conn)
        a = assess(dels[inp.delivery_id], store.all_events(conn), store.all_coverage(conn), now)
        hashes = store.event_hashes(conn)
        evidence = [{"origin": e.origin, "event_id": e.event_id, "revision": e.revision,
                     "content_hash": hashes[(e.origin, e.event_id, e.revision)]}
                    for e in a.evidence + a.incomplete]
        case = store.review_case(conn, inp.delivery_id)
        prev = case["current_review_id"] if case else None
        rid = store.next_review_id(conn)
        wall = store.iso(store.now_wall())
        conn.execute(
            "INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, inp.delivery_id, inp.person, inp.decision, inp.note, wall, store.iso(now),
             a.category, json.dumps(evidence), json.dumps(material_fingerprint(a)),
             json.dumps(a.stale_reasons), prev))
        conn.execute(
            "INSERT INTO review_cases VALUES (?, 'reviewed', ?, NULL, ?, ?) "
            "ON CONFLICT(delivery_id) DO UPDATE SET state='reviewed', current_review_id=excluded.current_review_id, "
            "reopened_reason=NULL, updated_wall=excluded.updated_wall, updated_scenario=excluded.updated_scenario",
            (inp.delivery_id, rid, wall, store.iso(now)))
        store.audit(conn, "review_saved", inp.delivery_id,
                    {"review_id": rid, "decision": inp.decision, "person": inp.person,
                     "previous_review_id": prev, "evidence": evidence})
        return rid


def set_clock(conn, t: datetime) -> list[str]:
    """Move the replay clock (forward or back). Applicability can change when an
    event's validity ends, so reviews are re-evaluated; staleness alone never
    reopens a review."""
    with store.transaction(conn):
        store.set_scenario_time_tx(conn, t)
        return reevaluate_reviews(conn)
