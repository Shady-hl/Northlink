"""Bundled MET replay. Real notices; fictional site-level delivery exercise.

No networking. CAP references establish the update chain. Source acquisition time
is preserved; the replay clock does not invent historical source fetches.
"""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from . import store
from .models import DeliveryPlan, Event, Packet
from .reconcile import import_packet, import_packet_tx, import_plan_tx
from .reviews import set_clock

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "scenarios" / "recorded" / "finnmark-polar-low"
NS = {"c": "urn:oasis:names:tc:emergency:cap:1.2"}
ORIGIN = "met-metalerts-recorded"
START = datetime(2026, 4, 23, 8, 0, tzinfo=timezone.utc)
SITES = {
    "FN-VARANGER": {"label": "Varanger exercise point", "lon": 31.1, "lat": 70.3},
    "FN-TROMS": {"label": "Troms comparison point", "lon": 18.96, "lat": 69.65},
}
TITLES = {
    "F1": "Essential supplies · morning arrival",
    "F2": "Equipment · daytime arrival",
    "F3": "Medical supplies · comparison site",
    "F4": "Food supplies · later arrival",
    "F5": "Spare parts · early arrival",
    "F6": "Fuel supplies · comparison site",
}


def point_in_ring(lon: float, lat: float, ring: list) -> bool:
    """Ray casting with boundary included. GeoJSON coordinates are lon, lat."""
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        x1, y1 = a[:2]
        x2, y2 = b[:2]
        cross = (lon - x1) * (y2 - y1) - (lat - y1) * (x2 - x1)
        if abs(cross) < 1e-9 and min(x1, x2) <= lon <= max(x1, x2) and min(y1, y2) <= lat <= max(y1, y2):
            return True
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def contains(geometry: dict, lon: float, lat: float) -> bool:
    polys = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    return any(point_in_ring(lon, lat, p[0]) and not any(point_in_ring(lon, lat, h) for h in p[1:]) for p in polys)


@dataclass(frozen=True)
class Notice:
    identifier: str
    sent: datetime
    onset: datetime
    expires: datetime
    message_type: str
    references: tuple[str, ...]
    headline: str
    description: str
    geometry: dict
    source_url: str
    revision: int


@lru_cache(maxsize=1)
def notices() -> tuple[Notice, ...]:
    manifest = json.loads((FIXTURE / "manifest.json").read_text())
    for entry in manifest["files"]:
        if hashlib.sha256((FIXTURE / entry["path"]).read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("Recorded MET source file failed its integrity check")
    features = {f["properties"]["id"]: f for f in json.loads((FIXTURE / "source.geojson").read_text())["features"]}
    parsed = []
    for rec in manifest["notices"]:
        element = ET.fromstring((FIXTURE / rec["path"]).read_bytes())
        def text(name):
            return element.findtext("c:" + name, namespaces=NS)
        infos = element.findall("c:info", NS)
        info = next((i for i in infos if (i.findtext("c:language", namespaces=NS) or "").startswith("en")), infos[0])
        def it(name):
            return info.findtext("c:" + name, namespaces=NS)
        ident = text("identifier")
        if text("status") != "Actual" or ident != rec["id"]:
            raise ValueError("Unexpected source identity or status in MET replay")
        refs = tuple(r.split(",")[1] for r in (text("references") or "").split())
        parsed.append(Notice(ident, store.parse(text("sent")), store.parse(it("onset")),
                             store.parse(it("expires")), text("msgType"), refs,
                             it("headline") or "Weather warning", it("description") or "",
                             features[ident]["geometry"], rec["source_url"], 0))
    parsed.sort(key=lambda n: n.sent)
    known = set()
    result = []
    for index, n in enumerate(parsed):
        if index == 0 and n.message_type != "Alert":
            raise ValueError("Replay must begin with an original Alert")
        if index and (n.message_type != "Update" or not known.intersection(n.references)):
            raise ValueError("MET update does not reference the verified earlier notice")
        known.add(n.identifier)
        result.append(Notice(**{**n.__dict__, "revision": index + 1}))
    return tuple(result)


def packet(index: int) -> Packet:
    n = notices()[index]
    manifest = json.loads((FIXTURE / "manifest.json").read_text())
    events = []
    for site_id, site in SITES.items():
        inside = contains(n.geometry, site["lon"], site["lat"])
        events.append(Event(
            event_id=notices()[0].identifier + "@" + site_id,
            revision=n.revision, origin=ORIGIN,
            corridor_id=site_id if inside else "OUTSIDE:" + site_id,
            published_at=n.sent, valid_from=n.onset, valid_until=n.expires,
            event_type="warning", status="active",
            supersedes_revision=n.revision - 1 if n.revision > 1 else None,
            source_url=n.source_url,
            text=f"MET CAP {n.identifier} ({n.message_type}). {n.headline}\n{n.description}\n"
                 f"Site mapping: {site['label']} at {site['lat']} N, {site['lon']} E is "
                 f"{'inside' if inside else 'outside'} this recorded warning polygon. "
                 "This is point exposure, not a road closure or a whole-route assessment.",
        ))
    return Packet(schema_version=1, packet_id="recorded-finnmark-" + n.identifier,
                  kind="recorded", retrieved_at=store.parse(manifest["retrieved_at"]),
                  label="Historical MET notice; local replay, fictional deliveries", events=events)


def plan() -> DeliveryPlan:
    def d(ident, site, start, end, priority):
        return {"delivery_id": ident, "corridor_id": site,
                "window_start": start, "window_end": end,
                "priority": priority, "deadline": end,
                "requirements": [TITLES[ident], "Fictional delivery; site-level weather exposure only"]}
    return DeliveryPlan.model_validate({
        "schema_version": 1, "plan_id": "fictional-finnmark-exercise-v1", "kind": "synthetic",
        "label": "Fictional preparedness deliveries at reviewed geographic points",
        "deliveries": [
            d("F1", "FN-VARANGER", "2026-04-24T08:00:00Z", "2026-04-24T08:30:00Z", "High"),
            d("F2", "FN-VARANGER", "2026-04-23T12:00:00Z", "2026-04-23T13:00:00Z", "High"),
            d("F3", "FN-TROMS", "2026-04-23T12:00:00Z", "2026-04-23T13:00:00Z", "Medium"),
            d("F4", "FN-VARANGER", "2026-04-24T10:00:00Z", "2026-04-24T11:00:00Z", "Normal"),
            d("F5", "FN-VARANGER", "2026-04-24T06:30:00Z", "2026-04-24T07:30:00Z", "Normal"),
            d("F6", "FN-TROMS", "2026-04-24T08:00:00Z", "2026-04-24T08:30:00Z", "Normal"),
        ],
    })


def prepare(conn) -> bool:
    if store.deliveries(conn):
        return False  # never reset an existing run or its decisions
    with store.transaction(conn):
        store.set_scenario_time_tx(conn, START)
        import_plan_tx(conn, plan())
        import_packet_tx(conn, packet(0))
    return True


def advance(conn, index: int):
    n = notices()[index]
    # Arrival times here are replay controls, not measured historical polling.
    target = n.sent.replace(second=0, microsecond=0)
    from datetime import timedelta
    target += timedelta(minutes=1)
    if store.scenario_time(conn) < target:
        set_clock(conn, target)
    return import_packet(conn, packet(index))
