"""Evaluate the actual UI adapter vs fixed simple rules. No training or APIs."""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from northlink.report_intake import LocalClassifier, QUESTIONS, baseline


def main():
    fixture = ROOT / "scenarios/intake/evaluation.json"
    dataset = json.loads(fixture.read_text())
    worker = LocalClassifier()
    rows = []
    try:
        for case in dataset["cases"]:
            rules = baseline(case["text"])
            start = time.perf_counter()
            predicted = worker.suggest(case["text"])
            rows.append({**case, "baseline": rules, "laya": predicted,
                         "end_to_end_ms": round((time.perf_counter() - start) * 1000, 2)})
    finally:
        worker.close()
    n = len(rows)
    summary = {}
    for method in ("baseline", "laya"):
        summary[method] = {
            "correct": sum(r[method]["category"] == r["expected"] for r in rows), "n": n,
            "accuracy": sum(r[method]["category"] == r["expected"] for r in rows) / n,
            "by_language": {lang: {"correct": sum(r[method]["category"] == r["expected"] for r in rows if r["lang"] == lang),
                                    "n": sum(r["lang"] == lang for r in rows)} for lang in ("en", "no")},
            "negation_and_cancellation_errors": sum(r["tag"] in ("negation", "cancellation") and
                                                      r[method]["category"] != r["expected"] for r in rows),
            "warm_median_ms": statistics.median(r[method]["elapsed_ms"] for r in rows[1:]),
            "confusion": {f"{a} -> {b}": count for (a, b), count in Counter(
                (r["expected"], r[method]["category"]) for r in rows).items()},
        }
    gate = (summary["laya"]["accuracy"] >= .85 and
            summary["laya"]["accuracy"] >= summary["baseline"]["accuracy"] and
            summary["laya"]["negation_and_cancellation_errors"] == 0)
    summary["laya_passed_demo_gate"] = gate
    summary["first_request_ms_including_worker_start"] = rows[0]["end_to_end_ms"]
    summary["recommendation"] = "Optional candidate classifier only; human confirmation required." if gate else (
        "Keep simple rules/manual as default. Laya remains an explicitly labelled experiment; it did not demonstrate an improvement on these examples.")
    result = {"evaluated_at_utc": datetime.now(timezone.utc).isoformat(), "dataset": dataset["dataset_version"],
              "dataset_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
              "question_sha256": hashlib.sha256(json.dumps(QUESTIONS, sort_keys=True).encode()).hexdigest(),
              "hardware": {"architecture": platform.machine(), "system": platform.platform()},
              "summary": summary, "limitations": ["Hand-labelled synthetic examples; no operational reliability claim.",
              "No fine-tuning, temperature fitting, prompt selection or confidence threshold tuning on these results.",
              "No independent field data or representative workload; latency includes this adapter's CPU configuration."], "cases": rows}
    target = ROOT / "verification/laya-evaluation.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print("Saved", target)


if __name__ == "__main__":
    main()
