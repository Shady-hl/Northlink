# Reused software and data

## Direct dependencies in the tested environment

| Package | Version | License from installed metadata |
|---|---|---|
| streamlit | 1.66.0 | Apache-2.0 |
| pydantic | 2.14.1 | MIT |
| pandas | 3.0.6 | BSD 3-Clause License |
| requests | 2.34.2 | Apache-2.0 |
| pytest | 9.1.1 | MIT |
| python-dotenv | 1.2.4 | BSD-3-Clause |

SQLite and the Python standard library provide local persistence and file parsing. Additional transitive packages are installed by the dependency resolver; their own notices and licences apply. The source release does not bundle those installed libraries.

## Data

MET Norway MetAlerts: https://api.met.no/weatherapi/metalerts/2.0/documentation
Terms: https://api.met.no/doc/License
Attribution: Norwegian Meteorological Institute (MET Norway), CC BY 4.0 / NLOD. Original CAP/GeoJSON files are preserved in the recorded fixture. The manifest records source URLs, source identifiers, acquisition time and SHA-256 hashes. Northlink derives site/time applicability for explicitly fictional deliveries; it does not modify the original notice files or produce new forecasts.

Natural Earth: public-domain regional country outlines. The local reduced dataset and source hash are documented in assets/SOURCES.md. It is a coarse reference map, not a navigation product.

Kartverket: offline `topograatone` imagery, © Kartverket, CC BY 4.0.
Service: https://cache.kartverket.no/ . Terms:
https://www.kartverket.no/api-og-data/vilkar-for-bruk . Source zooms 6, 8 and 11
only; 252 tiles mosaicked to four WebP images. Processing, URLs, acquisition times
and hashes are in `assets/topo/manifest.json` and `assets/SOURCES.md`.
The snapshot download date is not a map revision date.

## Optional classifier

The adapter and evaluation fixture are included. Installed Laya libraries, model
weights and caches are excluded. Laya source:
https://github.com/NandhaKishorM/laya (Apache-2.0). Optional installed packages
are pinned separately in `requirements-laya.txt`; their own licences apply.
Checkpoint: https://huggingface.co/convaiinnovations/laya-multilingual , revision
`1720e3e3357cfe1e281542e223f8273b0890ca34`. Review the checkpoint's terms before
redistributing weights; this source package does not redistribute them.

## UI references and project code

CloudTAK and public SitaWare interface examples informed general map/toolbox and
selection patterns. This release does not contain a CloudTAK fork, SitaWare code,
decompiled software or a claim of compatibility with those products.

Synthetic exercise records, fictional delivery plans, replay mapping, review
logic, interface and deterministic briefing form the demonstrated Northlink
prototype. The team has not selected a source-code licence for publication yet;
the data and dependency licences above remain separate.
