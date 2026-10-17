"""Optional report triage. No imports into the evidence/assessment database.

The core application imports only stdlib here. Laya runs in its own interpreter,
over private stdin/stdout pipes, only after an explicit request.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import sqlite3
import subprocess
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
MAX_CHARS = 1200
LABELS = {
    "access_disruption": "Road access disruption reported",
    "access_update": "Road access update / cancellation",
    "weather": "Weather report",
    "supply": "Supply or equipment report",
    "unclear": "Unclear / conflicting / question",
}
QUESTIONS = {"category": {
    "type": "choice",
    "instructions": "Classify what this logistics report says. Do not assess safety. "
                    "Negations and cancellations matter. Select unclear for questions, "
                    "hypothetical statements, missing meaning or contradictory reports.",
    "criteria": {
        "access_disruption": "A current road or bridge closure, blockage, or access restriction is reported.",
        "access_update": "A road closure or restriction is explicitly cancelled, lifted, or denied. This is not proof of safety.",
        "weather": "Weather conditions or a weather warning, including updates to a weather warning.",
        "supply": "Supply, fuel, medicine or equipment needs, shortages, deliveries, or breakdowns.",
        "unclear": "Unclear or conflicting information; a question or hypothetical; no actual report can be determined.",
    },
}}


def validate_text(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Enter a report first.")
    if len(text) > MAX_CHARS:
        raise ValueError(f"Use at most {MAX_CHARS} characters; longer reports need manual review.")
    return text  # preserve original bytes, including whitespace


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def baseline(text: str) -> dict:
    """Small conservative keyword baseline, explicitly not a trained model."""
    validate_text(text)
    start = time.perf_counter()
    t = text.casefold()
    uncertain = r"\?|\b(if|perhaps|maybe|hypothetical|conflicting|contradictory|unclear|unknown|kanskje|hvis|motstridende|uklart|ukjent)\b"
    access = r"\b(road|bridge|route|veien|vegen|vei|veg|bro|brua|bruen|ruten)\b"
    blocked = r"\b(closed|blocked|closure|restriction|impassable|stengt|stengd|stengning|sperret|restriksjon)\b"
    update = (r"\b(reopened|reopen|lifted|cancelled|canceled|withdrawn|åpnet|gjenåpnet|opphevet|avlyst|trukket)\b"
              r"|\b(not|never|ikke|aldri)\s+(?:currently\s+|lenger\s+)?(?:closed|blocked|stengt|sperret)\b"
              r"|\b(no|ingen)\s+(?:road\s+)?(?:closure|restriction|stengning|restriksjon)\b")
    weather = r"\b(weather|wind|snow|storm|ice|blizzard|warning|været|vær|vind|snø|stormen|uvær|farevarsel|varsel)\b"
    supply = r"\b(fuel|diesel|supplies|supply|medicine|medical|food|generator|equipment|drivstoff|dieselen|forsyninger|medisin|mat|utstyr|generatoren)\b"
    category = "unclear"
    if not re.search(uncertain, t):
        if re.search(access, t) and re.search(update, t):
            category = "access_update"
        elif re.search(access, t) and re.search(blocked, t):
            category = "access_disruption"
        elif re.search(weather, t):
            category = "weather"
        elif re.search(supply, t):
            category = "supply"
    return {"category": category, "method": "keyword-baseline-v1", "text_sha256": text_hash(text),
            "elapsed_ms": round((time.perf_counter() - start) * 1000, 3), "raw_score": None}


def validate_suggestion(value: dict, text: str) -> dict:
    if not isinstance(value, dict) or value.get("category") not in LABELS:
        raise ValueError("Classifier returned an invalid category. Use manual classification.")
    if value.get("text_sha256") != text_hash(text):
        raise ValueError("The report changed. Request a new suggestion.")
    score = value.get("raw_score")
    if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float))
                              or not math.isfinite(score) or not 0 <= score <= 1):
        raise ValueError("Classifier returned an invalid score. Use manual classification.")
    return value


def availability() -> tuple[bool, str]:
    if not (ROOT / ".venv-laya/bin/python").is_file():
        return False, "Optional model environment is not installed. Manual entry and simple rules remain available."
    if not (ROOT / "models/laya-multilingual/northlink-manifest.json").is_file():
        return False, "Model files have not been prepared. Runtime does not download them."
    return True, "Laya model is installed locally. It runs only when you request a suggestion."


class LocalClassifier:
    """One resident worker; serialised requests; bounded cold-start/inference time.

    Worker failure closes the process so a later request cannot consume stale output.
    No model is loaded by construction or by availability().
    """
    def __init__(self):
        self.process = None
        self.responses = queue.Queue()
        self.lock = threading.Lock()
        self.log = None

    def _start(self):
        ready, message = availability()
        if not ready:
            raise RuntimeError(message)
        logs = ROOT / "data"
        logs.mkdir(parents=True, exist_ok=True)
        self.log = (logs / "laya-worker.log").open("a")
        env = {k: v for k, v in os.environ.items() if k in ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL")}
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                   TOKENIZERS_PARALLELISM="false", HF_HOME=str(ROOT / ".hf-cache"),
                   PYTHONDONTWRITEBYTECODE="1", USE_TF="0")
        self.responses = queue.Queue()
        self.process = subprocess.Popen(
            [str(ROOT / ".venv-laya/bin/python"), "-I", str(ROOT / "scripts/laya_worker.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True, bufsize=1,
            cwd=ROOT, env=env)
        process, responses = self.process, self.responses

        def read():
            try:
                for line in process.stdout:
                    responses.put(line)
            finally:
                responses.put(None)
        threading.Thread(target=read, daemon=True).start()

    def suggest(self, text: str, timeout: float = 90) -> dict:
        validate_text(text)
        with self.lock:
            try:
                if self.process is None or self.process.poll() is not None:
                    self.close()
                    self._start()
                request_id = uuid.uuid4().hex
                self.process.stdin.write(json.dumps({"id": request_id, "text": text}) + "\n")
                self.process.stdin.flush()
                line = self.responses.get(timeout=timeout)
                if line is None:
                    raise RuntimeError("The local classifier stopped. Use manual entry or simple rules.")
                result = json.loads(line)
                if result.get("id") != request_id:
                    raise RuntimeError("The classifier response did not match this report.")
                if "error" in result:
                    raise RuntimeError(result["error"])
                return validate_suggestion(result["suggestion"], text)
            except queue.Empty:
                self.close()
                raise RuntimeError("Local inference timed out. Use manual entry or simple rules.") from None
            except (OSError, ValueError, KeyError, RuntimeError) as exc:
                self.close()
                raise RuntimeError(f"Local classifier unavailable: {exc}") from None

    def close(self):
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
            for pipe in (self.process.stdin, self.process.stdout):
                if pipe:
                    pipe.close()
            self.process = None
        if self.log:
            self.log.close()
            self.log = None


def inbox_path(core_db: Path) -> Path:
    return core_db.with_name(core_db.stem + "-report-inbox.sqlite3")


def _connect(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS confirmed_reports (report_id TEXT PRIMARY KEY, record TEXT NOT NULL)")
    return conn


def save_confirmed(path: Path, *, text: str, category: str, person: str, source_label: str,
                   workspace: str, suggestion: dict | None, confirmed: bool) -> str:
    validate_text(text)
    if not confirmed:
        raise ValueError("Confirm that you checked the original report and category.")
    if category not in LABELS:
        raise ValueError("Choose a valid category.")
    if not person.strip() or not source_label.strip():
        raise ValueError("A reviewer and source label are required.")
    if len(person) > 200 or len(source_label) > 200:
        raise ValueError("Reviewer and source labels must be at most 200 characters.")
    if suggestion is not None:
        validate_suggestion(suggestion, text)
    rid = "INT-" + uuid.uuid4().hex[:12]
    record = {"schema_version": 1, "report_id": rid, "original_text": text,
              "text_sha256": text_hash(text), "confirmed_category": category,
              "confirmed_by": person.strip(), "source_label": source_label.strip(),
              "workspace": workspace, "data_kind": "user-supplied exercise report",
              "confirmed_at_utc": datetime.now(timezone.utc).isoformat(),
              "suggestion": suggestion, "affects_assessments": False}
    conn = _connect(path)
    try:
        with conn:
            conn.execute("INSERT INTO confirmed_reports VALUES (?, ?)", (rid, json.dumps(record, ensure_ascii=False)))
    finally:
        conn.close()
    return rid


def saved_reports(path: Path) -> list[dict]:
    if not path.exists():
        return []
    conn = _connect(path)
    try:
        return [json.loads(r[0]) for r in conn.execute("SELECT record FROM confirmed_reports ORDER BY rowid DESC")]
    finally:
        conn.close()
