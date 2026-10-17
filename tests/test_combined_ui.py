"""The combined app exposes stored raw evidence and source timing together."""
import importlib
import json
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest


def get(elements, label):
    return next(e for e in elements if e.label == label)


def test_raw_evidence_time_status_and_intake_coexist(tmp_path, monkeypatch):
    monkeypatch.setenv("NORTHLINK_DB", str(tmp_path / "combined-ui.db"))
    from northlink import report_intake, store
    importlib.reload(store)
    monkeypatch.setattr(report_intake, "availability", lambda: (False, "Manual entry available"))
    st.cache_resource.clear()
    app = Path(__file__).resolve().parents[1] / "app.py"
    at = AppTest.from_file(str(app), default_timeout=30).run()
    get(at.button, "Load demo plan + packet A").click().run()
    get(at.selectbox, "Inspect delivery").select("D2").run()
    assert not at.exception
    assert {t.label for t in at.tabs} >= {"Raw evidence", "Report intake", "Evidence detail", "Map & review"}
    raw = [json.loads(e.value) for e in at.json]
    assert any(r.get("event_id") == "E2" and r.get("revision") == 1 and r.get("status") == "active" for r in raw)
    status = [frame.value for frame in at.dataframe if "Acquired from source" in frame.value.columns]
    assert len(status) == 1
    assert status[0].iloc[0]["Record"] == "E2"
    assert status[0].iloc[0]["Rev"] == 1
    assert "Stored on this laptop" in status[0].columns
    assert "Valid until" in status[0].columns
    assert get(at.button, "Save confirmed report").disabled
    st.cache_resource.clear()
