"""Workspace isolation: wrong-workspace and mixed payloads are rejected with no mutation.

Every rejection test compares a full snapshot of every table (including meta and
audit) before and after the attempt. Each rejection has a valid same-workspace
control so the tests cannot pass merely because imports are broken.
"""
import copy
import json

import pytest

from northlink import handover, replay, store
from northlink.loader import SCENARIO_DIR, load_file
from northlink.models import DeliveryPlan, Packet
from northlink.reconcile import import_packet, import_plan
from northlink.workspace import FINNMARK, SYNTHETIC, classify, guarded_import, mismatch

TABLES = ("meta", "packets", "events", "coverage", "plans", "deliveries", "reviews",
          "review_cases", "foreign_reviews", "audit")


def snapshot(conn) -> dict:
    return {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY rowid")] for t in TABLES}


def delivery_ids(conn) -> list[str]:
    return [d.delivery_id for d in store.deliveries(conn)]


@pytest.fixture
def finnmark_db(tmp_path):
    conn = store.connect(tmp_path / "finnmark.db")
    replay.prepare(conn)
    yield conn
    conn.close()


@pytest.fixture
def synthetic_db(tmp_path):
    conn = store.connect(tmp_path / "synthetic.db")
    import_plan(conn, load_file(SCENARIO_DIR / "deliveries.json"))
    import_packet(conn, load_file(SCENARIO_DIR / "packet_A.json"))
    yield conn
    conn.close()


@pytest.fixture
def synthetic_plan_only_handover(tmp_path):
    """The independently reported reproducer: valid handover, one synthetic plan, no packets."""
    src = store.connect(tmp_path / "plan-only-src.db")
    import_plan(src, load_file(SCENARIO_DIR / "deliveries.json"))
    payload = handover.export(src)
    src.close()
    assert len(payload["plans"]) == 1 and payload["packets"] == []
    return payload


@pytest.fixture
def finnmark_handover(tmp_path):
    src = store.connect(tmp_path / "finnmark-src.db")
    replay.prepare(src)
    payload = handover.export(src)
    src.close()
    return payload


def assert_rejected(conn, obj, workspace, source="file.json"):
    before = snapshot(conn)
    level, message = guarded_import(conn, obj, workspace, source)
    assert level == "error", message
    assert "nothing changed" in message.lower()
    assert snapshot(conn) == before
    return message


# ---------------------------------------------------------------- rejections

def test_plan_only_synthetic_handover_rejected_in_finnmark(finnmark_db, synthetic_plan_only_handover):
    msg = assert_rejected(finnmark_db, synthetic_plan_only_handover, FINNMARK)
    assert "Synthetic exercise" in msg
    assert delivery_ids(finnmark_db) == ["F1", "F2", "F3", "F4", "F5", "F6"]


def test_synthetic_packet_only_handover_rejected_in_finnmark(finnmark_db, tmp_path):
    src = store.connect(tmp_path / "packet-only.db")
    import_packet(src, load_file(SCENARIO_DIR / "packet_A.json"))
    payload = handover.export(src)
    src.close()
    assert payload["plans"] == [] and payload["packets"]
    assert_rejected(finnmark_db, payload, FINNMARK)


def test_finnmark_handover_and_records_rejected_in_synthetic(synthetic_db, finnmark_handover):
    assert_rejected(synthetic_db, finnmark_handover, SYNTHETIC)
    assert_rejected(synthetic_db, replay.plan(), SYNTHETIC)
    assert_rejected(synthetic_db, replay.packet(1), SYNTHETIC)
    assert delivery_ids(synthetic_db) == ["D1", "D2", "D3", "D4", "D5", "D6"]


def test_direct_synthetic_records_rejected_in_finnmark(finnmark_db):
    assert_rejected(finnmark_db, load_file(SCENARIO_DIR / "deliveries.json"), FINNMARK)
    for name in ("packet_A.json", "packet_B.json", "packet_late_E2r1.json"):
        assert_rejected(finnmark_db, load_file(SCENARIO_DIR / name), FINNMARK)


def test_mixed_handover_rejected_in_both_workspaces(finnmark_db, synthetic_db, finnmark_handover):
    mixed = copy.deepcopy(finnmark_handover)
    mixed["packets"].append(json.loads(load_file(SCENARIO_DIR / "packet_A.json").model_dump_json()))
    assert classify(mixed) == {FINNMARK, SYNTHETIC}
    assert "both" in assert_rejected(finnmark_db, mixed, FINNMARK)
    assert "both" in assert_rejected(synthetic_db, mixed, SYNTHETIC)


def test_mixed_plan_with_fn_and_synthetic_corridors_rejected(finnmark_db, synthetic_db):
    raw = json.loads(replay.plan().model_dump_json())
    raw["plan_id"] = "mixed-plan"
    raw["deliveries"].append({**raw["deliveries"][0], "delivery_id": "X1", "corridor_id": "C1"})
    plan = DeliveryPlan.model_validate(raw)
    assert classify(plan) == {FINNMARK, SYNTHETIC}
    assert_rejected(finnmark_db, plan, FINNMARK)
    assert_rejected(synthetic_db, plan, SYNTHETIC)


def test_mixed_packet_rejected(finnmark_db, synthetic_db):
    raw = json.loads((SCENARIO_DIR / "packet_A.json").read_text())
    raw["packet_id"] = "synthetic-pointing-at-finnmark"
    raw["events"][0]["corridor_id"] = "FN-VARANGER"
    packet = Packet.model_validate(raw)
    assert classify(packet) == {FINNMARK, SYNTHETIC}
    assert_rejected(finnmark_db, packet, FINNMARK)
    assert_rejected(synthetic_db, packet, SYNTHETIC)


# ---------------------------------------------------------------- valid controls

def test_control_same_workspace_imports_are_accepted(tmp_path, synthetic_plan_only_handover, finnmark_db):
    empty = store.connect(tmp_path / "empty-synthetic.db")
    level, msg = guarded_import(empty, synthetic_plan_only_handover, SYNTHETIC, "h.json")
    assert level == "success", msg
    assert delivery_ids(empty) == ["D1", "D2", "D3", "D4", "D5", "D6"]
    level, msg = guarded_import(empty, load_file(SCENARIO_DIR / "packet_A.json"), SYNTHETIC, "packet_A.json")
    assert level == "success", msg
    empty.close()

    before = snapshot(finnmark_db)
    level, msg = guarded_import(finnmark_db, replay.packet(1), FINNMARK, "update1")
    assert level == "success", msg
    assert snapshot(finnmark_db) != before
    assert mismatch(replay.plan(), FINNMARK) is None


def test_control_finnmark_handover_restores_into_empty_finnmark(tmp_path, finnmark_handover):
    empty = store.connect(tmp_path / "empty-finnmark.db")
    level, msg = guarded_import(empty, finnmark_handover, FINNMARK, "h.json")
    assert level == "success", msg
    assert delivery_ids(empty) == ["F1", "F2", "F3", "F4", "F5", "F6"]
    empty.close()


def test_neutral_payload_has_no_workspace_signal():
    assert classify({"plans": [], "packets": []}) == set()
    assert mismatch({"plans": [], "packets": []}, FINNMARK) is None
