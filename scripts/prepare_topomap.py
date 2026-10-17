"""One-time online preparation of a bounded Kartverket offline map pack.

Only official topograatone tiles at zooms 6, 8 and 11 are used. No zoom 12+
Geovekst data are copied. The app itself never calls this script or the service.
Run from the repo: .venv/bin/python scripts/prepare_topomap.py
"""
from __future__ import annotations
import hashlib
import io
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from northlink.mapgeo import tile_bounds

URL = "https://cache.kartverket.no/v1/wmts/1.0.0/topograatone/default/webmercator/{z}/{y}/{x}.png"
REGIONS = [
    ("overview", 6, [5, 65.5, 45, 74.5], None),
    ("regional", 8, [16.5, 68.4, 34.5, 71.8], None),
    ("varanger", 11, [30.5, 70.05, 31.4, 70.55], "FN-VARANGER"),
    ("troms", 11, [18.65, 69.47, 19.28, 69.88], "FN-TROMS"),
]


def tile_index(lon, lat, z):
    n = 2 ** z
    return (int((lon + 180) / 360 * n),
            int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n))


def main():
    cache = Path("/tmp/northlink-topo-source-cache")
    out = ROOT / "assets" / "topo"
    cache.mkdir(exist_ok=True)
    out.mkdir(exist_ok=True)
    acquired = datetime.now(timezone.utc).isoformat()
    packs, receipts = [], {}

    def obtain(item):
        z, x, y = item
        if z > 11:
            raise ValueError("This pack is restricted to zoom 11 and below")
        path = cache / f"{z}-{x}-{y}.png"
        url = URL.format(z=z, x=x, y=y)
        if path.exists():
            raw = path.read_bytes()
        else:
            response = requests.get(url, timeout=(5, 20), headers={"User-Agent": "Northlink-hackathon-offline-map-preparation/1.0"})
            response.raise_for_status()
            raw = response.content
            if len(raw) > 2_000_000 or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError(f"Unexpected tile response for {z}/{x}/{y}")
            path.write_bytes(raw)
        with Image.open(io.BytesIO(raw)) as image:
            if image.size != (256, 256):
                raise ValueError("Unexpected tile size")
            rgba = image.convert("RGBA")
        return item, rgba, {"url": url, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                            "retrieved_at": datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat()}

    for ident, z, box, site in REGIONS:
        x0, y0 = tile_index(box[0], box[3], z)
        x1, y1 = tile_index(box[2], box[1], z)
        tiles = [(z, x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
        if len(tiles) > 150:
            raise ValueError("Unexpected map request size")
        mosaic = Image.new("RGBA", ((x1 - x0 + 1) * 256, (y1 - y0 + 1) * 256), (0,0,0,0))
        print(f"Preparing {ident}: {len(tiles)} tiles, zoom {z}", flush=True)
        # At most two public-service requests in flight; no background polling.
        with ThreadPoolExecutor(max_workers=2) as pool:
            for (tz, x, y), image, receipt in pool.map(obtain, tiles):
                mosaic.paste(image, ((x - x0) * 256, (y - y0) * 256))
                receipts[f"{tz}/{x}/{y}"] = receipt
        path = out / f"{ident}.webp"
        mosaic.save(path, "WEBP", quality=93, method=6)
        raw = path.read_bytes()
        packs.append({"id": ident, "zoom": z, "site": site, "requested_bbox": box,
                      "bbox": tile_bounds(z, x0, y0, x1, y1), "file": path.name,
                      "pixel_size": list(mosaic.size), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        print(f"Saved {path.name}: {len(raw):,} bytes", flush=True)

    manifest = {"format": "northlink-offline-topomap-v1", "prepared_at": acquired,
                "acquired_at": max(r["retrieved_at"] for r in receipts.values()),
                "acquisition_range": [min(r["retrieved_at"] for r in receipts.values()),max(r["retrieved_at"] for r in receipts.values())],
                "provider": "Kartverket", "product": "topograatone", "projection": "EPSG:3857",
                "attribution": "© Kartverket", "license": "CC BY 4.0",
                "license_url": "https://www.kartverket.no/api-og-data/vilkar-for-bruk",
                "service_documentation": "https://cache.kartverket.no/", "maximum_source_zoom": 11,
                "processing": "XYZ tile mosaic, transparency preserved, WebP quality 93. No roads or terrain invented. Not a current road-status source.",
                "source_revision": "Not supplied by the service; acquisition time is not a map revision date.",
                "regions": packs, "source_tiles": receipts}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"Offline pack complete: {len(receipts)} tiles, {sum(p['bytes'] for p in packs):,} image bytes", flush=True)


if __name__ == "__main__":
    main()
