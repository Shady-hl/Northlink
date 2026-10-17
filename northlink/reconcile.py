"""Import with integrity checks, duplicate handling and review reopening.

Identity rules (from the brief):
- Same packet_id + same canonical content -> duplicate, no-op (no audit entry).
- Same packet_id + different content      -> IntegrityError, nothing written.
- Same (origin, event_id, revision) + different payload -> IntegrityError.
- Authority is version order (highest revision), never arrival order, so a
  late-arriving older revision cannot revive a cancelled event.
- Coverage rows are appended; freshness uses the newest *successful*
  source_retrieved_at, so an old file never renews a source clock.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import store
from .impact import assess, describe_change, material_fingerprint
from .models import DeliveryPlan, Packet, canonical, content_hash


class IntegrityError(Exception):
    """Reused identifier with different content. State is unchanged."""


@dataclass
class ImportResult:
    packet_id: str
    duplicate: bool = False
    new_events: list[str] = field(default_factory=list)
    already_known_events: list[str] = field(default_factory=list)
    coverage_rows: int = 0
    reopened: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.duplicate:
            return f"Packet {self.packet_id} was already imported with identical content; nothing changed."
        s = f"Imported {self.packet_id}: {len(self.new_events)} new event revision(s)"
        if self.already_known_events:
            s += f", {len(self.already_known_events)} already known"
        s += f", {self.coverage_rows} coverage record(s)."
        if self.reopened:
            s += f" Reopened review(s): {', '.join(self.reopened)}."
        if self.warnings:
            s += " Warnings: " + "; ".join(self.warnings)
        return s


def _check_packet(conn, p: Packet) -> tuple[bool, list, list]:
    """Return (is_duplicate, new_events, known_events) or raise IntegrityError."""
    row = conn.execute("SELECT canonical FROM packets WHERE packet_id=?", (p.packet_id,)).fetchone()
    if row is not None:
        if row[0] == canonical(p):
            return True, [], []
        raise IntegrityError(
            f"Packet ID '{p.packet_id}' was already imported with different content. "
            "A changed packet needs a new packet ID; nothing was imported.")
    new, known = [], []
    for e in p.events:
        r = conn.execute("SELECT content_hash, packet_id FROM events WHERE origin=? AND event_id=? AND revision=?",
                         (e.origin, e.event_id, e.revision)).fetchone()
        if r is None:
            new.append(e)
        elif r[0] == content_hash(e):
            known.append(e)
        else:
            raise IntegrityError(
                f"Event {e.origin}/{e.event_id} revision {e.revision} already exists (from packet "
                f"{r[1]}) with a different payload. A changed event needs a new revision; nothing was imported.")
    return False, new, known


def import_packet(conn, p: Packet, *, from_connector: bool = False) -> ImportResult:
    with store.transaction(conn):
        return import_packet_tx(conn, p, from_connector=from_connector)


def import_packet_tx(conn, p: Packet, *, from_connector: bool = False) -> ImportResult:
    """Caller holds a transaction. Files cannot claim to be live: only a
    connector may create a 'live' packet."""
    if p.kind == "live" and not from_connector:
        raise IntegrityError(f"Packet {p.packet_id} declares kind 'live' but was imported from a file. "
                             "Use kind 'recorded' for saved real-source data; nothing was imported.")
    dup, new, known = _check_packet(conn, p)
    res = ImportResult(p.packet_id, duplicate=dup)
    if dup:
        return res
    wall = store.iso(store.now_wall())
    conn.execute("INSERT INTO packets VALUES (?,?,?,?,?,?,?)",
                 (p.packet_id, p.kind, p.label, store.iso(p.retrieved_at), wall,
                  canonical(p), content_hash(p)))
    for e in new:
        conn.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?)",
                     (e.origin, e.event_id, e.revision, p.packet_id, canonical(e), content_hash(e), wall))
    for c in p.coverage:
        conn.execute("INSERT INTO coverage (packet_id, origin, scope_id, source_retrieved_at, successful, imported_at) "
                     "VALUES (?,?,?,?,?,?)",
                     (p.packet_id, c.origin, c.scope_id, store.iso(c.source_retrieved_at), int(c.successful), wall))
    for e in new:
        if e.supersedes_revision is not None and conn.execute(
                "SELECT 1 FROM events WHERE origin=? AND event_id=? AND revision=?",
                (e.origin, e.event_id, e.supersedes_revision)).fetchone() is None:
            res.warnings.append(f"{e.event_id} r{e.revision} supersedes r{e.supersedes_revision}, "
                                "which has not been imported")
    res.new_events = [f"{e.event_id} r{e.revision}" for e in new]
    res.already_known_events = [f"{e.event_id} r{e.revision}" for e in known]
    res.coverage_rows = len(p.coverage)
    store.audit(conn, "packet_imported", p.packet_id,
                {"kind": p.kind, "new_events": res.new_events, "known_events": res.already_known_events,
                 "coverage_rows": res.coverage_rows, "warnings": res.warnings})
    res.reopened = reevaluate_reviews(conn)
    return res


def import_plan(conn, plan: DeliveryPlan) -> bool:
    """Returns False for an identical duplicate. Raises IntegrityError for a
    changed plan under a reused ID or a delivery ID owned by another plan."""
    with store.transaction(conn):
        return import_plan_tx(conn, plan)


def import_plan_tx(conn, plan: DeliveryPlan) -> bool:
    """Caller holds a transaction."""
    row = conn.execute("SELECT canonical FROM plans WHERE plan_id=?", (plan.plan_id,)).fetchone()
    if row is not None:
        if row[0] == canonical(plan):
            return False
        raise IntegrityError(f"Plan ID '{plan.plan_id}' was already imported with different content; nothing was imported.")
    for d in plan.deliveries:
        r = conn.execute("SELECT plan_id FROM deliveries WHERE delivery_id=?", (d.delivery_id,)).fetchone()
        if r is not None:
            raise IntegrityError(f"Delivery {d.delivery_id} already belongs to plan {r[0]}; nothing was imported.")
    wall = store.iso(store.now_wall())
    conn.execute("INSERT INTO plans VALUES (?,?,?,?,?,?)",
                 (plan.plan_id, plan.kind, plan.label, canonical(plan), content_hash(plan), wall))
    for d in plan.deliveries:
        conn.execute("INSERT INTO deliveries VALUES (?,?,?)", (d.delivery_id, plan.plan_id, canonical(d)))
    store.audit(conn, "plan_imported", plan.plan_id, {"deliveries": [d.delivery_id for d in plan.deliveries]})
    return True


def reevaluate_reviews(conn) -> list[str]:
    """Reopen reviewed cases whose material evidence changed. Caller holds a
    transaction. A case already reopened is not reopened again; staleness
    alone never reopens (it is shown as a flag instead)."""
    now = store.scenario_time(conn)
    events, cov = store.all_events(conn), store.all_coverage(conn)
    dels = {d.delivery_id: d for d in store.deliveries(conn)}
    reopened = []
    for did, case in store.review_cases(conn).items():
        if case["state"] != "reviewed" or did not in dels:
            continue
        rv = store.review(conn, case["current_review_id"])
        old = json.loads(rv["fingerprint"])
        new = material_fingerprint(assess(dels[did], events, cov, now))
        if old != new:
            reason = describe_change(old, new)
            conn.execute("UPDATE review_cases SET state='reopened', reopened_reason=?, updated_wall=?, "
                         "updated_scenario=? WHERE delivery_id=?",
                         (reason, store.iso(store.now_wall()), store.iso(now), did))
            store.audit(conn, "review_reopened", did, {"review_id": rv["review_id"], "reason": reason})
            reopened.append(did)
    return reopened
