"""Presentation helpers. Filters never change the selected delivery or stored state."""
import html
import hashlib
import json
import uuid
import streamlit as st
from .impact import ATTENTION
from . import store
from .models import Packet
from .reconcile import IntegrityError, import_packet


def filtered_ids(ids, assessments, cases, mode, query, titles):
    result = []
    query = query.strip().casefold()
    for did in ids:
        state = cases[did]["state"] if did in cases else "open"
        category = assessments[did].category
        attention = state == "reopened" or (category in ATTENTION and state != "reviewed")
        if mode == "To review" and not attention:
            continue
        if mode == "Reopened" and state != "reopened":
            continue
        if mode == "Conflicting" and category != "conflict":
            continue
        if query and query not in f"{did} {titles.get(did, '')} {assessments[did].delivery.corridor_id}".casefold():
            continue
        result.append(did)
    return result


def queue(ids, assessments, cases, titles, selected, inspect_key, on_pick):
    labels = {"conflict": "Sources disagree", "restriction": "Restriction reported", "advisory": "Weather impact",
              "needs_confirmation": "Needs confirmation", "no_match": "No matching record"}
    st.markdown('<div class="desk-section">Deliveries <span style="float:right">' + str(len(ids)) + '</span></div>', unsafe_allow_html=True)
    mode = st.selectbox("Queue filter", ["All", "To review", "Reopened", "Conflicting"],
                        key=inspect_key + "-filter", label_visibility="collapsed")
    query = st.text_input("Find delivery", placeholder="Find delivery…", key=inspect_key + "-search", label_visibility="collapsed")
    shown = filtered_ids(ids, assessments, cases, mode, query, titles)
    if selected not in shown:
        st.caption(f"Inspecting {selected} outside this filter.")
    if not shown:
        st.caption("No deliveries match. Try another filter.")
    for did in shown:
        a = assessments[did]
        state = cases[did]["state"] if did in cases else "open"
        title = titles.get(did, a.delivery.corridor_id).split(" · ")[0]
        st.button(f"{did}  ·  {title}", type="primary" if did == selected else "secondary", width="stretch",
                  key=inspect_key + "-pick-" + did, on_click=on_pick, args=(did,),
                  help=f"Inspect {did}: {labels[a.category]}")
        st.caption(f"{'↻ REOPENED' if state == 'reopened' else ('Reviewed' if state == 'reviewed' else labels[a.category])}"
                   f" · {a.delivery.window_start:%H:%M}–{a.delivery.window_end:%H:%M} UTC")
    st.caption(f"{len(shown)} of {len(ids)} shown · attention first")


def fact(label, value):
    st.markdown(f'<div class="desk-fact"><span>{html.escape(str(label))}</span>'
                f'<strong>{html.escape(str(value))}</strong></div>', unsafe_allow_html=True)


def heading(title, subtitle, eyebrow="REVIEW WORKSPACE"):
    e = html.escape
    st.markdown(f'<div class="panel-heading"><div class="panel-eyebrow">{e(eyebrow)}</div>'
                f'<h2>{e(title)}</h2><p>{e(subtitle)}</p></div>', unsafe_allow_html=True)


def facts(items):
    e = html.escape
    st.markdown('<div class="panel-facts">' + ''.join(
        f'<div><span>{e(str(label))}</span><strong>{e(str(value))}</strong></div>'
        for label,value in items) + '</div>', unsafe_allow_html=True)


def origin_name(origin):
    return {"met-metalerts-recorded":"MET Norway · recorded archive", "demo-weather":"Weather reports · exercise",
            "demo-road":"Road reports · exercise"}.get(origin, origin)


def coverage_note(assessment, recorded):
    if not assessment.missing_origins:
        return "No missing-source flag under the configured policy. This does not prove route safety."
    if recorded:
        return "Coverage gap: historical polling coverage is not recorded. The warning archive does not establish that all sources were checked."
    return "Coverage gap: " + ", ".join(origin_name(o) for o in assessment.missing_origins) + ". These sources have not been checked for this corridor."


def source_headline(event):
    # Strip only the known machine-ID prefix; this is source text, not an AI
    # summary or a replacement for the original stored record.
    text = event.text.splitlines()[0]
    if event.origin == "met-metalerts-recorded" and text.startswith("MET CAP "):
        _, separator, headline = text.partition("). ")
        if separator:
            text = headline
    return text


def run_integrity_checks(source):
    """Exercise the real importer in a disposable in-memory DB, never the presenter DB."""
    sandbox = store.connect(":memory:")
    try:
        source.backup(sandbox)
        row = sandbox.execute("SELECT canonical FROM packets ORDER BY packet_id").fetchall()
        packet = next((p for r in row if (p := Packet.model_validate_json(r[0])).events), None)
        if packet is None:
            return []
        # A live connector packet cannot be re-imported from a local file. Its
        # stored identity can still be checked through the real connector path.
        from_connector = packet.kind == "live"
        def digest():
            return hashlib.sha256("\n".join(sandbox.iterdump()).encode()).hexdigest()
        baseline = digest()
        result = import_packet(sandbox, packet, from_connector=from_connector)
        checks = [{"check": "Identical packet", "expected": "Duplicate; no changes",
                   "passed": result.duplicate and digest() == baseline}]
        altered_event = packet.events[0].model_copy(update={
            "text": packet.events[0].text + " [ALTERED IN DISPOSABLE CHECK]"})
        altered = packet.model_copy(update={"events": [altered_event, *packet.events[1:]]})
        for label, attempt in (
            ("Changed payload, same packet ID", altered),
            ("New packet ID, reused event revision", altered.model_copy(update={"packet_id": "integrity-check-" + uuid.uuid4().hex})),
        ):
            rejected = False
            try:
                import_packet(sandbox, attempt, from_connector=from_connector)
            except IntegrityError:
                rejected = True
            checks.append({"check": label, "expected": "Rejected; no changes",
                           "passed": rejected and digest() == baseline})
        return checks
    finally:
        sandbox.close()


def integrity(conn, key):
    st.markdown("**Report integrity**")
    st.caption("Check what is protected before relying on a report.")
    fact("Reused identity", "Changed content rejected")
    fact("Late older revision", "Retained; cannot override newer")
    fact("Earlier decisions", "Preserved when review reopens")
    st.warning("Publisher identity is not authenticated. A hash cannot prove who sent a report.")
    with st.expander("What these checks do"):
        st.markdown("The importer compares a packet ID and each origin / event ID / revision with stored content. "
                    "A conflicting reuse rejects the entire import. A new, fabricated identity can still pass schema checks. "
                    "Cryptographic signatures with trusted publisher keys are not implemented.")
        st.caption("Offline handover transfers records and reviews by file. It is not automatic multi-node synchronisation or source authentication.")
    if st.button("Run altered-report checks", key=key + "-integrity-check", width="stretch"):
        st.session_state[key + "-integrity-result"] = run_integrity_checks(conn)
    results = st.session_state.get(key + "-integrity-result")
    if results is not None:
        if not results:
            st.info("Load an exercise first.")
        else:
            for check in results:
                (st.success if check["passed"] else st.error)(
                    f"{check['check']}: {check['expected']} — {'PASS' if check['passed'] else 'FAIL'}")
            st.caption("Actual importer run against an in-memory copy. The working database was not changed.")
            st.download_button("Download check receipt", json.dumps(results, indent=2),
                               file_name="northlink-integrity-checks.json", mime="application/json", key=key + "-integrity-receipt")
