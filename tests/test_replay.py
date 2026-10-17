"""Independent reference answers for the bundled real-notice replay."""
from datetime import datetime, timezone

import pytest

from northlink import briefing, handover, replay, store
from northlink.impact import assess
from northlink.models import ReviewInput
from northlink.reconcile import import_packet
from northlink.reviews import save_review


def cats(conn):
    return {d.delivery_id: assess(d, store.all_events(conn), store.all_coverage(conn), store.scenario_time(conn)).category
            for d in store.deliveries(conn)}


@pytest.fixture
def db(tmp_path):
    conn = store.connect(tmp_path / "replay.db")
    replay.prepare(conn)
    yield conn
    conn.close()


def test_original_cap_references_and_point_mapping():
    a, b, c = replay.notices()
    assert a.identifier == "2.49.0.1.578.0.20260422093451.031"
    assert a.identifier in b.references and b.identifier in c.references
    assert a.expires == datetime(2026, 4, 24, 7, tzinfo=timezone.utc)
    assert b.expires == datetime(2026, 4, 24, 9, tzinfo=timezone.utc)
    assert all(replay.contains(n.geometry, 31.1, 70.3) for n in (a, b, c))
    assert not any(replay.contains(n.geometry, 18.96, 69.65) for n in (a, b, c))


def test_point_boundaries_and_polygon_holes():
    square = {"type": "Polygon", "coordinates": [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
                                                    [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]]}
    assert replay.contains(square, 0, 2)
    assert replay.contains(square, 0.5, 0.5)
    assert not replay.contains(square, 2, 2)
    assert not replay.contains(square, 5, 2)


def test_reference_categories_before_and_after_update(db):
    assert cats(db) == {"F1": "no_match", "F2": "advisory", "F3": "no_match",
                        "F4": "no_match", "F5": "advisory", "F6": "no_match"}
    replay.advance(db, 1)
    assert cats(db) == {"F1": "advisory", "F2": "advisory", "F3": "no_match",
                        "F4": "no_match", "F5": "advisory", "F6": "no_match"}


def test_material_update_reopens_only_affected_review_and_preserves_history(db):
    r1 = save_review(db, ReviewInput(delivery_id="F1", person="A", decision="Hold for confirmation", note="Check next source update"))
    save_review(db, ReviewInput(delivery_id="F3", person="B", decision="Hold for confirmation"))
    result = replay.advance(db, 1)
    assert result.reopened == ["F1"]
    assert store.review_case(db, "F3")["state"] == "reviewed"
    assert store.review(db, r1)["note"] == "Check next source update"
    save_review(db, ReviewInput(delivery_id="F1", person="A", decision="Delay departure"))
    assert replay.advance(db, 2).reopened == []  # same applicability, corrected text
    assert store.review_case(db, "F1")["state"] == "reviewed"
    before = len(store.audit_log(db))
    assert import_packet(db, replay.packet(1)).duplicate
    assert len(store.audit_log(db)) == before
    assert cats(db)["F1"] == "advisory"


def test_prepare_never_resets_reviewed_run(db):
    save_review(db, ReviewInput(delivery_id="F1", person="A", decision="Hold for confirmation"))
    replay.advance(db, 1)
    before = "\n".join(db.iterdump())
    assert not replay.prepare(db)
    assert "\n".join(db.iterdump()) == before


def test_recorded_handover_and_readable_brief_survive_restart(db, tmp_path):
    save_review(db, ReviewInput(delivery_id="F1", person="A", decision="Hold for confirmation"))
    replay.advance(db, 1)
    export = handover.export(db)
    fresh = store.connect(tmp_path / "handover.db")
    handover.import_handover(fresh, export)
    assert cats(fresh) == cats(db)
    assert store.review_case(fresh, "F1")["state"] == "reopened"
    report = briefing.build(fresh)
    assert "deterministic template" in report
    assert "Reconsideration required" in report and "Hold for confirmation" in report
    assert replay.notices()[1].source_url in report
    assert "Archived weather is a replay" in report
    fresh.close()


@pytest.mark.parametrize("field,value", [
    ("evidence", "[{}]"), ("fingerprint", "[{}]"),
    ("stale_at_review", "[null]"), ("scenario_time", "2026-04-23T08:00:00"),
])
def test_nested_bad_handover_is_rejected_before_writing(db, tmp_path, field, value):
    save_review(db, ReviewInput(delivery_id="F1", person="A", decision="Hold for confirmation"))
    payload = handover.export(db)
    payload["reviews"][0][field] = value
    fresh = store.connect(tmp_path / "empty.db")
    before = "\n".join(fresh.iterdump())
    with pytest.raises(ValueError):
        handover.import_handover(fresh, payload)
    assert "\n".join(fresh.iterdump()) == before
    fresh.close()


def test_same_second_long_review_history_restores_in_parent_order(db, tmp_path, monkeypatch):
    fixed = datetime(2026, 10, 16, 16, tzinfo=timezone.utc)
    monkeypatch.setattr(store, "now_wall", lambda: fixed)
    for _ in range(12):
        save_review(db, ReviewInput(delivery_id="F1", person="A", decision="Hold for confirmation"))
    fresh = store.connect(tmp_path / "long-history.db")
    handover.import_handover(fresh, handover.export(db))
    assert fresh.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 12
    assert store.review_case(fresh, "F1")["current_review_id"] == "R12"
    fresh.close()
