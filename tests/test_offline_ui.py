"""Recorded replay, review and a fresh app run with Python network access blocked."""
import importlib
import socket
from pathlib import Path

import requests
import streamlit as st
from streamlit.testing.v1 import AppTest


def test_recorded_replay_review_and_restart_without_network(tmp_path, monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Network access attempted during offline workflow")
    monkeypatch.setattr(requests.Session, "request", blocked)
    monkeypatch.setattr(requests, "get", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setenv("NORTHLINK_DB", str(tmp_path / "offline.db"))
    from northlink import store
    importlib.reload(store)
    st.cache_resource.clear()
    app = Path(__file__).resolve().parent.parent / "app.py"
    at = AppTest.from_file(str(app), default_timeout=30).run()
    next(s for s in at.selectbox if s.label == "Workspace").select("Finnmark · recorded weather").run()
    next(b for b in at.button if b.label == "Load recorded Finnmark exercise").click().run()
    assert not at.exception
    next(s for s in at.selectbox if s.label == "Inspect delivery").select("F1").run()
    at.text_area[0].input("Offline review: await the next source update")
    next(b for b in at.button if b.label == "Save review").click().run()
    assert not at.exception
    next(b for b in at.button if b.label == "Import archived update 1").click().run()
    assert not at.exception
    assert any("Reopened" in s.value for s in at.success)
    st.cache_resource.clear()
    restarted = AppTest.from_file(str(app), default_timeout=30).run()
    next(s for s in restarted.selectbox if s.label == "Workspace").select("Finnmark · recorded weather").run()
    next(s for s in restarted.selectbox if s.label == "Inspect delivery").select("F1").run()
    assert not restarted.exception
    text = " ".join(m.value for m in restarted.markdown)
    assert "Offline review: await the next source update" in text
    assert any("Reopened" in e.value for e in restarted.error)
    db = store.connect(tmp_path / "offline-finnmark.db")
    from northlink import briefing, handover
    assert store.review_case(db, "F1")["state"] == "reopened"
    assert "Offline review" in briefing.build(db)
    assert handover.export(db)["reviews"][0]["note"].startswith("Offline review")
    db.close()
    st.cache_resource.clear()
