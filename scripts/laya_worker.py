"""Private local JSON-lines worker, with all IP network access blocked.

Loaded only by the optional triage button or evaluation script. Never downloads.
"""
from __future__ import annotations
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                  TOKENIZERS_PARALLELISM="false", USE_TF="0")


def block_network(event, args):
    if event in ("socket.connect", "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "socket.sendto"):
        raise OSError("Northlink local classifier: network access is disabled")


sys.addaudithook(block_network)
from northlink.report_intake import QUESTIONS, text_hash, validate_text


def load_model():
    path = ROOT / "models/laya-multilingual"
    manifest = json.loads((path / "northlink-manifest.json").read_text())
    # Check every local file before loading weights. A digest protects against
    # accidental changes; it does not authenticate a source or validate a report.
    for name, expected in manifest["sha256"].items():
        with (path / name).open("rb") as f:
            if hashlib.file_digest(f, "sha256").hexdigest() != expected:
                raise RuntimeError("Local model file changed; run setup again: " + name)
    import torch
    import laya
    torch.set_num_threads(4)
    # CPU float32 is reproducible on this 16 GB Mac and avoids MPS compatibility
    # surprises. No accelerator compilation, server, subscription, or API key.
    agent = laya.load(str(path), device="cpu", fast=False, compile=False)
    return agent, manifest, laya.__version__


agent = None
for line in sys.stdin:
    request_id = None
    try:
        request = json.loads(line)
        request_id = request["id"]
        text = validate_text(request["text"])
        start = time.perf_counter()
        with contextlib.redirect_stdout(sys.stderr):
            if agent is None:
                agent, manifest, version = load_model()
            from laya.common import state_room
            q = agent._to_internal(QUESTIONS["category"])
            room = state_room(agent.tok, q, agent.cfg["max_len"], agent.cfg["head_max_len"])
            if len(agent.tok.encode(text, add_special_tokens=False)) > room:
                raise ValueError("This report exceeds the model context. Shorten it or classify it manually.")
            answer = agent.predict(text, QUESTIONS)["answers"]["category"]
        suggestion = {"category": answer["choice"], "method": "laya-multilingual",
                      "text_sha256": text_hash(text), "raw_score": answer["probabilities"][answer["choice"]],
                      "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
                      "model_id": manifest["model_id"], "model_revision": manifest["revision"],
                      "laya_version": version, "device": "cpu", "network_blocked": True}
        print(json.dumps({"id": request_id, "suggestion": suggestion}), flush=True)
    except Exception as exc:
        print(json.dumps({"id": request_id, "error": f"{type(exc).__name__}: {exc}"}), flush=True)
