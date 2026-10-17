"""Explicit, online-only setup. Runtime never downloads model files."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "convaiinnovations/laya-multilingual"
REVISION = "1720e3e3357cfe1e281542e223f8273b0890ca34"
FILES = ["rl_agent_config.json", "model.safetensors", "encoder/config.json",
         "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json"]


def main():
    os.environ["HF_HOME"] = str(ROOT / ".hf-cache")
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    from huggingface_hub import hf_hub_download, snapshot_download
    target = ROOT / "models" / "laya-multilingual"
    snapshot_download(MODEL_ID, revision=REVISION, local_dir=target, allow_patterns=FILES)
    # Laya normalises this config on first load. Prepare that documented
    # compatibility adjustment now so a second offline launch sees stable hashes.
    hf_hub_download(MODEL_ID, "tokenizer/tokenizer_config.json", revision=REVISION,
                    local_dir=target, force_download=True)
    tokenizer_file = target / "tokenizer/tokenizer_config.json"
    config = json.loads(tokenizer_file.read_text())
    upstream_tokenizer_hash = hashlib.sha256(tokenizer_file.read_bytes()).hexdigest()
    if config.get("tokenizer_class") in (None, "TokenizersBackend"):
        config["tokenizer_class"] = "PreTrainedTokenizerFast"
        config.pop("backend", None)
        config.pop("is_local", None)
    if isinstance(config.get("extra_special_tokens"), list):
        config["extra_special_tokens"] = {f"extra_{i}": v for i, v in enumerate(config["extra_special_tokens"])}
    tokenizer_file.write_text(json.dumps(config, indent=2))
    digests = {}
    for name in FILES:
        with (target / name).open("rb") as f:
            digests[name] = hashlib.file_digest(f, "sha256").hexdigest()
    manifest = {"model_id": MODEL_ID, "revision": REVISION, "sha256": digests,
                "preparation": "Laya tokenizer compatibility normalisation before hashing",
                "upstream_tokenizer_config_sha256": upstream_tokenizer_hash}
    (target / "northlink-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Prepared local multilingual model:", target)
    print("Pinned revision:", REVISION)
    print("Files verified:", len(digests))


if __name__ == "__main__":
    main()
