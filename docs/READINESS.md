# Prototype readiness

Northlink is a hackathon prototype for local evidence and review continuity in a
fictional Arctic essential-supply exercise. It has not been validated for military
operations. A familiar map layout does not establish operational readiness.

## Implemented and checked

- Local SQLite storage, whole-file validation and atomic imports.
- Reject changed content reusing a stored packet ID or source/event/revision ID.
- Highest revision is authoritative even if an older record arrives later.
- Missing, stale and conflicting source information remains visible.
- Append-only human decisions retain the evidence versions/hashes used at review.
- Material evidence changes reopen the affected review; earlier decisions remain.
- JSON handover restore into an empty database; foreign review display on merges.
- Deterministic evidence-linked brief, with no model/API requirement.
- Prepared offline Kartverket imagery with hash checks and an outline fallback.
- Optional separate report inbox; suggestions require human confirmation.

The local suite passed 89 tests on macOS arm64 / Python 3.14.7. These cover the
reference scenarios, import/review/handover contracts, UI, and map-pack checks.
An external-Python-network-blocked browser rehearsal also exercised a saved
decision, correction, reopening and handover. Physical Wi-Fi-off acceptance and
installation on a second laptop remain human checks.

## Not implemented or not established

- Publisher signatures, verified source identities or detection of a convincing
  fabricated report with a new identity. Content hashes detect some changes;
  they do not prove who produced a report or whether it is true.
- Authentication, access control and protected/tamper-resistant audit storage.
  A role label in the UI is not an authenticated user identity.
- Secure distributed synchronization, conflict resolution across independent
  writers, or deployment hardening. The demo uses one authoritative laptop and
  file snapshots.
- Real route assessment, road-closure verification, navigation, GPS anti-spoofing,
  live comprehensive source coverage, or military message-format interoperability.
- Field usability trials, representative workload measurements, operational
  safety/reliability validation or certification.

The recorded weather replay is from April 2026; the map was downloaded in October
2026. All deliveries and exercise points are fictional. A missing matching record
is never an all-clear. Do not describe the prototype as a new weather model, a
validated military decision engine, or proof that competing products lack DDIL.

## Optional AI result

Laya multilingual scored 28/50 on the small synthetic English/Norwegian
classification fixture; simple rules scored 41/50. Laya remains a labelled
experiment, with simple rules/manual as the default. This is not an independent
benchmark or an operational accuracy estimate. See [LAYA.md](LAYA.md).

## Before submission

Run the demo from a fresh practice workspace. Confirm the organiser's actual
deadline and required submission fields, obtain mentor feedback on the proposed
coordinator workflow, and complete the physical offline restart check in the
README. Select a source-code licence and repository visibility with the team.
The prepared GitHub Actions workflow has not run until the repository is uploaded.
