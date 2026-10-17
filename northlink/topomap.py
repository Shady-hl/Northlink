"""Read and validate a prepared local map pack. No networking or downloads."""
import base64
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "assets" / "topo"


def read_pack(root=ROOT):
    try:
        manifest_path = root / "manifest.json"
        if manifest_path.stat().st_size > 512_000:
            raise ValueError("Map manifest is too large")
        manifest = json.loads(manifest_path.read_text())
        if manifest["format"] != "northlink-offline-topomap-v1" or manifest["projection"] != "EPSG:3857":
            raise ValueError("Unsupported map pack")
        images = []
        if not 1 <= len(manifest["regions"]) <= 4:
            raise ValueError("Unexpected region count")
        for r in manifest["regions"]:
            if Path(r["file"]).name != r["file"] or not 0 <= r["zoom"] <= 11:
                raise ValueError("Unexpected map source")
            if not isinstance(r["id"],str) or r["site"] not in (None,"FN-VARANGER","FN-TROMS"):
                raise ValueError("Unexpected map region")
            box = r["bbox"]
            if (len(box) != 4 or not all(isinstance(n, (int, float)) and math.isfinite(n) for n in box)
                    or not -180 <= box[0] < box[2] <= 180 or not -85.052 <= box[1] < box[3] <= 85.052):
                raise ValueError("Invalid map extent")
            image_path = root / r["file"]
            if image_path.stat().st_size > 12_000_000:
                raise ValueError("Map image is too large")
            raw = image_path.read_bytes()
            if len(raw) > 12_000_000 or len(raw) != r["bytes"] or hashlib.sha256(raw).hexdigest() != r["sha256"]:
                raise ValueError("Map image checksum mismatch")
            images.append({**r, "href": "data:image/webp;base64," + base64.b64encode(raw).decode("ascii")})
        return {"date": manifest["acquired_at"][:10], "images": images, "error": None}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"date": None, "images": [], "error": str(exc)}


@lru_cache(maxsize=1)
def prepared():
    return read_pack()
