"""Regression cases for the correctness review (H1-H3, M1-M5, L1-L3)."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from northlink import handover, store
from northlink.impact import assess
from northlink.loader import load_file
from northlink.models import Packet, ReviewInput
from northlink.reconcile import IntegrityError, import_packet, import_plan
from northlink.reviews import save_review, set_clock

DEMO = Path(__file__).resolve().parent.parent / "scenarios" / "demo"


def T(hm):
    h, m = hm.split(":")
    return datetime(2026, 10, 16, int(h), int(m), tzinfo=timezone.utc)


@pytest.fixture
def conn(tmp_path):
    c = store.connect(tmp_path / "r.db")
    import_plan(c, load_file(DEMO / "deliveries.json"))
    import_packet(c, load_file(DEMO / "packet_A.json"))
    yield c
    c.close()


def a(c, did):
    d = {x.delivery_id: x for x in store.deliveries(c)}[did]
    return assess(d, store.all_events(c), store.all_coverage(c), store.scenario_time(c))


def pkt(pid, events, coverage=(), kind="synthetic", retrieved="12:00"):
    return Packet.model_validate({"schema_version": 1, "packet_id": pid, "kind": kind,
                                  "retrieved_at": f"2026-10-16T{retrieved}:00Z",
                                  "coverage": list(coverage), "events": events})


def ev(eid, **kw):
    base = {"event_id": eid, "revision": 1, "origin": "demo-road", "corridor_id": "C1",
            "published_at": "2026-10-16T11:00:00Z", "valid_from": "2026-10-16T16:00:00Z",
            "valid_until": "2026-10-16T19:00:00Z", "event_type": "report", "status": "active"}
    return base | kw


def snapshot(c):
    return {t: c.execute(f"SELECT * FROM {t}").fetchall()
            for t in ("packets", "events", "coverage", "reviews", "review_cases", "audit", "meta", "foreign_reviews")}


# H3 ----------------------------------------------------------------------
@pytest.mark.parametrize("extra", [{}, {"claim_key": "C1-x", "claim_value": "reported_open"}, {"event_type": "other"}])
def test_unclassified_matching_record_is_not_no_match(conn, extra):
    import_packet(conn, pkt("p-h3", [ev("U1", **extra)]))
    r = a(conn, "D4")
    assert r.category == "needs_confirmation"
    assert "U1" in " ".join(r.reasons)


def test_unlocated_active_event_needs_confirmation_everywhere(conn):
    import_packet(conn, pkt("p-h3b", [ev("U2", corridor_id=None, event_type="closure")]))
    assert all(a(conn, d).category in ("needs_confirmation", "conflict", "restriction", "advisory")
               for d in ("D1", "D2", "D3", "D4", "D5", "D6"))
    assert a(conn, "D6").category == "needs_confirmation"


# M1 ----------------------------------------------------------------------
def test_staleness_appears_at_1240_not_1200(conn):
    assert not a(conn, "D1").stale and not a(conn, "D2").stale
    assert a(conn, "D2").gap_reasons == ["demo-weather/C2: not checked"]
    set_clock(conn, T("12:40"))
    assert a(conn, "D1").stale and a(conn, "D2").stale


# M2 ----------------------------------------------------------------------
def test_future_dated_coverage_is_rejected_or_ignored(conn):
    with pytest.raises(ValidationError, match="later than"):
        pkt("p-fut", [], [{"origin": "demo-weather", "scope_id": "C1",
                           "source_retrieved_at": "2026-10-17T00:00:00Z", "successful": True}])
    # Packet B imported while the clock is still 12:00: its 12:46 coverage is not yet valid.
    import_packet(conn, load_file(DEMO / "packet_B.json"))
    road = [c for c in a(conn, "D2").coverage if c.origin == "demo-road"][0]
    assert road.last_success == T("11:58")
    set_clock(conn, T("12:50"))
    road = [c for c in a(conn, "D2").coverage if c.origin == "demo-road"][0]
    assert road.last_success == T("12:46")


# M3 ----------------------------------------------------------------------
def test_kind_and_origin_must_agree(conn):
    with pytest.raises(ValidationError, match="does not match packet kind"):
        pkt("p-l", [ev("F1", source_url="https://www.vegvesen.no/fake")], kind="live")
    with pytest.raises(ValidationError, match="does not match packet kind"):
        pkt("p-s", [ev("F2", origin="met-metalerts")])
    live = pkt("p-live", [ev("F3", origin="met-metalerts")], kind="live")
    with pytest.raises(IntegrityError, match="live"):
        import_packet(conn, live)


# H1/H2/L1 ----------------------------------------------------------------
def _export_with_review(c):
    set_clock(c, T("12:05"))
    save_review(c, ReviewInput(delivery_id="D2", person="A", decision="Hold for confirmation"))
    return handover.export(c)


@pytest.mark.parametrize("mutate", [
    lambda d: d["reviews"][0].update({"review_id,person) SELECT 1,2 --": "x"}),
    lambda d: d["reviews"][0].update({"bogus": 1}),
    lambda d: d["reviews"][0].update({"category": "zzz"}),
    lambda d: d["reviews"][0].update({"fingerprint": "{bad"}),
    lambda d: d.pop("reviews"),
    lambda d: d.pop("scenario_time"),
    lambda d: d["reviews"].append(dict(d["reviews"][0])),
    lambda d: d["review_cases"][0].update({"current_review_id": "R99"}),
])
def test_bad_handover_rejected_without_change(conn, tmp_path, mutate):
    data = _export_with_review(conn)
    mutate(data)
    fresh = store.connect(tmp_path / "f.db")
    before = snapshot(fresh)
    with pytest.raises(ValueError, match="Nothing was imported"):
        handover.import_handover(fresh, json.loads(json.dumps(data)))
    assert snapshot(fresh) == before


# M4/L2 -------------------------------------------------------------------
def test_restore_keeps_local_audit_and_plan_times(conn, tmp_path):
    data = _export_with_review(conn)
    fresh = store.connect(tmp_path / "f.db")
    set_clock(fresh, T("12:01"))
    n_local = fresh.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    assert n_local == 1
    handover.import_handover(fresh, data)
    assert fresh.execute("SELECT COUNT(*) FROM audit WHERE action='clock_set' AND detail LIKE '%12:01%'").fetchone()[0] == 1
    assert [tuple(r) for r in fresh.execute("SELECT plan_id, imported_at FROM plans")] == \
           [tuple(r) for r in conn.execute("SELECT plan_id, imported_at FROM plans")]


# M5 ----------------------------------------------------------------------
def test_repeated_handovers_do_not_duplicate_foreign_reviews(conn, tmp_path):
    data1 = _export_with_review(conn)
    data2 = handover.export(conn, exported_by="again")
    assert data1["handover_id"] != data2["handover_id"]
    other = store.connect(tmp_path / "o.db")
    import_plan(other, load_file(DEMO / "deliveries.json"))
    handover.import_handover(other, data1)
    handover.import_handover(other, data2)
    assert other.execute("SELECT COUNT(*) FROM foreign_reviews").fetchone()[0] == 1


# L3 ----------------------------------------------------------------------
def test_unknown_superseded_revision_warns(conn):
    r = import_packet(conn, pkt("p-l3", [ev("ZZ", revision=4, supersedes_revision=2)]))
    assert r.warnings and "r2" in r.warnings[0]
