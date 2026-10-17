# Map sources

## Offline topographic snapshot — © Kartverket

Provider: https://cache.kartverket.no/

Licence: CC BY 4.0. https://www.kartverket.no/api-og-data/vilkar-for-bruk

252 PNG source tiles from the official `topograatone` Web Mercator service were
downloaded on 17 October 2026, then mosaicked into four local WebP images with
transparency preserved, WebP quality 93. The pack totals 1,361,228 image bytes.
No roads, contours, heights or place names were invented.

- Overview: zoom 6, requested 5–45°E / 65.5–74.5°N.
- Regional: zoom 8, requested 16.5–34.5°E / 68.4–71.8°N.
- Varanger: zoom 11, requested 30.5–31.4°E / 70.05–70.55°N.
- Troms: zoom 11, requested 18.65–19.28°E / 69.47–69.88°N.

Actual image extents include whole tiles and are listed in `topo/manifest.json`,
along with each source URL, tile hash, retrieval time, output image hash and
processing details. The service did not supply a map revision date. Download date
is not a revision date. Original PNGs are in the preparer's temporary source cache;
only the portable processed images and manifest are required and included here.

The pack excludes zoom 12+ because Kartverket's terms distinguish copying rights
for detailed Geovekst content at zooms 12–20. Outside mapped areas, the Natural
Earth outline remains. Roads/place names baked into imagery cannot be toggled as
separate layers. This is not current road condition information.

Rebuild online: `.venv/bin/python scripts/prepare_topomap.py`. The app never runs
that downloader. Runtime checks local image hashes and falls back to the outline
if the pack is missing or invalid.

## Natural Earth reference outlines — public domain

`basemap-high-north.json` uses Natural Earth 1:10 million land, lakes, borders and
populated places, clipped/simplified by `scripts/build_basemap.py`. Exact source
URLs/hashes are in that file's `meta.sources`.

Older `north-region.geojson`: 1:110 million country outlines for Norway, Sweden,
Finland and Russia. Source:
https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson

SHA-256: `6866c877d39cba9c357620878839b336d569f8c662d3cfab4cb1dbe2d39c977f`.

Terms: https://www.naturalearthdata.com/about/terms-of-use/

Display projection is Web Mercator, matching raster tiles; evidence matching
still uses original WGS84 coordinates. Approximate scale is measured at view
centre. The coordinate grid is WGS84 degrees, not MGRS. These reference views
are not a certified navigation or military mapping product.
