"""Queue navigation must not mutate assessments or lose a selected review."""
import importlib
from pathlib import Path
from unittest.mock import Mock
from streamlit.testing.v1 import AppTest


def get(items, label):
    return next(item for item in items if item.label == label)


def test_filter_preserves_selected_delivery_and_queue_pick_links_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("NORTHLINK_DB", str(tmp_path / "desk.db"))
    from northlink import store, report_intake
    importlib.reload(store)
    monkeypatch.setattr(report_intake.subprocess, "Popen", Mock(side_effect=AssertionError("Unexpected model start")))
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30).run()
    get(at.button, "Load demo plan + packet A").click().run()
    get(at.selectbox, "Inspect delivery").select("D2").run()
    get(at.selectbox, "Queue filter").select("Conflicting").run()
    assert get(at.selectbox, "Inspect delivery").value == "D2"
    assert any("Inspecting D2 outside this filter" in c.value for c in at.caption)
    assert not any(b.label.startswith("D2  ·") for b in at.button)
    next(b for b in at.button if b.label.startswith("D3  ·")).click().run()
    assert get(at.selectbox, "Inspect delivery").value == "D3"
    assert at.session_state["toolbox-inspect_synthetic"] == "Review"
    get(at.selectbox, "Queue filter").select("Reopened").run()
    assert get(at.selectbox, "Inspect delivery").value == "D3"
    assert any("No deliveries match" in c.value for c in at.caption)
    with store.connect(tmp_path / "desk.db") as conn:
        assert not store.review_cases(conn)
    get(at.selectbox, "Queue filter").select("All").run()
    get(at.text_input, "Find delivery").input("D2").run()
    assert get(at.selectbox, "Inspect delivery").value == "D3"
    assert any(b.label.startswith("D2  ·") for b in at.button)
    assert not any(b.label.startswith("D1  ·") for b in at.button)
    assert not at.exception


def test_integrity_lab_uses_disposable_copy_and_preserves_source(tmp_path):
    from northlink import deskview, store
    from northlink.loader import SCENARIO_DIR, load_file
    from northlink.reconcile import import_packet, import_plan
    from northlink.reviews import save_review
    from northlink.models import ReviewInput
    conn = store.connect(tmp_path / "integrity.db")
    try:
        import_plan(conn, load_file(SCENARIO_DIR / "deliveries.json"))
        import_packet(conn, load_file(SCENARIO_DIR / "packet_A.json"))
        save_review(conn, ReviewInput(delivery_id="D2", person="Exercise", decision="Hold for confirmation"))
        before = list(conn.iterdump())
        results = deskview.run_integrity_checks(conn)
        assert len(results) == 3 and all(r["passed"] for r in results)
        assert list(conn.iterdump()) == before
        assert store.review_case(conn, "D2")["state"] == "reviewed"
    finally:
        conn.close()


def test_fit_contains_full_warning_previous_outline_and_sites():
    from northlink import replay, visuals
    current, previous = replay.notices()[1], replay.notices()[0]
    data = visuals.recorded_map(current.geometry, previous.geometry,
                               {k: {**v, "note": "Exercise"} for k, v in replay.SITES.items()},
                               {}, "F1", "FN-VARANGER", "Recorded", "fit-check")
    x0, y0, width, height = data["fit_view"]
    points = [p for geometry in (current.geometry, previous.geometry)
              for ring in visuals._rings(geometry) for p in ring]
    points += [(s["lon"], s["lat"]) for s in replay.SITES.values()]
    for lon, lat in points:
        x, y = visuals.proj(lon, lat)
        assert x0 <= x <= x0 + width and y0 <= y <= y0 + height
