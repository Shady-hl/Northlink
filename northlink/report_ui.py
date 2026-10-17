"""Human-confirmed local report inbox; inference is always an explicit action."""
from __future__ import annotations
import atexit
import json
from pathlib import Path

import streamlit as st
from northlink import report_intake as intake
from northlink import deskview


@st.cache_resource
def classifier():
    worker = intake.LocalClassifier()
    atexit.register(worker.close)
    return worker


def render(core_db: Path, workspace: str, person: str):
    deskview.heading("Report intake", "Capture an English or Norwegian report, check its category and confirm the original wording.",
                     "STAGING INBOX / HUMAN CONFIRMATION")
    st.info("Confirmed reports are saved in a separate inbox. They do not automatically change evidence or map assessments.")
    key = "intake_" + core_db.stem
    if st.session_state.pop(key + "_reset_confirmation", False):
        st.session_state[key + "_confirmed"] = False
    ready, message = intake.availability()
    left, right = st.columns([3, 2], gap="large")
    with left:
        text = st.text_area("Incoming report", max_chars=intake.MAX_CHARS, height=150, key=key + "_text",
                            placeholder="Example: Veien er ikke stengt. Det tidligere varselet er opphevet.")
        source = st.text_input("Report source label", value="Exercise input", max_chars=200, key=key + "_source")
        method = st.selectbox("Suggestion method", ["Simple rules", "Laya · local experiment", "Manual"],
                              key=key + "_method")
        if method == "Simple rules":
            st.caption("Rules run locally. Check the original wording before confirming a suggested category.")
        elif method == "Manual":
            st.caption("Choose the report category yourself. No model is called.")
        if method.startswith("Laya"):
            st.caption(message)
            evaluation = intake.ROOT / "verification/laya-evaluation.json"
            if evaluation.exists():
                metrics = json.loads(evaluation.read_text())["summary"]
                m, b = metrics["laya"], metrics["baseline"]
                st.warning(f"Experimental: {m['correct']}/{m['n']} correct in our synthetic test, "
                           f"versus {b['correct']}/{b['n']} for simple rules. Read the original report; "
                           "model scores are not calibrated for this task.")
        draft_key = key + "_suggestion"
        old = st.session_state.get(draft_key)
        if old and (old["text_sha256"] != intake.text_hash(text) or old.get("ui_method") != method):
            st.session_state.pop(draft_key, None)
            st.session_state.pop(key + "_confirmed", None)
        if st.button("Suggest category", disabled=not text.strip() or method == "Manual" or
                     (method.startswith("Laya") and not ready), key=key + "_suggest"):
            try:
                if method.startswith("Laya"):
                    with st.spinner("Classifying on this Mac. First use loads the model; later requests reuse it…"):
                        result = classifier().suggest(text)
                else:
                    result = intake.baseline(text)
                result["ui_method"] = method
                st.session_state[draft_key] = result
                st.session_state[key + "_category"] = result["category"]
                st.session_state[key + "_confirmed"] = False
            except (RuntimeError, ValueError) as exc:
                st.session_state.pop(draft_key, None)
                st.error(str(exc))
        suggestion = st.session_state.get(draft_key)
        if suggestion:
            st.info("Suggested category: " + intake.LABELS[suggestion["category"]])
            st.caption(f"{suggestion['method']} · {suggestion['elapsed_ms']:,.0f} ms · awaiting your confirmation")
            if method.startswith("Laya"):
                with st.expander("Model and evaluation details"):
                    st.json({k: v for k, v in suggestion.items() if k != "ui_method"})
                    if evaluation.exists():
                        metrics = json.loads(evaluation.read_text())
                        st.write(metrics.get("summary", {}))
                        st.caption("Small synthetic evaluation, not operational validation. See docs/LAYA.md.")
        # Reset the confirmation whenever source text, source label or method changes.
        signature = (intake.text_hash(text), source, method, person)
        if st.session_state.get(key + "_signature") != signature:
            st.session_state[key + "_signature"] = signature
            st.session_state[key + "_confirmed"] = False
        st.session_state.setdefault(key + "_category", "unclear")
        category = st.selectbox("Confirmed report category", list(intake.LABELS), index=None,
                                format_func=intake.LABELS.get, key=key + "_category",
                                on_change=lambda: st.session_state.update({key + "_confirmed": False}))
        confirmed = st.checkbox("I checked the original report and this category", key=key + "_confirmed")
        if st.button("Save confirmed report", type="primary", disabled=not confirmed or not text.strip() or
                     not source.strip() or not person.strip() or category not in intake.LABELS, key=key + "_save"):
            try:
                rid = intake.save_confirmed(intake.inbox_path(core_db), text=text, category=category, person=person,
                                            source_label=source, workspace=workspace, suggestion=suggestion,
                                            confirmed=confirmed)
                st.session_state[key + "_saved"] = rid
                # A rerun clears the checkbox before rendering the next request.
                st.session_state[key + "_reset_confirmation"] = True
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    with right:
        st.markdown("**Local, human-confirmed records**")
        if st.session_state.get(key + "_saved"):
            st.success("Saved " + st.session_state[key + "_saved"])
        records = intake.saved_reports(intake.inbox_path(core_db))
        if not records:
            st.caption("No confirmed reports yet. Model suggestions are not saved automatically.")
        for record in records[:10]:
            with st.expander(record["report_id"] + " · " + intake.LABELS[record["confirmed_category"]]):
                st.text(record["original_text"])
                st.caption(f"Confirmed by {record['confirmed_by']} · {record['confirmed_at_utc']} · {record['source_label']}")
                st.caption("User-supplied exercise text. Not an authenticated source or route-safety finding.")
                st.json(record, expanded=False)
        if records:
            st.download_button("Export confirmed report inbox (JSON)",
                               json.dumps({"schema_version": 1, "reports": records}, ensure_ascii=False, indent=2),
                               file_name="northlink-confirmed-reports.json", mime="application/json", key=key + "_export")
            st.caption("This inbox has its own export. The existing evidence handover JSON does not include it.")
