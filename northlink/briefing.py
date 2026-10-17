"""Deterministic, evidence-linked Markdown briefing. No model or network calls."""
from __future__ import annotations

import json

from . import store
from .impact import CATEGORIES, assess


def build(conn, by: str = "Coordinator") -> str:
    now = store.scenario_time(conn)
    events, coverage = store.all_events(conn), store.all_coverage(conn)
    cases = store.review_cases(conn)
    kinds = sorted({r["kind"] for r in store.packets(conn)})
    lines = ["# Northlink · Situation handover", "",
             f"Prepared by: {by}", f"Scenario time: {store.iso(now)}",
             f"Exported at: {store.iso(store.now_wall())} (actual wall clock)",
             "Mode: deterministic template; no AI-generated factual claims.",
             f"Evidence modes: {', '.join(kinds) or 'no packets'}. Delivery plans may be fictional.", "",
             "Decision support only. No matching record is not an all-clear or a route-safety assessment.",
             "Archived weather is a replay; no historical polling coverage is claimed.", ""]
    deliveries = store.deliveries(conn)
    if not deliveries:
        lines.append("No delivery plan loaded.")
    for d in deliveries:
        a = assess(d, events, coverage, now)
        c = cases.get(d.delivery_id)
        lines.extend([f"## {d.delivery_id} · {CATEGORIES[a.category]}", "",
                      f"Scope: {d.corridor_id}; window: {store.iso(d.window_start)} → {store.iso(d.window_end)}.",
                      f"Priority: {d.priority}. Review: {c['state'] if c else 'not reviewed'}.", "",
                      "Facts and applicability:", *[f"- {r}" for r in a.reasons]])
        lines.extend(["", "Uncertainty:", *[f"- {r}" for r in a.stale_reasons + a.gap_reasons]])
        if not a.stale_reasons and not a.gap_reasons:
            lines.append("- No stale/missing flag under the configured policy; this is not proof of safety.")
        if c:
            rv = store.review(conn, c["current_review_id"])
            lines.extend(["", f"Human decision: {rv['decision']} — {rv['person']} ({rv['review_id']}).",
                          f"Decision note (human supplied): {rv['note'] or '(none)'}"])
            if c["state"] == "reopened":
                lines.append(f"Reconsideration required: {c['reopened_reason']}.")
        if a.category == "conflict" or a.stale or a.missing_origins:
            lines.extend(["", "Suggested review action: confirm the disputed or missing information with its source."])
        else:
            lines.extend(["", "Suggested review action: inspect supporting records and record a human decision."])
        lines.extend(["", "Supporting source records:"])
        for e in a.evidence + a.incomplete:
            lines.append(f"- {e.origin}/{e.event_id} r{e.revision}; published {store.iso(e.published_at)}. "
                         f"Source: {e.source_url or 'synthetic record; no official URL'}")
        if not a.evidence and not a.incomplete:
            lines.append("- No currently matching record; prior decisions remain in history.")
        history = store.review_history(conn, d.delivery_id)
        if history:
            lines.extend(["", "Retained decision history:"])
            for rv in history:
                refs = [f"{x['event_id']} r{x['revision']}" for x in json.loads(rv["evidence"])]
                lines.append(f"- {rv['review_id']} · {rv['decision']} · scenario {rv['scenario_time']} · "
                             f"recorded {rv['created_wall']} · evidence: {', '.join(refs) or 'none'}.")
        lines.append("")
    lines.extend(["---", "Portable JSON handovers include source-event records and reviews. "
                  "The separately cached live MET responses are not embedded. Bundled historical "
                  "CAP/GeoJSON files travel with the application release.", ""])
    return "\n".join(lines)
