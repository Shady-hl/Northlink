"""Actual-model AppTest rehearsal, including full model-worker restart, offline.

Opt-in: .venv/bin/python scripts/verify_local_intake.py
Creates new temporary databases; never touches existing workspace data.
"""
from __future__ import annotations
import importlib
import ipaddress
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def local(host):
    if host in ("localhost", "", None):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def block(event, args):
    if event == "socket.getaddrinfo" and not local(args[0]):
        raise OSError("Verification: external DNS blocked")
    if event == "socket.connect" and isinstance(args[1], tuple) and not local(args[1][0]):
        raise OSError("Verification: external connection blocked")


def get(elements, label):
    return next(e for e in elements if e.label == label)


def main():
    # All subsequent Python external connections are rejected, including startup.
    sys.addaudithook(block)
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    from northlink import report_intake, report_ui, store
    target = Path(tempfile.mkdtemp(prefix="northlink-intake-check-")) / "exercise.db"
    os.environ["NORTHLINK_DB"] = str(target)
    importlib.reload(store)
    text = "Lageret trenger 200 liter diesel før morgenen."
    timings = []
    for attempt in range(2):
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90).run()
        if attempt == 0:
            get(at.button, "Load demo plan + packet A").click().run()
        assert not at.exception
        get(at.text_area, "Incoming report").input(text).run()
        get(at.selectbox, "Suggestion method").select("Laya · local experiment").run()
        start = time.perf_counter()
        get(at.button, "Suggest category").click().run()
        timings.append(round((time.perf_counter() - start) * 1000, 1))
        assert not at.exception
        assert not at.error, [e.value for e in at.error]
        assert any("Suggested category:" in e.value for e in at.info)
        assert get(at.button, "Save confirmed report").disabled
        if attempt == 0:
            # Classification describes the report; human decides its stored label.
            get(at.selectbox, "Confirmed report category").select("supply").run()
            get(at.checkbox, "I checked the original report and this category").check().run()
            get(at.button, "Save confirmed report").click().run()
            assert not at.exception
        records = report_intake.saved_reports(report_intake.inbox_path(target))
        assert len(records) == 1 and records[0]["original_text"] == text
        assert records[0]["suggestion"]["network_blocked"] is True
        assert records[0]["confirmed_category"] == "supply"
        with store.connect(target) as conn:
            assert len(store.all_events(conn)) == 5  # bundled packet A, no AI evidence writes
            assert not store.review_history(conn, "D2")
        report_ui.classifier().close()
        st.cache_resource.clear()
    output = {"passed": True, "external_python_network_blocked": True,
              "worker_network_blocked": True, "full_worker_restarts": 2,
              "inbox_persisted_across_restart": True, "classification_request_ms": timings,
              "temporary_database": str(target), "physical_wifi_off_test": "not performed"}
    result = ROOT / "verification/offline-model-check.json"
    result.parent.mkdir(parents=True, exist_ok=True)
    result.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
