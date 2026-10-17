"""Report confirmation, source preservation, isolation and failure handling."""
import importlib
import json
from pathlib import Path
import queue
from unittest.mock import Mock

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from northlink import report_intake as intake


def test_confirmation_required_and_source_preserved(tmp_path):
    path = tmp_path / "inbox.sqlite3"
    text = "  Veien er ikke stengt.\nTidligere melding er opphevet.  "
    args = dict(text=text, category="access_update", person="Reviewer", source_label="Exercise radio report",
                workspace="Synthetic exercise", suggestion=intake.baseline(text))
    with pytest.raises(ValueError, match="Confirm"):
        intake.save_confirmed(path, confirmed=False, **args)
    assert not path.exists()
    rid = intake.save_confirmed(path, confirmed=True, **args)
    record = intake.saved_reports(path)[0]
    assert record["report_id"] == rid
    assert record["original_text"] == text
    assert record["text_sha256"] == intake.text_hash(text)
    assert record["confirmed_category"] == "access_update"
    assert record["affects_assessments"] is False
    assert record["data_kind"] == "user-supplied exercise report"
    # A later report is another record and leaves the first one intact.
    intake.save_confirmed(path, confirmed=True, **{**args, "category": "unclear", "suggestion": None})
    assert len(intake.saved_reports(path)) == 2
    assert intake.saved_reports(path)[1] == record


def test_edited_report_invalidates_model_suggestion(tmp_path):
    original = "The road is closed."
    changed = "The road is not closed."
    suggestion = intake.baseline(original)
    with pytest.raises(ValueError, match="changed"):
        intake.save_confirmed(tmp_path / "inbox.sqlite3", text=changed, category="access_update", person="P",
                              source_label="Exercise", workspace="Synthetic exercise", suggestion=suggestion, confirmed=True)
    assert not (tmp_path / "inbox.sqlite3").exists()


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -1, 1.1, True, "certain"])
def test_invalid_model_scores_are_rejected(score):
    text = "Weather report"
    suggestion = {"category": "weather", "raw_score": score, "text_sha256": intake.text_hash(text)}
    with pytest.raises(ValueError, match="invalid score"):
        intake.validate_suggestion(suggestion, text)


def test_workspaces_and_practice_runs_have_separate_inboxes(tmp_path):
    paths = [intake.inbox_path(tmp_path / p) for p in ("northlink.db", "northlink-finnmark.db", "northlink-practice-1.db")]
    assert len(set(paths)) == 3
    intake.save_confirmed(paths[0], text="The generator is broken.", category="supply", person="P",
                          source_label="Exercise", workspace="Synthetic exercise", suggestion=None, confirmed=True)
    assert len(intake.saved_reports(paths[0])) == 1
    assert intake.saved_reports(paths[1]) == intake.saved_reports(paths[2]) == []
    assert not (tmp_path / "northlink.db").exists()


def test_timeout_stops_worker_and_does_not_silently_substitute_rules(monkeypatch):
    worker = intake.LocalClassifier()
    worker.process = Mock()
    worker.process.poll.return_value = None
    worker.responses = Mock()
    worker.responses.get.side_effect = queue.Empty
    worker.close = Mock()
    with pytest.raises(RuntimeError, match="timed out"):
        worker.suggest("The road is closed.", timeout=.01)
    worker.close.assert_called_once()


def test_bad_response_closes_worker():
    worker = intake.LocalClassifier()
    worker.process = Mock()
    worker.process.poll.return_value = None
    worker.responses.put('{"id":"wrong-request","suggestion":{}}')
    worker.close = Mock()
    with pytest.raises(RuntimeError, match="did not match"):
        worker.suggest("Weather report")
    worker.close.assert_called_once()


def _element(elements, label):
    return next(e for e in elements if e.label == label)


def test_ui_rules_manual_confirmation_edit_and_restart(tmp_path, monkeypatch):
    db = tmp_path / "ui.db"
    monkeypatch.setenv("NORTHLINK_DB", str(db))
    from northlink import store
    importlib.reload(store)
    # The app must remain usable when the model is absent, and must not spawn
    # any worker on startup, report editing, simple rules or confirmation.
    monkeypatch.setattr(intake, "availability", lambda: (False, "Model not installed; manual entry available."))
    monkeypatch.setattr(intake.subprocess, "Popen", Mock(side_effect=AssertionError("Unexpected model startup")))
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    at = AppTest.from_file(str(app_path), default_timeout=30).run()
    _element(at.button, "Load demo plan + packet A").click().run()
    assert not at.exception
    assert _element(at.button, "Save confirmed report").disabled
    _element(at.text_area, "Incoming report").input("Veien er ikke stengt.").run()
    _element(at.button, "Suggest category").click().run()
    assert not at.exception
    assert _element(at.selectbox, "Confirmed report category").value == "access_update"
    _element(at.checkbox, "I checked the original report and this category").check().run()
    # Changing the category must require a new confirmation.
    _element(at.selectbox, "Confirmed report category").select("unclear").run()
    assert not _element(at.checkbox, "I checked the original report and this category").value
    _element(at.checkbox, "I checked the original report and this category").check().run()
    _element(at.button, "Save confirmed report").click().run()
    assert not at.exception
    assert _element(at.button, "Save confirmed report").disabled
    records = intake.saved_reports(intake.inbox_path(db))
    assert len(records) == 1 and records[0]["original_text"] == "Veien er ikke stengt."
    assert records[0]["confirmed_category"] == "unclear"  # human overrode suggestion
    with store.connect(db) as conn:
        assert not store.review_history(conn, "D2")
        assert all(e.origin != "laya" for e in store.all_events(conn))
    # Editing source text removes its old suggestion and confirmation.
    _element(at.checkbox, "I checked the original report and this category").check().run()
    _element(at.text_area, "Incoming report").input("The road is closed.").run()
    assert not _element(at.checkbox, "I checked the original report and this category").value
    assert not any("Suggested category:" in e.value for e in at.info)
    _element(at.selectbox, "Suggestion method").select("Laya · local experiment").run()
    assert _element(at.button, "Suggest category").disabled
    st.cache_resource.clear()
    at2 = AppTest.from_file(str(app_path), default_timeout=30).run()
    assert not at2.exception
    assert any("Saved" not in e.label and records[0]["report_id"] in e.label for e in at2.expander)
    assert len(intake.saved_reports(intake.inbox_path(db))) == 1


def test_empty_and_oversized_text_rejected():
    for text in ("", " \n ", "a" * (intake.MAX_CHARS + 1)):
        with pytest.raises(ValueError):
            intake.baseline(text)
