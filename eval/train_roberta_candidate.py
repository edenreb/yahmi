"""Train and save the RoBERTa email candidate on all development data."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

os.environ.setdefault("ROBERTA_MAX_LEN", "128")

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from cv_roberta_live import load_aux, load_real, roberta_pool  # noqa: E402
from roberta_common import EPOCHS, MAX_LEN, MODEL_NAME, predict_roberta, seed_all, train_roberta  # noqa: E402

OUT_DIR = os.path.join(ROOT, "models", "candidates", "roberta_base_email_v1")
CALIBRATION = os.path.join(HERE, "result_roberta_calibration.json")
CV_RESULT = os.path.join(HERE, "result_cv_roberta_vs_live.json")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    seed_all(42)
    torch.set_num_threads(max(1, min(16, os.cpu_count() or 1)))
    real_texts, real_y, groups, types = load_real()
    public, synthetic = load_aux()
    pub_texts, pub_y = public["text"].tolist(), public["y"].to_numpy()
    syn_texts, syn_y = synthetic["text"].tolist(), synthetic["y"].to_numpy()
    train_texts, train_y = roberta_pool(
        real_texts,
        real_y,
        np.arange(len(real_y)),
        pub_texts,
        pub_y,
        syn_texts,
        syn_y,
    )
    print(
        f"training n={len(train_y)} fraud={int(train_y.sum())} legit={int((train_y == 0).sum())} "
        f"max_len={MAX_LEN} epochs={EPOCHS}",
        flush=True,
    )
    started = time.time()
    resumed = os.path.exists(os.path.join(OUT_DIR, "training_state.pt"))
    model, tokenizer = train_roberta(train_texts, train_y, checkpoint_dir=OUT_DIR)
    elapsed_min = (time.time() - started) / 60
    model.config.id2label = {0: "legit", 1: "fraud"}
    model.config.label2id = {"legit": 0, "fraud": 1}
    os.makedirs(OUT_DIR, exist_ok=True)
    model.save_pretrained(OUT_DIR, safe_serialization=True)
    tokenizer.save_pretrained(OUT_DIR)

    calibration = json.load(open(CALIBRATION, encoding="utf-8"))
    metadata = {
        "name": "roberta_base_email_v1",
        "status": "candidate",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "base_model": MODEL_NAME,
        "seed": 42,
        "epochs": EPOCHS,
        "max_len": MAX_LEN,
        "training_minutes": None if resumed else round(elapsed_min, 1),
        "resumed_from_checkpoint": resumed,
        "training": {
            "n": int(len(train_y)),
            "fraud": int(train_y.sum()),
            "legit": int((train_y == 0).sum()),
            "real_dataset": "data/bec_realworld.json + data/bec_realworld_more.json",
            "real_n": int(len(real_y)),
            "real_fraud": int(real_y.sum()),
            "real_legit": int((real_y == 0).sum()),
            "real_sources": int(len(set(groups))),
            "aux_public_n": int(len(pub_y)),
            "aux_synthetic_n": int(len(syn_y)),
            "real_repeat": 3,
        },
        "calibration": {
            "temperature": calibration["temperature"],
            "amber_threshold": calibration["operating_points_development"]["amber_equal_live_false_alarms"]["threshold"],
            "red_threshold": calibration["operating_points_development"]["red_equal_live_false_alarms"]["threshold"],
            "source": os.path.basename(CALIBRATION),
            "source_sha256": sha256(CALIBRATION),
            "caveat": "Temperature and thresholds came from source-grouped OOF scores, not from this all-data model and not from a holdout.",
        },
        "development_metrics": calibration["calibrated"],
        "live_recipe_development_metrics": calibration["live_recipe_fixed_thresholds"],
        "provenance": {
            "cv_result": os.path.basename(CV_RESULT),
            "cv_result_sha256": sha256(CV_RESULT),
            "scripts": {
                "roberta_common.py": sha256(os.path.join(HERE, "roberta_common.py")),
                "cv_roberta_live.py": sha256(os.path.join(HERE, "cv_roberta_live.py")),
                "calibrate_roberta.py": sha256(os.path.join(HERE, "calibrate_roberta.py")),
                "train_roberta_candidate.py": sha256(os.path.abspath(__file__)),
            },
            "data_sha256": {
                name: sha256(os.path.join(ROOT, "data", name))
                for name in ("bec_realworld.json", "bec_realworld_more.json")
                if os.path.exists(os.path.join(ROOT, "data", name))
            },
            "aux_public_sha256": sha256(os.path.join(ROOT, "data", "dl", "phishing_email.csv")),
            "aux_synthetic_sha256": sha256(os.path.join(HERE, "synthetic_bec_train.json")),
        },
        "caveats": [
            "Candidate only; not live and not promoted.",
            "The model has no fresh source-disjoint holdout result yet.",
            "Calibration transfer from fold models to this all-data model has not been measured.",
            "Mostly-Arabic messages must stay on bec_multi; this model is English-only.",
        ],
    }
    model_file = os.path.join(OUT_DIR, "model.safetensors")
    if os.path.exists(model_file):
        metadata["model_sha256"] = sha256(model_file)
    json.dump(metadata, open(os.path.join(OUT_DIR, "metadata.json"), "w", encoding="utf-8"), indent=1)
    json.dump(
        {
            "temperature": calibration["temperature"],
            "amber_threshold": metadata["calibration"]["amber_threshold"],
            "red_threshold": metadata["calibration"]["red_threshold"],
        },
        open(os.path.join(OUT_DIR, "calibration.json"), "w", encoding="utf-8"),
        indent=1,
    )
    print(json.dumps(metadata, indent=1), flush=True)
    state_file = os.path.join(OUT_DIR, "training_state.pt")
    if os.path.exists(state_file):
        os.remove(state_file)
    print("saved", OUT_DIR, flush=True)


if __name__ == "__main__":
    main()
