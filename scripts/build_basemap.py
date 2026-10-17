"""Build the bundled offline basemap for the High North map view.

Run once while connected (inputs are Natural Earth 1:10m GeoJSON files, public domain):

    curl -O https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_land.geojson
    curl -O https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_boundary_lines_land.geojson
    curl -O https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_lakes.geojson
    curl -O https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_populated_places_simple.geojson
    python scripts/build_basemap.py <dir-with-those-files>

Output: assets/basemap-high-north.json. The app only reads that file; it never
downloads map data. Pure Python: rectangle clipping (Sutherland-Hodgman) and
Douglas-Peucker simplification in a local equirectangular projection.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "basemap-high-north.json"
BBOX = (5.0, 65.5, 45.0, 74.5)           # lon0, lat0, lon1, lat1
LAT0 = 70.0
KX = math.cos(math.radians(LAT0))        # x stretch for a local equirectangular view
TOLERANCE = 0.0045                       # projected degrees of latitude (~500 m)
MIN_AREA = 0.0006                        # drop tiny islets/lakes (projected deg^2)
SOURCES = {
    "land": "ne_10m_land.geojson",
    "borders": "ne_10m_admin_0_boundary_lines_land.geojson",
    "lakes": "ne_10m_lakes.geojson",
    "places": "ne_10m_populated_places_simple.geojson",
}
URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"


def clip_ring(ring, bbox):
    x0, y0, x1, y1 = bbox
    def clip(points, inside, cut):
        out = []
        for i, cur in enumerate(points):
            prev = points[i - 1]
            if inside(cur):
                if not inside(prev):
                    out.append(cut(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cut(prev, cur))
        return out
    def at_x(x):
        return lambda a, b: (x, a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]))
    def at_y(y):
        return lambda a, b: (a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]), y)
    pts = [tuple(p[:2]) for p in ring[:-1]] if ring[0] == ring[-1] else [tuple(p[:2]) for p in ring]
    for inside, cut in ((lambda p: p[0] >= x0, at_x(x0)), (lambda p: p[0] <= x1, at_x(x1)),
                        (lambda p: p[1] >= y0, at_y(y0)), (lambda p: p[1] <= y1, at_y(y1))):
        if not pts:
            break
        pts = clip(pts, inside, cut)
    return pts


def proj(p):
    return ((p[0] - 25.0) * KX, p[1] - LAT0)


def dp(points, tol):
    """Douglas-Peucker on projected coordinates; endpoints kept."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    pp = [proj(p) for p in points]
    while stack:
        a, b = stack.pop()
        ax, ay = pp[a]
        bx, by = pp[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy) or 1e-12
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            px, py = pp[i]
            d = abs(dy * (px - ax) - dx * (py - ay)) / norm
            if d > best:
                best, idx = d, i
        if best > tol:
            keep[idx] = True
            stack.extend([(a, idx), (idx, b)])
    return [p for p, k in zip(points, keep) if k]


def area(ring):
    pp = [proj(p) for p in ring]
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pp, pp[1:] + pp[:1]))) / 2


def on_edge(p, bbox):
    x0, y0, x1, y1 = bbox
    return abs(p[0] - x0) < 1e-9 or abs(p[0] - x1) < 1e-9 or abs(p[1] - y0) < 1e-9 or abs(p[1] - y1) < 1e-9


def simplify_ring(ring):
    # Split into an open chain so Douglas-Peucker keeps a stable start point.
    if len(ring) < 4:
        return ring
    far = max(range(len(ring)), key=lambda i: (ring[i][0] - ring[0][0]) ** 2 + (ring[i][1] - ring[0][1]) ** 2)
    first = dp(ring[: far + 1], TOLERANCE)
    second = dp(ring[far:] + [ring[0]], TOLERANCE)
    return first[:-1] + second[:-1]


def rnd(p):
    return [round(p[0], 3), round(p[1], 3)]


def polygons(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def bbox_hits(ring, bbox):
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return not (max(xs) < bbox[0] or min(xs) > bbox[2] or max(ys) < bbox[1] or min(ys) > bbox[3])


def area_layer(features, keep=lambda f: True):
    rings, coast = [], []
    for f in features:
        if not keep(f):
            continue
        for poly in polygons(f["geometry"]):
            for ring in poly:
                if not bbox_hits(ring, BBOX):
                    continue
                clipped = clip_ring(ring, BBOX)
                if len(clipped) < 3 or area(clipped) < MIN_AREA:
                    continue
                simple = simplify_ring(clipped)
                if len(simple) < 3:
                    continue
                rings.append([rnd(p) for p in simple])
                # Coastline = ring edges not lying along the artificial clip boundary.
                chain = []
                closed = simple + simple[:1]
                for a, b in zip(closed, closed[1:]):
                    if on_edge(a, BBOX) and on_edge(b, BBOX):
                        if len(chain) > 1:
                            coast.append([rnd(p) for p in chain])
                        chain = []
                        continue
                    if not chain:
                        chain = [a]
                    chain.append(b)
                if len(chain) > 1:
                    coast.append([rnd(p) for p in chain])
    return rings, coast


def line_layer(features):
    out = []
    x0, y0, x1, y1 = BBOX
    for f in features:
        g = f["geometry"]
        lines = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"] if g["type"] == "MultiLineString" else []
        for line in lines:
            chain = []
            for p in line:
                if x0 <= p[0] <= x1 and y0 <= p[1] <= y1:
                    chain.append(tuple(p[:2]))
                elif chain:
                    if len(chain) > 1:
                        out.append([rnd(q) for q in dp(chain, TOLERANCE)])
                    chain = []
            if len(chain) > 1:
                out.append([rnd(q) for q in dp(chain, TOLERANCE)])
    return out


def main(src: Path):
    loaded, digests = {}, {}
    for key, name in SOURCES.items():
        raw = (src / name).read_bytes()
        digests[key] = hashlib.sha256(raw).hexdigest()
        loaded[key] = json.loads(raw)["features"]
    land, coast = area_layer(loaded["land"])
    lakes, _ = area_layer(loaded["lakes"], keep=lambda f: (f["properties"].get("scalerank") or 99) <= 6)
    borders = line_layer(loaded["borders"])
    places = []
    for f in loaded["places"]:
        p = f["properties"]
        lon, lat = p.get("longitude"), p.get("latitude")
        if lon is None or not (BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]):
            continue
        if (p.get("scalerank") or 99) > 8:
            continue
        places.append({"name": p.get("name"), "lon": round(lon, 4), "lat": round(lat, 4),
                       "rank": p.get("scalerank"), "country": p.get("adm0name")})
    places.sort(key=lambda p: (p["rank"], p["name"]))
    out = {
        "meta": {
            "title": "High North offline basemap",
            "license": "Natural Earth, public domain (https://www.naturalearthdata.com/about/terms-of-use/)",
            "sources": {k: {"file": SOURCES[k], "url": URL + SOURCES[k], "sha256": digests[k]} for k in SOURCES},
            "bbox_lon_lat": BBOX, "simplification_tolerance_deg_lat": TOLERANCE,
            "projection_note": f"Rendered in a local equirectangular view (x scaled by cos {LAT0}°). Not for navigation.",
            "builder": "scripts/build_basemap.py",
        },
        "land": land, "coast": coast, "lakes": lakes, "borders": borders, "places": places,
    }
    OUT.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    pts = sum(len(r) for r in land) + sum(len(r) for r in coast) + sum(len(r) for r in borders)
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB): {len(land)} land rings, {len(coast)} coast chains, "
          f"{len(lakes)} lakes, {len(borders)} border lines, {len(places)} places, {pts} points")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("."))
