"""Northlink - evidence-linked delivery review workspace (decision support only).

Run: .venv/bin/streamlit run app.py
Starts without any network access; the MET connector only fetches when its
Refresh button is pressed.
"""
from __future__ import annotations

import json
import html
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

import pandas as pd
import streamlit as st

from northlink import briefing, changes, handover, mapview, replay, report_ui, store, visuals, topomap, deskview
from northlink.connectors import met
from northlink.impact import ATTENTION, CATEGORIES, assess
from northlink.loader import SCENARIO_DIR, InputError, load_file, parse_any
from northlink.models import DECISIONS, DeliveryPlan, Packet, ReviewInput
from northlink.reconcile import IntegrityError, import_packet, import_plan
from northlink.reviews import save_review, set_clock
from northlink import workspace as workspace_guard

st.set_page_config(page_title="Northlink · Review desk", layout="wide", page_icon="◈", initial_sidebar_state="collapsed")
st.markdown(visuals.STYLE, unsafe_allow_html=True)

BADGE = {"conflict": "◆ Sources disagree", "restriction": "■ Restriction reported", "advisory": "▲ Potential weather impact",
         "needs_confirmation": "● Needs confirmation", "no_match": "○ No match (not a safety assessment)"}
STATE = {"open": "Open - not reviewed", "reviewed": "Reviewed", "reopened": "REOPENED - evidence changed"}


@st.cache_resource
def get_conn(path: str):
    return store.connect(path)


with st.container(key="desk-header"):
    brand_col, workspace_col, local_col = st.columns([1.6, 1.5, 1.2], vertical_alignment="center")
    brand_col.markdown('<div class="desk-brand">◈ NORTHLINK <span>REVIEW DESK</span></div>', unsafe_allow_html=True)
    with workspace_col:
        workspace = st.selectbox("Workspace", ["Synthetic exercise", "Finnmark · recorded weather"], key="workspace", label_visibility="collapsed")
    local_col.markdown('<div class="desk-local">LOCAL WORKSPACE <span>Evidence · decisions · handover</span></div>', unsafe_allow_html=True)
recorded = workspace.startswith("Finnmark")
run_key = "run_id_finnmark" if recorded else "run_id_synthetic"
run_id = st.session_state.get(run_key)
base = Path(store.DEFAULT_DB)
suffix = ("-finnmark" if recorded else "") + (f"-practice-{run_id}" if run_id else "")
conn = get_conn(str(base.with_name(base.stem + suffix + base.suffix)))


def flash(kind: str, msg: str):
    st.session_state.setdefault("flash", []).append((kind, msg))


def do_import(obj, source: str):
    """Single UI import path; workspace isolation is enforced before any write."""
    level, message = workspace_guard.guarded_import(
        conn, obj, workspace_guard.FINNMARK if recorded else workspace_guard.SYNTHETIC, source)
    flash(level, message)


def prepare_run():
    if recorded:
        if replay.prepare(conn):
            flash("success", "Recorded Finnmark exercise loaded (6 fictional deliveries, initial MET polar-low Alert).")
        else:
            flash("info", "Recorded Finnmark exercise already loaded; existing decisions preserved. Use 'New practice run' to replay from the beginning.")
    else:
        for name in ("deliveries.json", "packet_A.json"):
            do_import(load_file(SCENARIO_DIR / name), name)


if st.session_state.pop("prepare_run", False):
    prepare_run()


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.subheader("Exercise setup & files")
    st.caption("Decision support only. Does not dispatch vehicles or certify routes as safe.")
    st.session_state.setdefault("person", "Coordinator")
    st.text_input("Your name / role label", key="person")

    if st.button("New practice run", width="stretch"):
        st.session_state[run_key] = uuid.uuid4().hex[:8]
        st.session_state.prepare_run = True
        st.rerun()
    if run_id and st.button("Return to persistent workspace", width="stretch"):
        st.session_state.pop(run_key, None)
        st.rerun()
    st.caption("Practice runs preserve all earlier data. Recorded replay has its own workspace. Clock changes retain imported notices; use a new run to replay from the beginning.")
    st.subheader("Scenario clock")
    now = store.scenario_time(conn)
    st.markdown(f"**Scenario time:** `{now:%Y-%m-%d %H:%M}Z`  \n"
                f"Wall clock: `{datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z` (separate)")
    c1, c2, c3 = st.columns(3)
    for col, mins in ((c1, 5), (c2, 15), (c3, 60)):
        if col.button(f"+{mins}m", width="stretch"):
            r = set_clock(conn, now + timedelta(minutes=mins))
            if r:
                flash("warning", f"Reopened after clock change: {', '.join(r)}")
            st.rerun()
    if st.session_state.get("last_clock") != store.iso(now):
        st.session_state.clock_text = f"{now:%H:%M}"
        st.session_state.last_clock = store.iso(now)
    with st.form("clock"):
        t = st.text_input("Set scenario time (HH:MM, UTC, on scenario date)", key="clock_text")
        if st.form_submit_button("Set"):
            try:
                h, m = (int(x) for x in t.split(":"))
                r = set_clock(conn, now.replace(hour=h, minute=m, second=0))
                if r:
                    flash("warning", f"Reopened after clock change: {', '.join(r)}")
                st.rerun()
            except ValueError:
                st.error("Use HH:MM, e.g. 12:40")

    if recorded:
        if st.button("Load recorded Finnmark exercise", type="primary", width="stretch"):
            prepare_run()
            st.rerun()
        known = {r["packet_id"] for r in store.packets(conn)}
        for index in (1, 2):
            if st.button(f"Import archived update {index}", width="stretch",
                         disabled=not store.deliveries(conn) or replay.packet(index).packet_id in known):
                result = replay.advance(conn, index)
                flash("success", f"Recorded update {index} imported. " +
                      ("Reopened: " + ", ".join(result.reopened) if result.reopened else "No reviewed assessment materially changed."))
                st.rerun()
        st.caption("Buttons advance historical replay time. No live fetch is made.")
    else:
        if st.button("Load demo plan + packet A", type="primary", width="stretch"):
            prepare_run()
            st.rerun()
        if st.button("Import correction · packet B", width="stretch", disabled=not store.deliveries(conn)):
            target = store.DEFAULT_SCENARIO_START.replace(hour=12, minute=46)
            if store.scenario_time(conn) < target:
                set_clock(conn, target)
            do_import(load_file(SCENARIO_DIR / "packet_B.json"), "packet_B.json")
            st.rerun()
    with st.expander("Import a local file"):
        if not recorded:
            demo_files = sorted(p.name for p in SCENARIO_DIR.glob("*.json"))
            pick = st.selectbox("Bundled synthetic file", demo_files, index=None, placeholder="Choose file")
            if pick and st.button(f"Import {pick}", width="stretch"):
                try:
                    if pick == "packet_late_E2r1.json":
                        target = store.DEFAULT_SCENARIO_START.replace(hour=12, minute=48)
                        if store.scenario_time(conn) < target:
                            set_clock(conn, target)
                    do_import(load_file(SCENARIO_DIR / pick), pick)
                except InputError as exc:
                    flash("error", str(exc))
                st.rerun()
        else:
            st.caption("Bundled synthetic files apply to the Synthetic exercise workspace.")
        up = st.file_uploader("Packet, plan or handover (.json)", type="json")
        if up is not None and st.button("Import uploaded file", width="stretch"):
            try:
                do_import(parse_any(up.getvalue(), up.name), up.name)
            except InputError as exc:
                flash("error", f"{exc.source} rejected, nothing changed:\n" + "\n".join(f"- {p}" for p in exc.problems))
            st.rerun()

    st.subheader("Handover")
    st.download_button("Export handover (JSON, offline)",
                       data=json.dumps(handover.export(conn, st.session_state.person), indent=2),
                       file_name=f"northlink-handover-{now:%H%M}Z.json", mime="application/json",
                       width="stretch")

    st.download_button("Download situation brief", data=briefing.build(conn, st.session_state.person),
                       file_name=f"northlink-brief-{now:%Y%m%d-%H%M}Z.md", mime="text/markdown", width="stretch")
    st.caption("Local core; no connection test at startup. Live refresh needs internet.")

# ---------------------------------------------------------------- main
for kind, msg in st.session_state.pop("flash", []):
    getattr(st, kind)(msg)

dels = store.deliveries(conn)
if not dels:
    st.info("Choose a workspace and load its exercise from the sidebar. Existing decisions are preserved.")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("01 · Outage and conflicting reports")
        st.write("Six fictional deliveries. A restriction, a disagreement, stale evidence and a correction. Prove decision continuity.")
    with c2:
        st.subheader("02 · Real weather, recorded replay")
        st.write("An archived MET polar-low warning in Eastern Finnmark. A verified update changes potential exposure for a fictional delivery.")
    st.stop()

events, cov = store.all_events(conn), store.all_coverage(conn)
kinds = store.event_packet_kind(conn)
cases = store.review_cases(conn)
assessments = {d.delivery_id: assess(d, events, cov, now) for d in dels}
plan_kinds = {r["kind"] for r in store.plans(conn)}
pkt_kinds = {r["kind"] for r in store.packets(conn)}

mode_label = "RECORDED WEATHER · FICTIONAL DELIVERIES" if recorded else "SYNTHETIC EXERCISE · FICTIONAL SOURCES & CORRIDORS"
st.markdown(f'<div class="desk-mode"><span>{mode_label}</span><span>Scenario {now:%d %b %Y · %H:%M} UTC</span></div>', unsafe_allow_html=True)
if not recorded:
    with st.container(key="exercise-notice"):
        st.warning("**SYNTHETIC SCENARIO.** Deliveries, sources and corridors are fictional. Not a navigation map.")

def short_ref(e) -> str:
    """Readable record label; long CAP identifiers stay inspectable in Evidence detail."""
    return "MET warning" if e.origin == replay.ORIGIN else e.event_id


rows = []
order = list(CATEGORIES)
for d in dels:
    a = assessments[d.delivery_id]
    c = cases.get(d.delivery_id)
    state = c["state"] if c else "open"
    needs = a.category in ATTENTION or state == "reopened"
    rows.append({
        "Delivery": d.delivery_id, "Attention": "YES" if needs else "-",
        "Assessment": BADGE[a.category],
        "Evidence": ", ".join(f"{short_ref(e)} r{e.revision}" for e in a.evidence) or "-",
        "Freshness": ("⚠ Evidence stale - recheck" if a.stale else "See source ages / coverage policy")
                     + (f"; not checked: {', '.join(a.missing_origins)}" if a.missing_origins else ""),
        "Review": STATE[state] + (f" ({c['current_review_id']})" if c else ""),
        "Corridor": d.corridor_id, "Window (UTC)": f"{d.window_start:%H:%M}-{d.window_end:%H:%M}",
        "Priority": d.priority, "Deadline": f"{d.deadline:%H:%M}Z",
        "_sort": (not needs, state != "reopened", order.index(a.category), d.delivery_id),
    })
df = pd.DataFrame(rows).sort_values("_sort").drop(columns="_sort")
titles = replay.TITLES if recorded else {
    "D1": "Priority supplies · C1", "D2": "Essential supplies · C2", "D3": "Medical equipment · C3",
    "D4": "Evening supplies · C1", "D5": "Spare parts · C2", "D6": "Evening equipment · C3"}
def state_of(did):
    return cases[did]["state"] if did in cases else "open"
values = [sum(state_of(did) == "reopened" or (a.category in ATTENTION and state_of(did) != "reviewed") for did, a in assessments.items()),
          sum(a.category == "conflict" for a in assessments.values()),
          sum(c["state"] == "reopened" for c in cases.values()),
          sum(bool(a.missing_origins) for a in assessments.values())]
st.markdown('<div class="desk-counts">' + ''.join(
    f'<span><strong>{value}</strong> {label}</span>' for label, value in zip(
        ["to review", "conflicting", "reopened", "with coverage gaps"], values)) + '</div>', unsafe_allow_html=True)
ids = list(df["Delivery"])
inspect_key = "inspect_finnmark" if recorded else "inspect_synthetic"
map_key = "map_finnmark" if recorded else "map_synthetic"


def pick_from_map():
    """Map marker -> delivery selector. Runs before the rerun, so the selector shows it."""
    picked = (st.session_state.get(map_key) or {}).get("select")
    if picked in ids:
        st.session_state[inspect_key] = picked
        st.session_state.setdefault("selected_by_ws", {})[inspect_key] = picked
        st.session_state["toolbox-" + inspect_key] = "Review"


saved_sel = st.session_state.setdefault("selected_by_ws", {}).get(inspect_key)
if st.session_state.get(inspect_key) not in ids:
    st.session_state[inspect_key] = saved_sel if saved_sel in ids else ids[0]
sel = st.session_state[inspect_key]
st.session_state["selected_by_ws"][inspect_key] = sel
a = assessments[sel]
d = a.delivery
case = cases.get(sel)

PLAIN = {"conflict": "Sources disagree", "restriction": "Restriction reported", "advisory": "Potential weather impact",
         "needs_confirmation": "Needs confirmation", "no_match": "No matching record (not an all-clear)"}
SHAPE = {"conflict": "◆", "restriction": "■", "advisory": "▲", "needs_confirmation": "●", "no_match": "○"}


def status_text(did: str) -> str:
    cat, state = assessments[did].category, state_of(did)
    review = {"open": "not reviewed", "reviewed": "reviewed", "reopened": "REOPENED"}[state]
    return f"{SHAPE[cat]} {PLAIN[cat]} · {review}"


def attention(did: str) -> bool:
    return state_of(did) == "reopened" or (assessments[did].category in ATTENTION and state_of(did) != "reviewed")


def next_action(did: str) -> str:
    x, state = assessments[did], state_of(did)
    if state == "reopened":
        return "Evidence used by the last decision changed. Compare the before/after below and record a new decision."
    if state == "reviewed":
        extra = " Evidence is stale: recheck the source before relying on it." if x.stale else ""
        return "Decision recorded. No action unless evidence changes." + extra
    if x.category == "no_match":
        return "No active record matches. Confirm coverage is adequate before treating this as routine; record a decision."
    return "Inspect the supporting record and record a human decision."


def plain_reason(x) -> str:
    """Readable first explanation, built from stored fields; technical IDs follow in Evidence detail."""
    if x.delivery.corridor_id.startswith("FN-") and x.evidence:
        e = x.evidence[0]
        return (f"The site is inside the recorded MET warning area, and the warning (valid {e.valid_from:%d %b %H:%M}–"
                f"{e.valid_until:%d %b %H:%M} UTC, revision {e.revision}) overlaps this delivery window.")
    if x.delivery.corridor_id.startswith("FN-") and x.category == "no_match":
        return ("No loaded warning revision both covers this site and overlaps this delivery window. "
                "This is not an all-clear.")
    return x.reasons[0]


groups: dict[str, list] = {}
for did in ids:
    item = assessments[did].delivery
    groups.setdefault(item.corridor_id, []).append({
        "id": did, "title": titles.get(did, item.corridor_id), "status": status_text(did), "attention": attention(did),
        "window": f"{item.window_start:%d %b %H:%M}–{item.window_end:%H:%M} UTC"})

loaded = {r["packet_id"] for r in store.packets(conn)}
if recorded:
    notices = replay.notices()
    shown_index = max((i for i in range(len(notices)) if replay.packet(i).packet_id in loaded), default=0)
    shown = notices[shown_index]
    previous = notices[shown_index - 1] if shown_index else None
    revision_label = ("Original alert" if shown_index == 0 else f"Update {shown_index}")
    sites = {k: {**v, "note": "Fictional exercise point · not a verified depot · "
                 + ("inside" if replay.contains(shown.geometry, v["lon"], v["lat"]) else "outside")
                 + " the shown warning polygon"} for k, v in replay.SITES.items()}
    map_data = visuals.recorded_map(
        shown.geometry, previous.geometry if previous else None, sites, groups, sel, d.corridor_id,
        f"Showing {revision_label.lower()} (revision {shown.revision} of {len(notices)}) · sent {shown.sent:%d %b %H:%M} UTC · "
        f"valid {shown.onset:%d %b %H:%M} → {shown.expires:%d %b %H:%M} UTC", map_key)
else:
    statuses = {scope: next((assessments[did].category for did in ids if assessments[did].delivery.corridor_id == scope
                             and assessments[did].category != "no_match"), "no_match") for scope in ("C1", "C2", "C3")}
    map_data = visuals.schematic_map(statuses, groups, sel, d.corridor_id, map_key)

event_rows_map = {(r["origin"], r["event_id"], r["revision"]): r for r in store.event_rows(conn)}
packet_meta = {r["packet_id"]: r for r in store.packets(conn)}

overview, review_tab, raw_tab, brief_tab, source_tab, intake_tab = st.tabs(
    ["Map & review", "Evidence detail", "Raw evidence", "Situation brief", "Sources & audit", "Report intake"],
    key="northlink-main-tabs", on_change="rerun")


def pick_delivery(did):
    if did in ids:
        st.session_state[inspect_key] = did
        st.session_state["selected_by_ws"][inspect_key] = did
        st.session_state["toolbox-" + inspect_key] = "Review"


def open_selected_review():
    st.session_state["northlink-main-tabs"] = "Map & review"
    st.session_state["toolbox-" + inspect_key] = "Review"


with overview:
    toolbox_col, map_col = st.columns([1, 2.8], gap="small")
    with toolbox_col, st.container(key="desk-toolbox"):
        st.markdown('<div class="toolbox-heading">Toolbox <span>LOCAL REVIEW</span></div>', unsafe_allow_html=True)
        queue_tab, detail_col, integrity_col = st.tabs(
            ["Deliveries", "Review", "Integrity"], key="toolbox-" + inspect_key, on_change="rerun")
    with queue_tab, st.container(key="delivery-queue"):
        deskview.queue(ids, assessments, cases, titles, sel, inspect_key, pick_delivery)
    with map_col:
        st.markdown('<div class="desk-section">' + ("Finnmark · recorded warning" if recorded else "Fictional corridor diagram") + '</div>', unsafe_allow_html=True)
        mapview.show(map_data, key=map_key, on_select=pick_from_map)
        st.caption("Site exposure only · fictional delivery points · not a navigation or route-safety assessment."
                   if recorded else "Fictional corridors and reports · not a navigation map.")
        if recorded:
            with st.expander("Map data & offline coverage"):
                pack = topomap.prepared()
                if pack["images"]:
                    st.write(f"**© Kartverket · topograatone · downloaded {pack['date']}**")
                    st.caption("Prepared locally: regional overview plus higher detail around the Varanger and Troms exercise points. "
                               "Roads, place names and terrain are part of the map image. This is a snapshot, not current road condition data. "
                               "The service does not supply a map revision date; download date is shown separately.")
                    st.dataframe(pd.DataFrame([{"Area": r["id"].capitalize(), "Source zoom": r["zoom"],
                                                "WGS84 bounds (west, south, east, north)": ", ".join(f"{n:.4f}" for n in r["bbox"])}
                                               for r in pack["images"]]), hide_index=True, width="stretch")
                    st.link_button("Kartverket map source", "https://cache.kartverket.no/")
                    st.link_button("Kartverket licence · CC BY 4.0", "https://www.kartverket.no/api-og-data/vilkar-for-bruk")
                else:
                    st.warning("Offline topographic pack unavailable or checksum invalid. Using the bundled outline map.")
        with st.expander("Source timing and storage"):
            kind_label = {"recorded": "Recorded archive · not a live poll",
                          "synthetic": "Synthetic exercise fixture",
                          "live": "Live connector cache"}
            status_rows = []
            for e in a.evidence + a.incomplete:
                row = event_rows_map.get((e.origin, e.event_id, e.revision))
                if row is None:
                    continue
                meta = packet_meta.get(row["packet_id"])
                status_rows.append({
                    "Record": short_ref(e), "Rev": e.revision,
                    "Source type": kind_label.get(row["packet_kind"], row["packet_kind"]),
                    "Acquired from source": store.iso(store.parse(meta["retrieved_at"])) if meta else "-",
                    "Stored on this laptop": store.iso(store.parse(row["imported_at"])),
                    "Valid from": f"{e.valid_from:%d %b %H:%M} UTC" if e.valid_from else "MISSING",
                    "Valid until": f"{e.valid_until:%d %b %H:%M} UTC" if e.valid_until else "MISSING",
                })
            if status_rows:
                st.dataframe(pd.DataFrame(status_rows), hide_index=True, width="stretch")
                st.caption("Acquisition is when the source was read; storage is when this laptop imported the file. "
                           "Neither decides authority - the highest stored revision per record identity does.")
            else:
                st.caption("No stored record applies to this delivery at the current scenario time. "
                           "Nothing was acquired for it; that is not an all-clear.")
            if a.coverage:
                st.caption("Coverage for this scope: " + " | ".join(f"{c.origin} {c.label}" for c in a.coverage))
        with st.expander("All deliveries · table"):
            st.dataframe(df, hide_index=True, width="stretch", height=250)
    with detail_col, st.container(key="desk-inspector"):
        st.selectbox("Inspect delivery", ids, key=inspect_key,
                     format_func=lambda did: f"{did} · {titles.get(did, '')}", label_visibility="collapsed",
                     help="Select here, in the queue, or on the map. Selection is preserved across filters and updates.")
        st.markdown(f'<div class="desk-selection">{html.escape(sel)}</div>'
                    f'<div class="desk-subtitle">{html.escape(titles.get(sel, d.corridor_id))}</div>', unsafe_allow_html=True)
        tone = visuals.COLORS[a.category]
        state_label = "REOPENED" if state_of(sel) == "reopened" else ("Reviewed" if state_of(sel) == "reviewed" else "Not reviewed")
        st.markdown(f'<div class="desk-status" style="--tone:{tone}"><strong>{SHAPE[a.category]} {html.escape(PLAIN[a.category])}</strong><br>{state_label}</div>', unsafe_allow_html=True)
        deskview.fact("Delivery window", f"{d.window_start:%d %b %H:%M}–{d.window_end:%H:%M} UTC")
        deskview.fact("Site" if recorded else "Corridor", replay.SITES[d.corridor_id]["label"] if recorded else d.corridor_id)
        st.markdown('<div class="desk-reason">' + html.escape(plain_reason(a)) + '</div>', unsafe_allow_html=True)
        if state_of(sel) == "reopened":
            st.error(f"Reopened · {case['current_review_id']} used earlier evidence. Previous decision preserved.")
        st.markdown('<div class="desk-next">' + html.escape(next_action(sel)) + '</div>', unsafe_allow_html=True)
        if a.stale:
            st.warning("Evidence stale — recheck source before relying on it.")
        if case and case["state"] == "reviewed":
            rv = store.review(conn, case["current_review_id"])
            st.caption(f"Current: {rv['review_id']} · {rv['decision']} by {rv['person']}" + (" · evidence stale - recheck" if a.stale else ""))
        with st.form(f"review-{sel}", clear_on_submit=True):
            note = st.text_area("Note", placeholder="Decision rationale…", height=68)
            decision_col, save_col = st.columns([1.8, 1], vertical_alignment="bottom")
            decision = decision_col.selectbox("Decision", DECISIONS, index=1)
            if save_col.form_submit_button("Save review", type="primary", width="stretch"):
                try:
                    rid = save_review(conn, ReviewInput(delivery_id=sel, person=st.session_state.person.strip() or "unnamed",
                                                        decision=decision, note=note))
                    flash("success", f"Saved {rid} for {sel} against evidence shown at {now:%H:%M}Z.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        with st.expander("What changed · stored revisions", expanded=False):
            st.markdown("**What changed** · from stored revisions")
            diffs = changes.for_delivery(d, events)
            if not diffs:
                st.caption("No later revision of a related record has been imported yet.")
            for ch in diffs:
                with st.container(border=True):
                    notice_from = f"revision {ch.from_revision} → {ch.to_revision}"
                    st.markdown(f"**{ch.summary}**  \n"
                                f"Published {ch.published_at:%d %b %H:%M} UTC · {notice_from}")
                    if ch.fields:
                        st.markdown("Field | Before | After\n--- | --- | ---\n" + "\n".join(
                            f"{label} | {before} | {after}" for label, before, after in ch.fields))
                    st.markdown(f"This delivery window ({d.window_start:%d %b %H:%M}–{d.window_end:%H:%M} UTC): "
                                f"{'overlaps' if ch.overlap_before else 'no overlap'} → "
                                f"**{'overlaps' if ch.overlap_after else 'no overlap'}**")
                    st.caption(f"Record {ch.event_id} · {ch.origin}")
        with st.expander("Source summary & uncertainty"):
            for e in a.evidence + a.incomplete:
                deskview.fact("Record", f"{short_ref(e)} · revision {e.revision}")
                deskview.fact("Valid from", f"{e.valid_from:%d %b %H:%M} UTC" if e.valid_from else "MISSING")
                deskview.fact("Valid until", f"{e.valid_until:%d %b %H:%M} UTC" if e.valid_until else "MISSING")
            if a.missing_origins:
                st.caption("Coverage not checked: " + ", ".join(a.missing_origins))
            if a.stale:
                st.caption("Evidence stale - recheck: " + " | ".join(a.stale_reasons))
            st.caption("No match is not a safety assessment. " + ("Archived replay, not a live poll." if recorded else "Synthetic exercise sources."))
        with st.expander("Previous decisions"):
            history = store.review_history(conn, sel)
            if not history:
                st.caption("No decisions recorded.")
            for rv in reversed(history):
                st.markdown(f"**{rv['review_id']} · {rv['decision']}**  \n{rv['person']} · scenario {rv['scenario_time']}")
                st.caption(rv['note'] or "No note recorded.")
                st.caption("Evidence: " + (", ".join(f"{x['event_id']} r{x['revision']}" for x in json.loads(rv['evidence'])) or "none"))
    with integrity_col:
        deskview.integrity(conn, key=inspect_key)

with review_tab, st.container(key="evidence-workspace"):
    deskview.heading(f"{sel} · Evidence review", titles.get(sel, d.corridor_id), "DELIVERY / EVIDENCE")
    st.markdown(f"**{BADGE[a.category]}** · {STATE[state_of(sel)]}")
    deskview.facts([
        ("Site" if recorded else "Corridor", replay.SITES[d.corridor_id]["label"] if recorded else d.corridor_id),
        ("Delivery window", f"{d.window_start:%d %b %H:%M}–{d.window_end:%H:%M} UTC"),
        ("Priority", d.priority), ("Deadline", f"{d.deadline:%d %b %H:%M} UTC")])
    left, right = st.columns([2.25, 1], gap="medium")
    with left:
        st.markdown("**Why this needs attention**" if attention(sel) else "**Assessment**")
        st.markdown(plain_reason(a))
        if a.stale:
            st.error("**Evidence stale - recheck.** Confirm the source before relying on this assessment.")
        if a.gap_reasons:
            st.warning(deskview.coverage_note(a, recorded) + " No matching record is not an all-clear.")
        st.markdown(f"**Supporting records · {len(a.evidence) + len(a.incomplete)}**")
        if not a.evidence and not a.incomplete:
            st.caption("No active matching record. Earlier decisions remain in history.")
        for e in a.evidence + a.incomplete:
            kind = kinds.get((e.origin, e.event_id, e.revision), "?")
            readable = deskview.source_headline(e)
            short_id = f" · {e.event_id} rev {e.revision}" if len(e.event_id) <= 12 else f" · rev {e.revision}"
            when = (f"valid {e.valid_from:%d %b %H:%M}–{e.valid_until:%d %b %H:%M} UTC" if e.valid_from and e.valid_until
                    else "validity MISSING")
            with st.expander(f"{e.event_type.capitalize()} · {when}{short_id} [{kind.upper()}]", expanded=True):
                st.markdown(f"**{readable}**")
                deskview.fact("Source", deskview.origin_name(e.origin))
                deskview.fact("Revision / status", f"{e.revision} · {e.status}")
                deskview.fact("Published", f"{e.published_at:%d %b %Y %H:%M} UTC")
                deskview.fact("Validity", f"{e.valid_from:%d %b %H:%M} → {e.valid_until:%d %b %H:%M} UTC"
                              if e.valid_from and e.valid_until else "MISSING · needs confirmation")
                if e.claim_key:
                    deskview.fact("Reported claim", f"{e.claim_key} = {e.claim_value}")
                if e.source_url:
                    st.link_button("Open original source", e.source_url, key=f"evidence-url-{e.origin}-{e.event_id}-{e.revision}")
                with st.expander("Original text, identity and hash"):
                    st.text(e.text)
                    st.caption(f"Record ID {e.event_id} rev {e.revision} · {e.origin}")
                    st.code(store.event_hashes(conn)[(e.origin, e.event_id, e.revision)], language=None)
        with st.expander("Matching details · technical"):
            st.caption("Matcher reasons (technical): " + " ".join(a.reasons))
            if a.stale_reasons:
                st.caption("Freshness: " + " | ".join(a.stale_reasons))
            if a.gap_reasons:
                st.caption("Coverage: " + " | ".join(a.gap_reasons))
        cov_rows = [{"Origin": c.origin, "Scope": c.scope_id,
                     "Last successful retrieval": store.iso(c.last_success) if c.last_success else "never",
                     "Last failed attempt": store.iso(c.last_failure) if c.last_failure else "-",
                     "State": c.label} for c in a.coverage]
        cov_rows += [{"Origin": o, "Scope": d.corridor_id, "Last successful retrieval": "never",
                      "Last failed attempt": "-", "State": "NOT CHECKED - absence of records is not evidence"}
                     for o in a.missing_origins]
        with st.expander("Source coverage · exact checks"):
            st.dataframe(pd.DataFrame(cov_rows), hide_index=True, width="stretch")

    with right, st.container(key="decision-summary"):
        st.markdown("**Decision status**")
        if case is None:
            st.info("Not reviewed yet.")
        elif case["state"] == "reopened":
            st.error(f"**Reopened.** {case['current_review_id']} used earlier evidence. Record a new decision.")
            st.caption("The earlier decision is preserved below.")
        else:
            rv = store.review(conn, case["current_review_id"])
            msg = f"**{rv['review_id']} · {rv['decision']}** · {rv['person']}."
            st.info(msg + (" Evidence stale - recheck." if a.stale else ""))
        st.button("Record new review" if case else "Record review", key="open-selected-review", type="primary",
                  width="stretch", on_click=open_selected_review)
        st.caption("Opens the selected delivery's review beside the map.")
        st.markdown("**Retained decisions**")
        hist = store.review_history(conn, sel)
        if not hist:
            st.caption("No decisions recorded.")
        for rv in reversed(hist):
            ev = ", ".join(f"{x['event_id']} r{x['revision']}" for x in json.loads(rv["evidence"])) or "none"
            stale = json.loads(rv["stale_at_review"])
            st.markdown(f"**{rv['review_id']} · {rv['decision']}**")
            st.caption(f"{rv['person']} · scenario {store.parse(rv['scenario_time']):%d %b %H:%M} UTC")
            st.markdown(rv['note'] or "No note recorded.")
            with st.expander(f"{rv['review_id']} · exact decision context"):
                st.caption(f"Recorded: {rv['created_wall']} (wall clock). Scenario: {rv['scenario_time']}.")
                st.markdown(f"Assessment then: {CATEGORIES[rv['category']]}; evidence: {ev}")
                if stale:
                    st.caption("Stale at decision: " + "; ".join(stale))
                if rv['previous_review_id']:
                    st.markdown(f"Supersedes {rv['previous_review_id']}")
        if case and case["state"] == "reopened":
            with st.expander("Stored reopening trigger"):
                st.text(case['reopened_reason'])
        for fr in handover.foreign_reviews(conn, sel):
            st.caption(f"From other laptop ({fr['handover_id']}): {fr['review_id']} {fr['decision']} by {fr['person']} "
                       f"at {fr['scenario_time']} - shown for comparison, not merged.")

with raw_tab, st.container(key="raw-workspace"):
    deskview.heading(f"{sel} · Raw records", "Exact stored fields and content hashes for inspection.", "RECORD INSPECTOR")
    st.caption("Immutable records as imported. Names explain the content; raw keys and hashes let a "
               "reviewer verify that a decision refers to an exact stored revision.")
    if not a.evidence and not a.incomplete:
        st.info("No evidence records apply to this delivery at the current scenario time. "
                "That is not an all-clear.")
    rows_by_key = event_rows_map
    for e in a.evidence + a.incomplete:
        row = rows_by_key.get((e.origin, e.event_id, e.revision))
        if row is None:
            continue
        raw = json.loads(row["canonical"])
        role = "Applies to this delivery" if e in a.evidence else "Cannot be ruled out / incomplete"
        with st.expander(f"{role} · {e.origin} · rev {e.revision}" + (f" · {e.event_id}" if len(e.event_id) <= 12 else ""),
                         expanded=False):
            st.caption(f"Identity `{e.origin}` / `{e.event_id}` / revision `{e.revision}` — highest revision "
                       "per identity is authoritative; older revisions are retained but never override it.")
            st.json(raw, expanded=True)
            st.caption(f"Content hash (canonical JSON, SHA-256): `{store.event_hashes(conn)[(e.origin, e.event_id, e.revision)]}`")
            st.caption(f"Packet `{row['packet_id']}` · kind `{row['packet_kind']}` · local import time `{row['imported_at']}`")

with brief_tab, st.container(key="brief-workspace"):
    deskview.heading("Situation brief", f"Scenario {now:%d %b %Y · %H:%M} UTC · prepared by {st.session_state.person}",
                     "LOCAL BRIEF / HANDOVER")
    st.caption("Built from stored assessments and decisions. No cloud model or API key needed.")
    brief_text = briefing.build(conn, st.session_state.person)
    st.download_button("Download brief (Markdown)", brief_text,
                       file_name=f"northlink-brief-{now:%Y%m%d-%H%MZ}.md", mime="text/markdown", key="brief-page-download")
    for did in ids:
        item = assessments[did]
        item_case = cases.get(did)
        label = f"{did} · {titles.get(did, item.delivery.corridor_id)} · {STATE[state_of(did)]}"
        with st.expander(label, expanded=did == sel):
            st.markdown(f"**{BADGE[item.category]}**")
            st.markdown("**Facts and applicability**")
            st.write(plain_reason(item))
            st.markdown("**Uncertainty**")
            st.write(deskview.coverage_note(item, recorded))
            if item.stale:
                st.warning("Evidence stale - recheck the source before relying on it.")
            if item_case:
                rv = store.review(conn, item_case["current_review_id"])
                st.markdown(f"**Human decision · {rv['review_id']}** · {rv['decision']} · {rv['person']}")
                st.write(rv['note'] or "No note recorded.")
            else:
                st.caption("No human decision recorded.")
            st.markdown("**Next review action**")
            st.write(next_action(did))
    with st.expander("Full export · exact source references"):
        st.text(brief_text)
with source_tab, st.container(key="sources-workspace"):
    deskview.heading("Sources & audit", "Inspect imported revisions, local storage times and retained actions.", "SOURCE REGISTER")
    deskview.facts([("Imported packets", len(packet_meta)), ("Stored event revisions", len(event_rows_map)),
                    ("Local decisions", conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]),
                    ("Data mode", "Recorded archive" if recorded else "Synthetic exercise")])
    if recorded:
        with st.expander("Recorded weather archive · source provenance"):
            st.caption("MET Norway · CC BY 4.0. Original CAP/GeoJSON files and acquisition manifest are bundled with this release.")
            for n in replay.notices():
                st.write(f"**Revision {n.revision} · {n.message_type}** · {n.sent:%d %b %Y %H:%M:%S} UTC")
                st.caption(n.headline)
                st.caption(f"{n.identifier} · validity {n.onset:%d %b %H:%M} → {n.expires:%d %b %H:%M} UTC")
                st.caption("References: " + (", ".join(n.references) or "original alert"))
                st.link_button("Original MET CAP notice", n.source_url, key="cap-" + n.identifier)
    st.caption("Live MET cache stays on this laptop. Portable JSON carries derived source-event records and decisions; the release bundle also includes the historical source fixture. Optional report intake is a separate inbox and is not part of core evidence handover.")
    st.divider()
    t1, t2, t3, t4 = st.tabs(["All records", "Packets", "Audit log", "Real source: MET alerts"])
    with t1:
        st.dataframe(pd.DataFrame([{
            "Origin": r["origin"], "Event": r["event_id"], "Rev": r["revision"], "Packet": r["packet_id"],
            "Kind": r["packet_kind"], "Imported (local)": r["imported_at"],
            **{k: v for k, v in json.loads(r["canonical"]).items() if k in ("corridor_id", "status", "published_at", "valid_from", "valid_until", "claim_value")},
        } for r in store.event_rows(conn)]), hide_index=True, width="stretch")
    with t2:
        st.dataframe(pd.DataFrame([dict(r) for r in store.packets(conn)]), hide_index=True, width="stretch")
    with t3:
        st.dataframe(pd.DataFrame([dict(r) for r in store.audit_log(conn)]), hide_index=True, width="stretch")
    with t4:
        st.markdown("**Real-source information (MET Norway MetAlerts 2.0).** Kept separate from the synthetic "
                    "scenario: these alerts are **not** mapped onto corridors C1-C3. "
                    "Data: MET Norway, licensed under CC BY 4.0 / NLOD. Fetches only when you press Refresh.")
        mc1, mc2 = st.columns(2)
        endpoint = mc1.selectbox("Endpoint", list(met.ENDPOINTS), format_func=lambda e: {
            "current": "current (live, active alerts)", "example": "example (MET sample alerts)",
            "test": "test (MET fictional test alerts)"}[e])
        county = mc2.selectbox("County (current only)", list(met.COUNTIES), index=1,
                               format_func=lambda c: f"{c} {met.COUNTIES[c]}", disabled=endpoint != "current")
        url = met.build_url(endpoint, county)
        st.caption(f"Request: `{url}`")
        configured = met.user_agent() is not None
        if not configured:
            st.warning("Live refresh disabled: set NORTHLINK_MET_USER_AGENT in .env "
                       "(app name + team contact, required by MET's terms), then restart the app.")
        if st.button("Refresh from MET (needs network)", disabled=not configured):
            with st.spinner("Contacting api.met.no (timeout 15 s)..."):
                res = met.refresh(conn, url)
            (st.success if res.ok else st.error)(res.message)
        data, row = met.load_cached(conn, url)
        att, ok = met.last_attempt(conn, url), met.last_success(conn, url)
        st.markdown(f"- Last successful retrieval: `{ok['attempted_at'] if ok else 'never'}`"
                    + (" (not modified)" if ok and ok["not_modified"] else "")
                    + (f"\n- Last attempt: `{att['attempted_at']}` - {'ok' if att['successful'] else 'FAILED: ' + (att['error'] or '')}" if att else "")
                    + (f"\n- Server Expires: `{ok['expires']}`, Last-Modified: `{ok['last_modified']}`" if ok else "")
                    + (f"\n- Saved original: `{Path(row['raw_path']).name}` sha256 `{row['sha256'][:16]}...`" if row and row["raw_path"] else ""))
        if data is None:
            st.info("No saved MET response for this request. Offline, nothing can be shown; this is not an all-clear.")
        else:
            alerts = met.parse_alerts(data)
            if ok and ok["attempted_at"] and (datetime.now(timezone.utc) - store.parse(ok["attempted_at"])).total_seconds() > 3600:
                st.warning("Saved MET response is over an hour old (wall clock). Alerts may have changed.")
            if not alerts:
                st.info(f"MET reported no alerts for this request at {data.get('lastChange', '?')}. "
                        "That is MET's statement for this area only, not a route-safety assessment.")
            else:
                st.dataframe(pd.DataFrame([{
                    "Status": a.status, "Type": a.msg_type, "Event": a.event, "Level": a.level, "Area": a.area,
                    "Onset": a.onset, "Ends": a.ends, "Certainty": a.certainty, "Geometry": a.geometry_type,
                    "BBox (lon/lat)": ", ".join(f"{v:.2f}" for v in a.bbox) if a.bbox else "-",
                    "Title": a.title, "MET id": a.id} for a in alerts]), hide_index=True, width="stretch")
                if any(a.status == "Test" for a in alerts):
                    st.caption("Rows with Status = Test are MET's own test/example alerts, not real warnings.")

with intake_tab, st.container(key="intake-workspace"):
    report_ui.render(base.with_name(base.stem + suffix + base.suffix), workspace, st.session_state.person)
