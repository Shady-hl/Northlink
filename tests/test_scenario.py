"""Reference scenario from the brief (section 16), checked step by step.
Expected values come from the brief, not from the implementation's output."""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from northlink import handover, store
from northlink.impact import assess
from northlink.loader import InputError, load_file
from northlink.models import ReviewInput
from northlink.reconcile import IntegrityError, import_packet, import_plan
from northlink.reviews import save_review, set_clock

ROOT = Path(__file__).resolve().parent.parent
DEMO, BAD = ROOT / "scenarios" / "demo", ROOT / "scenarios" / "invalid"


def T(hm: str) -> datetime:
    h, m = hm.split(":")
    return datetime(2026, 10, 16, int(h), int(m), tzinfo=timezone.utc)


def cats(conn) -> dict[str, str]:
    now = store.scenario_time(conn)
    ev, cov = store.all_events(conn), store.all_coverage(conn)
    return {d.delivery_id: assess(d, ev, cov, now).category for d in store.deliveries(conn)}


def one(conn, did):
    d = {x.delivery_id: x for x in store.deliveries(conn)}[did]
    return assess(d, store.all_events(conn), store.all_coverage(conn), store.scenario_time(conn))


def snapshot(conn) -> dict:
    return {t: conn.execute(f"SELECT * FROM {t}").fetchall()
            for t in ("packets", "events", "coverage", "reviews", "review_cases", "audit", "meta")}


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "t.db"
    conn = store.connect(path)
    import_plan(conn, load_file(DEMO / "deliveries.json"))
    import_packet(conn, load_file(DEMO / "packet_A.json"))
    yield conn, path
    conn.close()


def test_initial_assessment_at_1200(db):
    conn, _ = db
    assert store.scenario_time(conn) == T("12:00")
    assert cats(conn) == {"D1": "advisory", "D2": "restriction", "D3": "conflict",
                          "D4": "no_match", "D5": "restriction", "D6": "no_match"}
    assert [e.event_id for e in one(conn, "D2").evidence] == ["E2"]
    # Expired E4 must not appear for D1; E1 does.
    assert [e.event_id for e in one(conn, "D1").evidence] == ["E1"]
    assert set(one(conn, "D3").conflicts) == {"C3-restriction-12to15"}
    # no_match is never phrased as safe
    assert "does not mean the route is safe" in " ".join(one(conn, "D4").reasons)


def test_full_reference_walkthrough(db):
    conn, path = db
    set_clock(conn, T("12:05"))
    rid = save_review(conn, ReviewInput(delivery_id="D2", person="Coordinator", decision="Hold for confirmation",
                                        note="Await road authority confirmation"))
    assert rid == "R1"
    conn.close()

    # Restart: new connection to the same file.
    conn = store.connect(path)
    assert store.scenario_time(conn) == T("12:05")
    case = store.review_case(conn, "D2")
    assert case["state"] == "reviewed" and case["current_review_id"] == "R1"
    r1 = store.review(conn, "R1")
    assert '"event_id": "E2"' in r1["evidence"] and '"revision": 1' in r1["evidence"]

    set_clock(conn, T("12:40"))
    d2 = one(conn, "D2")
    assert d2.category == "restriction"          # stale closure does not become open
    assert d2.stale                              # Evidence stale - recheck
    assert store.review_case(conn, "D2")["state"] == "reviewed"   # staleness alone does not reopen
    assert len(store.review_history(conn, "D2")) == 1
    d1 = one(conn, "D1")
    assert d1.stale and d1.category == "advisory"
    # Report origins: ages shown, no invented threshold, so not stale by policy.
    d3 = one(conn, "D3")
    assert d3.category == "conflict"
    rep = [c for c in d3.coverage if c.origin.startswith("demo-report")]
    assert rep and all(c.threshold_min is None and round(c.age_min) == 42 for c in rep)

    set_clock(conn, T("12:46"))
    res = import_packet(conn, load_file(DEMO / "packet_B.json"))
    assert res.reopened == ["D2"]
    case = store.review_case(conn, "D2")
    assert case["state"] == "reopened" and "E2" in case["reopened_reason"]
    assert store.review(conn, "R1")["decision"] == "Hold for confirmation"   # R1 preserved
    c = cats(conn)
    assert c["D2"] == "no_match" and c["D5"] == "no_match" and c["D3"] == "conflict"
    assert "does not mean the route is safe" in " ".join(one(conn, "D2").reasons)
    road = [x for x in one(conn, "D2").coverage if x.origin == "demo-road"][0]
    assert road.last_success == T("12:46")
    assert one(conn, "D1").stale  # weather still stale

    # Late E2 r1 at 12:48 must not revive the closure or reset the coverage clock.
    set_clock(conn, T("12:48"))
    import_packet(conn, load_file(DEMO / "packet_late_E2r1.json"))
    assert cats(conn)["D2"] == "no_match"
    road = [x for x in one(conn, "D2").coverage if x.origin == "demo-road"][0]
    assert road.last_success == T("12:46")
    weather = [x for x in one(conn, "D1").coverage if x.origin == "demo-weather"][0]
    assert weather.last_success == T("11:58")
    assert store.review_case(conn, "D2")["state"] == "reopened"
    assert len(store.review_history(conn, "D2")) == 1

    # Re-importing packet A and B: complete no-ops.
    before = snapshot(conn)
    assert import_packet(conn, load_file(DEMO / "packet_B.json")).duplicate
    assert import_packet(conn, load_file(DEMO / "packet_A.json")).duplicate
    assert snapshot(conn) == before
    reopen_audits = [a for a in store.audit_log(conn) if a["action"] == "review_reopened"]
    assert len(reopen_audits) == 1
    conn.close()


def test_reviewing_reopened_case_links_previous(db):
    conn, _ = db
    set_clock(conn, T("12:05"))
    save_review(conn, ReviewInput(delivery_id="D2", person="A", decision="Hold for confirmation"))
    set_clock(conn, T("12:46"))
    import_packet(conn, load_file(DEMO / "packet_B.json"))
    r2 = save_review(conn, ReviewInput(delivery_id="D2", person="A", decision="Proceed as planned", note="Closure cancelled"))
    assert store.review(conn, r2)["previous_review_id"] == "R1"
    assert [r["review_id"] for r in store.review_history(conn, "D2")] == ["R1", "R2"]
    assert store.review_case(conn, "D2")["state"] == "reviewed"


def test_malformed_packet_rejected_with_clear_errors(db):
    conn, _ = db
    with pytest.raises(InputError) as exc:
        load_file(BAD / "malformed_packet.json")
    text = " ".join(exc.value.problems)
    assert "retrieved_at" in text and "revision" in text and "status" in text


def test_reused_packet_id_with_changed_content_errors_atomically(db):
    conn, _ = db
    before = snapshot(conn)
    with pytest.raises(IntegrityError, match="different content"):
        import_packet(conn, load_file(BAD / "packet_A_changed_same_id.json"))
    assert snapshot(conn) == before


def test_reused_event_revision_with_changed_payload_errors_atomically(db):
    conn, _ = db
    p = load_file(DEMO / "packet_late_E2r1.json")
    changed = p.model_copy(update={"packet_id": "x-new", "events": [
        p.events[0].model_copy(update={"valid_until": T("16:00")})]})
    before = snapshot(conn)
    with pytest.raises(IntegrityError, match="new revision"):
        import_packet(conn, changed)
    assert snapshot(conn) == before


def test_handover_round_trip_preserves_history(db, tmp_path):
    conn, _ = db
    set_clock(conn, T("12:05"))
    save_review(conn, ReviewInput(delivery_id="D2", person="A", decision="Hold for confirmation", note="n"))
    set_clock(conn, T("12:46"))
    import_packet(conn, load_file(DEMO / "packet_B.json"))
    data = handover.export(conn)
    assert any(s["delivery_id"] == "D2" and s["review_state"] == "reopened" for s in data["summary"])

    fresh = store.connect(tmp_path / "other.db")
    handover.import_handover(fresh, data)
    for t in ("reviews", "review_cases", "events", "coverage"):
        q = f"SELECT * FROM {t} ORDER BY 1,2" if t != "coverage" else "SELECT packet_id, origin, scope_id, source_retrieved_at, successful, imported_at FROM coverage ORDER BY 1,2,3,4"
        assert [tuple(r) for r in fresh.execute(q)] == [tuple(r) for r in conn.execute(q)], t
    assert store.scenario_time(fresh) == T("12:46")
    assert cats(fresh) == cats(conn)
    # Importing again into the restored DB does not duplicate anything.
    n = fresh.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    handover.import_handover(fresh, data)
    assert fresh.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == n
