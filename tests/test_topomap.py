"""Offline imagery integrity, coverage and alignment with the vector projection."""
import hashlib
import json

import pytest

from northlink import mapgeo, replay, topomap, visuals


def test_pack_is_complete_local_and_covers_each_exercise_site(monkeypatch):
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("Runtime must not download maps"))
    pack = topomap.read_pack()
    assert not pack["error"] and len(pack["images"]) == 4
    manifest = json.loads((topomap.ROOT / "manifest.json").read_text())
    assert len(manifest["source_tiles"]) == 252
    assert max(r["zoom"] for r in pack["images"]) == 11
    for image in pack["images"]:
        raw = (topomap.ROOT / image["file"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == image["sha256"]
        assert image["href"].startswith("data:image/webp;base64,")
    # Transparent sea/no-coverage pixels must stay transparent, rather than
    # turning black when a paletted/RGBA source is converted to a mosaic.
    from PIL import Image
    with Image.open(topomap.ROOT / "overview.webp") as overview:
        assert overview.mode == "RGBA"
        assert overview.getchannel("A").getextrema() == (0,255)
    for ident, site in replay.SITES.items():
        image = next(r for r in pack["images"] if r["site"] == ident)
        west,south,east,north = image["bbox"]
        assert west < site["lon"] < east and south < site["lat"] < north


def test_bad_pack_falls_back_without_using_other_paths(tmp_path):
    manifest = json.loads((topomap.ROOT / "manifest.json").read_text())
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert topomap.read_pack(tmp_path)["images"] == []  # missing files
    manifest["regions"][0]["file"] = "../elsewhere.webp"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert "source" in topomap.read_pack(tmp_path)["error"]
    manifest["regions"][0]["file"] = "bad.webp"
    manifest["regions"][0]["bbox"] = [5,70,4,71]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert "extent" in topomap.read_pack(tmp_path)["error"]
    del manifest["regions"][0]["site"]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert topomap.read_pack(tmp_path)["images"] == []


def test_altered_map_bytes_rejected(tmp_path):
    manifest = json.loads((topomap.ROOT / "manifest.json").read_text())
    first = manifest["regions"][0]
    (tmp_path / first["file"]).write_bytes(b"altered map bytes")
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    result = topomap.read_pack(tmp_path)
    assert result["images"] == [] and "checksum" in result["error"]


def test_xyz_tile_corners_align_in_display_projection():
    # A Web Mercator tile is a projected square. Equal edge spans and adjacent
    # boundaries catch the old latitude-linear raster misalignment at 70 N.
    west,south,east,north = mapgeo.tile_bounds(11, 1200, 453, 1200, 453)
    x0,y0 = mapgeo.project(west,north)
    x1,y1 = mapgeo.project(east,south)
    assert x1-x0 == pytest.approx(y1-y0,abs=.0002)
    adjacent = mapgeo.tile_bounds(11,1201,453,1201,453)
    assert adjacent[0] == east
    assert mapgeo.project(adjacent[0],adjacent[3])[0] == x1
    assert mapgeo.project(25,70) == (0,0)


def test_display_projection_does_not_change_source_point_exposure():
    before = [(n.identifier, ident, replay.contains(n.geometry, s["lon"], s["lat"]))
              for n in replay.notices() for ident,s in replay.SITES.items()]
    data = visuals.recorded_map(replay.notices()[1].geometry,None,
                               {k:{**s,"note":"Exercise"} for k,s in replay.SITES.items()},
                               {},"F1","FN-VARANGER","Recorded","alignment-check")
    assert len(data["rasters"]) == 4
    marker = next(m for m in data["markers"] if m["id"] == "FN-VARANGER")
    assert (marker["x"],marker["y"]) == mapgeo.project(31.1,70.3)
    after = [(n.identifier, ident, replay.contains(n.geometry, s["lon"], s["lat"]))
             for n in replay.notices() for ident,s in replay.SITES.items()]
    assert before == after
