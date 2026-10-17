# Northlink - agent rules

Read `docs/PROJECT_CONTEXT.md` first; it holds the contracts. Keep this file and that one consistent.

## Run
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # needs network once
.venv/bin/python -m pytest -q
.venv/bin/streamlit run app.py        # http://localhost:8528, no network needed
```
Reset local state: stop the app, move `data/northlink.db` aside (don't delete without asking).

## Rules
- Startup must make no network call. Live fetches only behind an explicit button, bounded timeout, failures caught.
- Offline map pack: prepared local imagery only at runtime. Preserve source/licence metadata and image hashes in `assets/topo/manifest.json`; see `assets/SOURCES.md`. Map preparation is an explicit online script, never app startup.
- Never weaken: atomic imports, immutable IDs, highest-revision authority, coverage-clock rules,
  append-only reviews, "no match is not safe" wording, synthetic labelling.
- Synthetic data uses `demo-*` origins and no source URLs; never attach real MET notices to C1-C3.
- Tests encode the brief's expected answers; do not edit expectations to match output.
- No secrets in Git (`.env` is ignored; `.env.example` has names only). Brief/guide docs are ignored.
- One writer per working tree. Use a separate copy when another agent is editing.
- Commit at each verified checkpoint.
