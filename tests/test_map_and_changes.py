"""Map data and evidence-derived before/after differences (recorded and synthetic)."""
import json
import re

import pytest

from northlink import changes, replay, store, visuals
from northlink.loader import SCENARIO_DIR, load_file
from northlink.reconcile import import_packet, import_plan


@pytest.fixture
def finn(tmp_path):
    conn = store.connect(tmp_path / "map.db")
    replay.prepare(conn)
    yield conn
    conn.close()


def delivery(conn, ident):
    return next(d for d in store.deliveries(conn) if d.delivery_id == ident)


def test_f1_difference_comes_from_stored_revisions(finn):
    f1 = delivery(finn, "F1")
    assert changes.for_delivery(f1, store.all_events(finn)) == []
    replay.advance(finn, 1)
    (ch,) = changes.for_delivery(f1, store.all_events(finn))
    assert (ch.from_revision, ch.to_revision) == (1, 2)
    assert ("Valid until", "24 Apr 07:00 UTC", "24 Apr 09:00 UTC") in ch.fields
    assert ("Valid from", "23 Apr 06:00 UTC", "23 Apr 09:00 UTC") in ch.fields
    assert not ch.overlap_before and ch.overlap_after
    assert ch.summary == "Now overlaps this delivery window"


def test_text_only_update_is_shown_as_not_material(finn):
    replay.advance(finn, 1)
    replay.advance(finn, 2)
    last = changes.for_delivery(delivery(finn, "F1"), store.all_events(finn))[-1]
    assert (last.from_revision, last.to_revision) == (2, 3)
    assert not last.material and last.overlap_before and last.overlap_after


def test_outside_site_change_keeps_two_point_semantics(finn):
    replay.advance(finn, 1)
    (ch,) = changes.for_delivery(delivery(finn, "F6"), store.all_events(finn))
    assert not ch.overlap_before and not ch.overlap_after
    assert all(label != "Scope" for label, _, _ in ch.fields)   # Troms stays outside


def test_synthetic_cancellation_difference(tmp_path):
    conn = store.connect(tmp_path / "syn.db")
    import_plan(conn, load_file(SCENARIO_DIR / "deliveries.json"))
    import_packet(conn, load_file(SCENARIO_DIR / "packet_A.json"))
    import_packet(conn, load_file(SCENARIO_DIR / "packet_B.json"))
    (ch,) = changes.for_delivery(delivery(conn, "D2"), store.all_events(conn))
    assert ch.event_id == "E2" and ("Status", "active", "cancelled") in ch.fields
    assert ch.overlap_before and not ch.overlap_after
    conn.close()


def test_recorded_map_is_local_attributed_and_links_sites(finn):
    replay.advance(finn, 1)
    n = replay.notices()
    sites = {k: {**v, "note": "fictional"} for k, v in replay.SITES.items()}
    groups = {"FN-VARANGER": [{"id": "F1"}], "FN-TROMS": [{"id": "F3"}]}
    data = visuals.recorded_map(n[1].geometry, n[0].geometry, sites, groups, "F1", "FN-VARANGER", "status", "k")
    blob = json.dumps(data)
    assert not re.search(r"https?://|//cdn|@import|<script", blob)
    assert "Natural Earth" in data["attribution"] and "MET Norway" in data["attribution"]
    assert "fictional" in data["attribution"].lower()
    assert {m["id"] for m in data["markers"]} == {"FN-VARANGER", "FN-TROMS"}
    assert data["selected_marker"] == "FN-VARANGER" and data["has_previous"]
    assert 'class="warning"' in data["layers"] and 'class="previous"' in data["layers"]
    assert {"Tromsø", "Vadsø", "Kirkenes", "Hammerfest"} <= {p["name"] for p in data["places"]}
    # Varanger exercise point sits inside the fit view; the polygon drives the fit.
    x, y = visuals.proj(31.1, 70.3)
    fx, fy, fw, fh = data["fit_view"]
    assert fx < x < fx + fw and fy < y < fy + fh


def test_map_component_source_has_no_remote_references():
    from pathlib import Path
    src = (Path(visuals.__file__).parent / "mapview.py").read_text()
    assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)", src)
    assert "fetch(" not in src and "XMLHttpRequest" not in src and "import(" not in src
