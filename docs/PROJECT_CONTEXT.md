# Northlink - project context

Stable product and technical agreement. Update when a contract changes.

## Product
Offline-capable decision-support workspace for a regional emergency-logistics coordinator
(Northern Norway). Links delivery impacts to source evidence, shows stale/conflicting/missing
information, preserves human decisions, reopens affected reviews after material corrections.
No autonomous dispatch, no route-safety claims. "No match" never means safe.

Agreed decisions (from the brief):
- Signature behaviour: review continuity and explicit uncertainty after a network-off restart.
- Two isolated workspaces: synthetic deliveries/disruptions; real recorded MET warning geography with fictional site-level delivery windows. Live MET panel remains separate.
- Single presenter laptop is authoritative for review state; multi-laptop = snapshot exchange.
- Every event has origin, timestamps, kind and an immutable (origin, event_id, revision) identity.
- Cloud AI optional, template fallback required. No external tiles/fonts/scripts offline.
- Material source changes reopen reviews; prior reviews and audit entries are retained.
- Claims about live feeds, measurements or novelty require evidence.
- Open: coordinator workflow validation with a mentor, confirmed submission deadline and final submission requirements.

## Architecture
| Path | Responsibility |
|---|---|
| `app.py` | Streamlit UI: queue, evidence panel, review controls, clock, import/export |
| `northlink/models.py` | Pydantic contracts (Packet, Event, Coverage, DeliveryPlan, Delivery, ReviewInput), canonical JSON + hash |
| `northlink/loader.py` | JSON -> models, readable per-field errors |
| `northlink/store.py` | SQLite schema, transactions, reads, audit, persisted scenario clock |
| `northlink/reconcile.py` | Atomic import, duplicate/integrity checks, review re-evaluation |
| `northlink/impact.py` | Pure matching, conflicts, coverage freshness, material fingerprint |
| `northlink/reviews.py` | Save review (append-only, linked to previous), set clock |
| `northlink/handover.py` | Offline JSON export/import |
| `northlink/replay.py` | Local verified CAP update chain, geographic point exposure and fictional Finnmark plan |
| `northlink/briefing.py` | Deterministic evidence-linked Markdown brief |
| `northlink/visuals.py` | Offline SVG geography and fictional corridor diagram |
| `northlink/mapgeo.py` | Web Mercator display projection; source point exposure stays in WGS84 |
| `northlink/topomap.py` | Checks/reads prepared local Kartverket imagery; outline fallback |
| `northlink/connectors/met.py` | Cached MET MetAlerts connector (explicit refresh only) |
| `scenarios/demo/` | Synthetic fixture: plan, packet A, packet B, late E2r1 |
| `scenarios/invalid/` | Malformed and identity-reuse examples |
| `tests/` | Reference scenario + headless UI test |

DB: `data/northlink.db` (git-ignored), override with `NORTHLINK_DB`. Recorded workspace uses a `-finnmark` suffix. Practice runs use new files; no deletion. Practice suffix lives in session state and does not survive a full browser reload.

## Contracts
Packet (schema_version 1): `packet_id`, `kind` (live|recorded|synthetic), `retrieved_at`, `label`,
`coverage[]` {origin, scope_id, source_retrieved_at, successful}, `events[]`.
Event: `event_id`, `revision>=1`, `origin`, `corridor_id?`, `published_at`, `valid_from?`, `valid_until?`,
`event_type` (advisory|warning|closure|restriction|report|other), `status` (active|cancelled),
`claim_key`/`claim_value` (together or not at all), `supersedes_revision?`, `source_url?`, `text`.
Synthetic events may not carry a `source_url`. All times must be timezone-aware; stored as UTC `...Z`.
Unknown fields are rejected.

Identity and import:
- Whole file validated before any write; one `BEGIN IMMEDIATE` transaction per import.
- Same packet_id + same canonical content = duplicate no-op (no audit row). Different content = error, no change.
- Same (origin, event_id, revision) + different payload = error, no change.
- Authoritative event = highest revision per (origin, event_id). Arrival/publication order never decide.
- Coverage is append-only; freshness = newest successful `source_retrieved_at` per (origin, scope).
  Local `imported_at` is separate and never used for freshness. Failed attempts recorded separately.

Assessment (per delivery, at scenario time):
- Relevant = current revision active, same corridor_id, validity overlaps travel window, validity not ended.
- Conflict = relevant events sharing a claim_key with differing claim_values (no precedence rule).
- Category priority: conflict > restriction > advisory > needs_confirmation (missing validity) > no_match.
- Freshness thresholds (demo policy only): demo-weather 30 min, demo-road 15 min; other origins show age,
  no threshold. Coverage dated after the scenario clock is ignored ("not yet valid"); coverage dated after
  its packet's retrieved_at is rejected at import.
- Stale coverage (checked, now too old) => "Evidence stale - recheck"; never reopens a review on its own.
- Expected origins per corridor (demo-weather, demo-road) with no coverage row => separate "Coverage gap /
  not checked" warning, shown in queue, detail and export. (Changed after review M1 so the brief's 12:40
  staleness transition is visible; needs human confirmation.)
- Recorded FN-* exercise scopes expect met-metalerts-recorded. No historical polling coverage is fabricated. The replay maps reviewed geographic points into the warning polygon before using the same time matcher; it does not assess the whole route.
- Any active matching record that is not a conflict/restriction/advisory, and any unlocated active record,
  => needs_confirmation. no_match only when nothing active matches.
- Packet kind must agree with origin: demo-* origins only in synthetic packets and vice versa. Files cannot
  import kind "live" (only connectors); saved real data uses "recorded".

Reviews:
- Append-only `reviews` rows (R1, R2, ...), each with evidence versions + content hashes, material
  fingerprint, stale reasons at decision time, wall time AND scenario time, `previous_review_id`.
- `review_cases` holds state reviewed|reopened. Reopen once when the material fingerprint
  (status, corridor, validity, type, claim) of the evidence changes; text-only changes don't reopen.

Handover: JSON with raw canonical packets/plans, reviews, cases, audit, clock and a readable summary.
Every row is validated (Pydantic, extra fields forbidden, fixed SQL column lists) before the transaction.
Import into an empty DB (no packets/plans/reviews/cases) = full restore; local audit rows are kept and the
exported log is appended. Into a non-empty DB = packets merged under integrity rules,
other laptop's reviews kept as `foreign_reviews` for display only, deduplicated by review content. Foreign reviews are included in subsequent exports and retain their original provenance. Nested evidence/fingerprints and review links are validated before writes; restores insert parent reviews before children.

## Verified prototype checkpoint (2026-10-17)

- 89 tests pass locally on macOS arm64 / Python 3.14.7.
- Map-led review, readable evidence detail, raw records, situation brief, source
  register and report intake are available in one local app.
- A network-guarded browser rehearsal exercised local map loading, a saved review,
  a material update, review reopening, retained context and JSON handover.
- Physical Wi-Fi-off and independent second-laptop installation remain unverified.
- Optional Laya multilingual scored 28/50 synthetic examples against 41/50 simple
  rules. Rules/manual remain default; intake never automatically affects evidence.
- Source authentication, access control, protected audit storage, secure multi-user
  synchronization and field validation are not implemented or established.
- See `READINESS.md` for measured scope and gaps. No model API is needed for core.

## Map snapshot update (2026-10-17)

- Local Kartverket topograatone snapshot, 252 source tiles,
  four WebP mosaics, 1,361,228 image bytes, CC BY 4.0 attribution. Source zoom 6
  overview, zoom 8 regional, zoom 11 at the two fictional sites. No zoom 12+ tiles
  copied. Metadata and hashes: `assets/topo/manifest.json`.
- Display uses Web Mercator to align raster/vector layers. Original WGS84 point /
  polygon and time assessments are unchanged. WGS84 grid spacing adapts to zoom;
  scale is approximate at view centre. No MGRS grid or GPS position is supplied.
- Runtime makes no map requests. Topographic / Outline / Site detail use checked
  local files. Maps show a snapshot, not live road conditions or route safety.
- Weather is the recorded April 2026 warning over a map downloaded October 2026;
  this does not establish historical map reconstruction. Acquisition date is not
  the underlying map revision date, which the service did not supply.
- 89 tests passed: pack integrity, missing/corrupt fallback, image transparency,
  tile alignment and inherited offline review/restart checks. See
  `verification/topomap-tests.txt` and `assets/SOURCES.md`.
