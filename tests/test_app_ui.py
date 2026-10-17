"""Drive app.py headlessly with Streamlit's AppTest against a temp database."""
import importlib

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parent.parent / "app.py"


def delivery_ids(at):
    """Delivery IDs offered by the selector (its labels add readable status after the ID)."""
    box = next(s for s in at.selectbox if s.label == "Inspect delivery")
    return {o.split(" · ")[0] for o in box.options}


def selected_id(at):
    return next(s for s in at.selectbox if s.label == "Inspect delivery").value


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("NORTHLINK_DB", str(tmp_path / "ui.db"))
    import northlink.store as s
    importlib.reload(s)
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    yield at


def test_load_review_and_restart(app, tmp_path):
    at = app
    assert not at.exception
    next(b for b in at.button if b.label.startswith("Load demo")).click().run()
    assert not at.exception
    assert any("SYNTHETIC SCENARIO" in w.value for w in at.warning)
    sel = next(s for s in at.selectbox if s.label == "Inspect delivery")
    sel.select("D2").run()
    assert any("E2 rev 1" in e.label for e in at.expander)
    at.text_area[0].input("Hold until road authority confirms")
    next(s for s in at.selectbox if s.label == "Decision").select("Hold for confirmation")
    next(b for b in at.button if b.label == "Save review").click().run()
    assert not at.exception
    assert any("Saved R1 for D2" in s.value for s in at.success)

    # "Restart": brand-new script run with a fresh resource cache, same DB file.
    st.cache_resource.clear()  # drop the cached DB connection
    at2 = AppTest.from_file(str(APP), default_timeout=30)
    at2.run()
    next(s for s in at2.selectbox if s.label == "Inspect delivery").select("D2").run()
    assert not at2.exception
    md = " ".join(m.value for m in at2.markdown)
    assert "R1" in md and "Hold until road authority confirms" in md and "E2 r1" in md


def test_startup_makes_no_network_call(app, monkeypatch):
    import requests
    def boom(*a, **k):
        raise AssertionError("network call during startup")
    monkeypatch.setattr(requests.Session, "request", boom)
    monkeypatch.setattr(requests, "get", boom)
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    next(b for b in at.button if b.label.startswith("Load demo")).click().run()
    assert not at.exception
    assert any("No saved MET response" in i.value for i in at.info)


def test_rehearsal_selection_stability_and_workspace_isolation(app):
    at = app
    # 1. Load Synthetic demo, review D2, set 12:40 stale, import packet B, re-review D2, import late E2r1
    next(b for b in at.button if b.label == "Load demo plan + packet A").click().run()
    next(s for s in at.selectbox if s.label == "Inspect delivery").select("D2").run()
    at.text_area[0].input("Hold until road authority confirms")
    next(s for s in at.selectbox if s.label == "Decision").select("Hold for confirmation")
    next(b for b in at.button if b.label == "Save review").click().run()
    assert next(s for s in at.selectbox if s.label == "Inspect delivery").value == "D2"

    next(t for t in at.text_input if "Set scenario time" in t.label).input("12:40")
    next(b for b in at.button if b.label == "Set").click().run()
    assert any("Evidence stale - recheck" in e.value for e in at.error)

    next(b for b in at.button if b.label == "Import correction · packet B").click().run()
    assert next(s for s in at.selectbox if s.label == "Inspect delivery").value == "D2"
    assert any("Reopened" in e.value for e in at.error)

    # Saving R2 on reopened D2 changes its queue sort order; selection must stay on D2
    at.text_area[0].input("Closure cancelled, proceed")
    next(s for s in at.selectbox if s.label == "Decision").select("Proceed as planned")
    next(b for b in at.button if b.label == "Save review").click().run()
    assert not at.exception
    assert next(s for s in at.selectbox if s.label == "Inspect delivery").value == "D2"

    # Late E2 revision 1 via local-file expander advances to 12:48Z and does not revive restriction
    next(s for s in at.selectbox if s.label == "Bundled synthetic file").select("packet_late_E2r1.json").run()
    next(b for b in at.button if b.label == "Import packet_late_E2r1.json").click().run()
    assert not at.exception
    assert any("12:48Z" in m.value for m in at.markdown)
    assert next(s for s in at.selectbox if s.label == "Inspect delivery").value == "D2"

    # 2. Switch to Finnmark workspace, start a practice run, and verify Synthetic workspace is untouched
    next(s for s in at.selectbox if s.label == "Workspace").select("Finnmark · recorded weather").run()
    assert not any(s.label == "Bundled synthetic file" for s in at.selectbox)
    next(b for b in at.button if b.label == "New practice run").click().run()
    assert not at.exception
    assert any(b.label == "Return to persistent workspace" for b in at.button)
    assert delivery_ids(at) == {"F1", "F2", "F3", "F4", "F5", "F6"}

    # Switching back to Synthetic exercise still shows the persistent D1-D6 run and R2
    next(s for s in at.selectbox if s.label == "Workspace").select("Synthetic exercise").run()
    assert not at.exception
    assert delivery_ids(at) == {"D1", "D2", "D3", "D4", "D5", "D6"}
    md = " ".join(m.value for m in at.markdown)
    assert "R2" in md and "Supersedes R1" in md

    # Switch back to Finnmark and return from practice run to persistent workspace
    next(s for s in at.selectbox if s.label == "Workspace").select("Finnmark · recorded weather").run()
    next(b for b in at.button if b.label == "Return to persistent workspace").click().run()
    assert not at.exception
    assert not any(b.label == "Return to persistent workspace" for b in at.button)


def _table_snapshot(conn):
    tables = ("meta", "packets", "events", "coverage", "plans", "deliveries", "reviews",
              "review_cases", "foreign_reviews", "audit")
    return {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY rowid")] for t in tables}


def test_cross_workspace_import_rejected_without_contaminating_db(tmp_path, monkeypatch):
    """End to end through the real upload control. Fails if the app's guard is bypassed."""
    import json
    monkeypatch.setenv("NORTHLINK_DB", str(tmp_path / "ws.db"))
    from northlink import handover, store
    from northlink.loader import SCENARIO_DIR, load_file
    from northlink.reconcile import import_plan
    importlib.reload(store)
    st.cache_resource.clear()

    # The independently reported reproducer: a valid synthetic plan-only handover.
    src = store.connect(tmp_path / "plan-only-src.db")
    import_plan(src, load_file(SCENARIO_DIR / "deliveries.json"))
    payload = json.dumps(handover.export(src)).encode()
    src.close()

    at = AppTest.from_file(str(APP), default_timeout=30).run()
    next(s for s in at.selectbox if s.label == "Workspace").select("Finnmark · recorded weather").run()
    next(b for b in at.button if b.label == "Load recorded Finnmark exercise").click().run()
    finn = store.connect(tmp_path / "ws-finnmark.db")
    before = _table_snapshot(finn)
    assert [d.delivery_id for d in store.deliveries(finn)] == ["F1", "F2", "F3", "F4", "F5", "F6"]

    at.file_uploader[0].set_value(("synthetic-plan-only.json", payload, "application/json")).run()
    next(b for b in at.button if b.label == "Import uploaded file").click().run()
    assert not at.exception
    assert any("Synthetic exercise" in e.value and "nothing changed" in e.value for e in at.error)
    assert _table_snapshot(finn) == before
    assert delivery_ids(at) == {
        "F1", "F2", "F3", "F4", "F5", "F6"}
    finn.close()

    # Valid control: the same file is accepted by the synthetic workspace.
    next(s for s in at.selectbox if s.label == "Workspace").select("Synthetic exercise").run()
    at.file_uploader[0].set_value(("synthetic-plan-only.json", payload, "application/json")).run()
    next(b for b in at.button if b.label == "Import uploaded file").click().run()
    assert not at.exception
    assert any("Restored handover" in s.value for s in at.success)
    assert delivery_ids(at) == {
        "D1", "D2", "D3", "D4", "D5", "D6"}




def _map_data(at):
    import json as _json
    (el,) = at.get("bidi_component")
    return _json.loads(el.proto.json)


def test_recorded_map_follows_selection_and_save(app):
    at = app
    next(s for s in at.selectbox if s.label == "Workspace").select("Finnmark · recorded weather").run()
    next(b for b in at.button if b.label == "Load recorded Finnmark exercise").click().run()
    assert any(t.label == "Map & review" for t in at.tabs)
    box = next(s for s in at.selectbox if s.label == "Inspect delivery")
    box.select("F3").run()
    data = _map_data(at)
    assert data["selected"] == "F3" and data["selected_marker"] == "FN-TROMS"
    assert {m["id"] for m in data["markers"]} == {"FN-VARANGER", "FN-TROMS"}
    assert "original alert (revision 1 of 3)" in data["status"] and "24 Apr 07:00" in data["status"]

    box = next(s for s in at.selectbox if s.label == "Inspect delivery")
    box.select("F1").run()
    at.text_area[0].input("Await next source update")
    next(b for b in at.button if b.label == "Save review").click().run()
    next(b for b in at.button if b.label == "Import archived update 1").click().run()
    assert not at.exception
    assert selected_id(at) == "F1"
    data = _map_data(at)
    assert data["selected"] == "F1" and data["has_previous"] and "update 1 (revision 2 of 3)" in data["status"]
    md = " ".join(m.value for m in at.markdown)
    assert "Now overlaps this delivery window" in md
    assert "24 Apr 07:00 UTC | 24 Apr 09:00 UTC" in md
    assert any("Reopened" in e.value for e in at.error)
