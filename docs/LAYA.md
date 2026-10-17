# Optional local report intake — 17 October 2026

This optional adapter stages human-confirmed text reports separately from core
source evidence. The source release includes the adapter, fixed synthetic fixture
and evaluation results; model weights and installed environments are excluded.

## Prepare and use locally

Install the core app as described in the README. While connected, run
`Setup-Local-Laya.command` on a Mac, or prepare the optional environment explicitly:

```sh
python3 -m venv .venv-laya
.venv-laya/bin/python -m pip install -r requirements-laya.txt
.venv-laya/bin/python scripts/prepare_laya.py
```

Start the app at http://localhost:8528, load an exercise, and select **Report intake**.
Choose Simple rules, Manual, or **Laya · local experiment**. Request a suggestion,
inspect the original wording, correct the category if needed, tick the confirmation
checkbox and save. Merely running the model never saves a report.

The app uses its own `.venv`; the classifier runs in `.venv-laya` over private pipes.
It does not need a separate model server or listening port. It loads on the first
explicit Laya request and reuses the process. Stopping the app releases it.
The launcher defaults to `data/northlink.db`; the recorded workspace uses
`data/northlink-finnmark.db`. An explicit `NORTHLINK_DB` overrides the base file.
Setup can be repeated with `Setup-Local-Laya.command` while online. A different laptop
needs its own environments: copying macOS virtual environments is not a portable install.

## What is integrated

- Five candidate categories: reported access disruption, access update/cancellation,
  weather, supplies/equipment, and unclear/conflicting/question.
- Exact original text and SHA-256, source label, suggested label/method/model revision,
  human-confirmed label, reviewer label, workspace and UTC confirmation time.
- Editing text invalidates the old suggestion. Text/source/method/reviewer/category
  changes require a new confirmation. Confirmation resets after saving.
- Separate inboxes per synthetic, Finnmark and practice workspace. Saving reports
  does not insert event/coverage rows, change assessments, reopen reviews or dispatch anything.
- The source label is user-supplied, not authenticated identity or verified provenance.
- A 1,200-character limit plus an actual tokenizer-budget check avoids silently
  classifying truncated input. Longer reports need manual handling outside this panel.
- Missing environment, missing files, invalid output, timeout or model failure leaves
  the core app available. Simple rules/manual work without Laya.

Report inboxes live beside the selected core database as `*-report-inbox.sqlite3`.
They survive app/browser/model restarts. Export them with **Export confirmed report
inbox (JSON)**. Existing evidence handover JSON and situation briefs do **not** embed
this separate inbox; import/merge of inbox exports is not implemented. Confirmed
exercise reports are staging records, not authoritative source evidence.

## Measured evaluation

`scenarios/intake/evaluation.json` contains 50 hand-labelled synthetic examples:
25 English and 25 Norwegian, balanced across five classes. They include negation,
cancellation, conflicting reports, questions, hypothetical statements and missing
information. These are invented test cases, not operational data or an independent benchmark.
No fine-tuning, score calibration, threshold fitting or prompt selection was performed
on these results. Two initial plumbing probes preceded the fixed evaluation; one
English probe and one Norwegian probe also appear in the fixture. This is therefore
a development evaluation, not a fully untouched held-out estimate.

| Measure | Simple rules | Laya multilingual |
|---|---:|---:|
| Correct / total | 41/50 | 28/50 |
| English correct | 21/25 | 15/25 |
| Norwegian correct | 20/25 | 13/25 |
| Negation/cancellation classification errors | 2 | 14 |
| Warm median inference time | 0.012 ms | 71.58 ms |

The complete results and every error are in `verification/laya-evaluation.json`.
Laya often returned unclear for specific access reports. Calling those wrong labels
does not imply every error asserts a dangerous opposite. Neither result measures
truthfulness of the original report, route safety, time saved, or military reliability.
The small convenience sample cannot establish general accuracy.

**Recommendation: keep simple rules/manual as default.** Laya failed the predefined
demo gate (at least 85% accuracy, no worse than rules, zero negation/cancellation
errors). It remains available as a labelled local experiment because the requested
integration can now be tried without changing core decisions. Do not pitch it as
zero-error or an improvement over the rules on these examples.

## Verified environment and offline scope

Tested on this Apple Silicon Mac (arm64, 16 GB RAM), Python 3.14.7, Laya 0.4.8,
PyTorch 2.14.1, Transformers 5.20.1. CPU float32, four PyTorch threads; no MPS/CUDA
compilation. The first evaluation request including process startup took 5.25 seconds;
the initial first-ever plumbing probe took 17.8 seconds. Warm latency above excludes
UI rendering and should not be advertised as end-to-end response time.

The model worker blocks IP networking with a Python audit hook, sets Hugging Face
and Transformers offline flags, and loads only the local prepared directory. No
cloud AI is invoked, no API key is passed, and no per-request paid model call is made.
This is an application-level guard, not an OS sandbox or a physical Wi-Fi test.
Model/package downloads require connectivity once. Live MET refresh still needs internet.

`scripts/verify_local_intake.py` exercised real Laya through Streamlit AppTest under
an external Python socket/DNS block, confirmed and saved a report, closed the worker,
cleared app caches and repeated inference after a full worker restart. The inbox
persisted and event/review tables were unchanged. See `verification/offline-model-check.json`.
Physical Wi-Fi-off acceptance and field validation have not been performed.

## Model and attribution

Source: https://github.com/NandhaKishorM/laya (Apache-2.0).
Checkpoint: https://huggingface.co/convaiinnovations/laya-multilingual
Pinned model revision: `1720e3e3357cfe1e281542e223f8273b0890ca34`.
`scripts/prepare_laya.py` downloads only this checkpoint, prepares the tokenizer
compatibility normalisation used by Laya, then hashes the prepared local files.
The worker verifies these hashes before loading. This detects accidental model-file
changes; it is not independent authentication or tamper-proof storage.

Model weights, caches and virtual environments are ignored by Git. Source-only
archives need online setup before their first offline use. The downloaded checkpoint must remain available locally before offline inference.
MET, Kartverket and Natural Earth attribution is in `assets/SOURCES.md`.

## Reproduce

```sh
.venv/bin/python -B -m pytest -q -p no:cacheprovider
.venv/bin/python scripts/evaluate_laya.py
.venv/bin/python scripts/verify_local_intake.py
```

No tests or rehearsal scripts delete existing local workspace data. Optional-model
evaluation is separate from the default unit suite so core checks work without weights.
