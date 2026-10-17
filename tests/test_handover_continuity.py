"""Independent checks: both fail on supplied Northlink snapshot 0c884f8.

Run with the intended project on PYTHONPATH and its existing Python environment.
Uses only temporary databases and synthetic bundled fixtures.
"""
import json
from pathlib import Path

import pytest

import northlink
from northlink import handover, store
from northlink.loader import load_file
from northlink.models import ReviewInput
from northlink.reconcile import import_packet, import_plan
from northlink.reviews import save_review


DEMO = Path(northlink.__file__).resolve().parent.parent / "scenarios" / "demo"


@pytest.fixture
def source(tmp_path):
    conn = store.connect(tmp_path / "source.db")
    import_plan(conn, load_file(DEMO / "deliveries.json"))
    import_packet(conn, load_file(DEMO / "packet_A.json"))
    save_review(conn, ReviewInput(
        delivery_id="D2", person="Laptop A reviewer",
        decision="Hold for confirmation", note="Keep this original decision",
    ))
    yield conn
    conn.close()


def test_malformed_nested_evidence_rejected_atomically(source, tmp_path):
    payload = handover.export(source)
    payload["reviews"][0]["evidence"] = "[{}]"
    fresh = store.connect(tmp_path / "fresh.db")
    try:
        before = "\n".join(fresh.iterdump())
        with pytest.raises(ValueError):
            handover.import_handover(fresh, payload)
        assert "\n".join(fresh.iterdump()) == before
    finally:
        fresh.close()


def test_foreign_review_survives_onward_handover(source, tmp_path):
    middle = store.connect(tmp_path / "middle.db")
    final = store.connect(tmp_path / "final.db")
    try:
        # A non-empty destination must retain its own authority and show A's
        # decisions as foreign comparison records.
        import_plan(middle, load_file(DEMO / "deliveries.json"))
        handover.import_handover(middle, handover.export(source))
        original = handover.foreign_reviews(middle, "D2")
        assert len(original) == 1

        # B's next snapshot must retain the decision it already displays.
        handover.import_handover(final, handover.export(middle))
        carried = handover.foreign_reviews(final, "D2")
        assert len(carried) == 1
        for field in ("review_id", "person", "decision", "note", "evidence"):
            assert carried[0][field] == original[0][field]
        assert store.review_case(final, "D2") is None
    finally:
        middle.close()
        final.close()
