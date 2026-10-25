"""Smoke-test the saved RoBERTa candidate and measure CPU inference."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)

from cv_roberta_live import load_real  # noqa: E402
from roberta_common import MAX_LEN, predict_roberta  # noqa: E402

CANDIDATE = os.path.join(ROOT, "models", "candidates", "roberta_base_email_v1")
OUT = os.path.join(HERE, "result_roberta_candidate_runtime.json")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def calibrate(p, temperature):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    z = np.log(p / (1 - p))
    return 1 / (1 + np.exp(-z / temperature))


def main():
    started = time.perf_counter()
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    metadata = json.load(open(os.path.join(CANDIDATE, "metadata.json"), encoding="utf-8"))
    calibration = json.load(open(os.path.join(CANDIDATE, "calibration.json"), encoding="utf-8"))
    tokenizer = AutoTokenizer.from_pretrained(CANDIDATE)
    model = AutoModelForSequenceClassification.from_pretrained(CANDIDATE)
    model.eval()
    load_seconds = time.perf_counter() - started
    torch.set_num_threads(max(1, min(16, os.cpu_count() or 1)))

    texts, labels, groups, types = load_real()
    sample = texts[:16]
    one_started = time.perf_counter()
    one = predict_roberta(model, tokenizer, sample[:1])
    one_seconds = time.perf_counter() - one_started
    batch_started = time.perf_counter()
    batch = predict_roberta(model, tokenizer, sample)
    batch_seconds = time.perf_counter() - batch_started
    calibrated = calibrate(batch, calibration["temperature"])
    model_file = os.path.join(CANDIDATE, "model.safetensors")

    out = {
        "candidate": metadata["name"],
        "status": metadata["status"],
        "base_model": metadata["base_model"],
        "max_len": MAX_LEN,
        "model_size_bytes": os.path.getsize(model_file),
        "model_sha256": sha256(model_file),
        "metadata_model_sha256": metadata.get("model_sha256"),
        "hash_matches": sha256(model_file) == metadata.get("model_sha256"),
        "load_seconds": round(load_seconds, 3),
        "one_email_seconds": round(one_seconds, 3),
        "batch_16_seconds": round(batch_seconds, 3),
        "per_email_batch_seconds": round(batch_seconds / 16, 4),
        "raw_score_range": [round(float(batch.min()), 6), round(float(batch.max()), 6)],
        "calibrated_score_range": [round(float(calibrated.min()), 6), round(float(calibrated.max()), 6)],
        "calibration": calibration,
        "sample_note": "The 16 scored emails are training data; only range/latency are reported, not accuracy.",
        "caveats": [
            "CPU-only single-process benchmark; not a concurrency or memory test.",
            "The candidate has no fresh source-disjoint holdout result.",
        ],
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), indent=1)
    print(json.dumps(out, indent=1))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
