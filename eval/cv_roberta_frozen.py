import hashlib
import json
import os
import sys

import numpy as np
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedGroupKFold

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from cv_roberta_live import (  # noqa: E402
    AMBER,
    RED,
    SEED,
    FOLDS,
    bge_features,
    fit_live_recipe,
    load_aux,
    load_real,
    result_block,
)
from eval_holdout_v5 import compare  # noqa: E402
from yahmi.cues import cue_hits  # noqa: E402

MODEL_NAME = os.environ.get("ROBERTA_MODEL", "roberta-base")
MAX_LEN = int(os.environ.get("ROBERTA_MAX_LEN", "192"))
BATCH = int(os.environ.get("ROBERTA_BATCH", "32"))
CACHE = os.path.join(HERE, "emb_cache_roberta.npz")
OUT = os.path.join(HERE, "result_cv_roberta_frozen.json")


def roberta_features(texts):
    cache = dict(np.load(CACHE, allow_pickle=True)) if os.path.exists(CACHE) else {}
    keys = [hashlib.md5(t[:700].encode()).hexdigest() for t in texts]
    missing = [t for t, key in zip(texts, keys) if key not in cache]
    if missing:
        from transformers import AutoModel, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        model = AutoModel.from_pretrained(MODEL_NAME)
        model.eval()
        for start in range(0, len(missing), BATCH):
            batch = missing[start:start + BATCH]
            enc = tokenizer(batch, truncation=True, max_length=MAX_LEN, padding=True, return_tensors="pt")
            with torch.inference_mode():
                hidden = model(**enc).last_hidden_state[:, 0, :].cpu().numpy()
            for text, vector in zip(batch, hidden):
                cache[hashlib.md5(text[:700].encode()).hexdigest()] = vector
            print(f"encoded {min(start + BATCH, len(missing))}/{len(missing)}", flush=True)
        np.savez(CACHE, **cache)
    emb = np.array([cache[key] for key in keys])
    emb = emb / np.maximum(np.linalg.norm(emb, axis=1, keepdims=True), 1e-9)
    cues = np.array([[float(v) for v in cue_hits(text).values()] for text in texts])
    return np.hstack([emb, cues * 0.5])


def main():
    torch.set_num_threads(max(1, min(16, os.cpu_count() or 1)))
    real_texts, real_y, groups, types = load_real()
    public, synthetic = load_aux()
    pub_x_bge = bge_features(public["text"].tolist())
    syn_x_bge = bge_features(synthetic["text"].tolist())
    real_x_bge = bge_features(real_texts)

    all_texts = real_texts + public["text"].tolist() + synthetic["text"].tolist()
    all_x = roberta_features(all_texts)
    real_x = all_x[:len(real_texts)]
    pub_x = all_x[len(real_texts):len(real_texts) + len(public)]
    syn_x = all_x[len(real_texts) + len(public):]

    p_live = np.zeros(len(real_y))
    p_roberta = np.zeros(len(real_y))
    splitter = StratifiedGroupKFold(n_splits=FOLDS, shuffle=True, random_state=SEED)
    for fold, (train_idx, test_idx) in enumerate(splitter.split(real_x, real_y, groups), start=1):
        print(f"fold {fold}/{FOLDS} train={len(train_idx)} test={len(test_idx)}", flush=True)
        p_live[test_idx] = fit_live_recipe(
            real_x_bge, real_y, real_texts, train_idx, test_idx,
            pub_x_bge, public["y"].to_numpy(), syn_x_bge, synthetic["y"].to_numpy(),
        )
        x = np.vstack([real_x[train_idx]] * 3 + [pub_x, syn_x])
        y = np.concatenate([real_y[train_idx]] * 3 + [public["y"].to_numpy(), synthetic["y"].to_numpy()])
        clf = LogisticRegression(C=1.0, class_weight="balanced", max_iter=3000).fit(x, y)
        p_roberta[test_idx] = clf.predict_proba(real_x[test_idx])[:, 1]

    out = {
        "dataset": "data/bec_realworld.json + data/bec_realworld_more.json",
        "n": int(len(real_y)),
        "fraud": int(real_y.sum()),
        "legit": int((real_y == 0).sum()),
        "sources": int(len(set(groups))),
        "folds": FOLDS,
        "thresholds": {"amber": AMBER, "red": RED},
        "roberta": {
            "base_model": MODEL_NAME,
            "frozen": True,
            "pooling": "CLS",
            "max_len": MAX_LEN,
            "classifier": "LogisticRegression(C=1.0, class_weight=balanced)",
            "train_pool": "real x3 + 1500 public + 1200 synthetic",
        },
        "caveats": [
            "Source-grouped 5-fold development CV; public and synthetic pools are fixed across folds.",
            "The live artifact was trained on all real emails, so the live recipe is retrained per fold.",
            "RoBERTa is a frozen encoder with a linear probe, not a full fine-tune.",
            "This is not a holdout result and cannot support promotion.",
        ],
        "models": {
            "bec_final_recipe_cv": result_block(p_live, real_y),
            "roberta_frozen_lr_cv": result_block(p_roberta, real_y),
        },
        "comparison": compare(p_roberta >= AMBER, p_live >= AMBER, real_y.astype(bool), "roberta frozen vs live recipe, amber"),
        "comparison_red": compare(p_roberta >= RED, p_live >= RED, real_y.astype(bool), "roberta frozen vs live recipe, red"),
        "by_type_amber": {},
        "scores": {
            "bec_final_recipe_cv": [round(float(v), 6) for v in p_live],
            "roberta_frozen_lr_cv": [round(float(v), 6) for v in p_roberta],
        },
    }
    for attack_type in sorted(set(types)):
        mask = types == attack_type
        out["by_type_amber"][attack_type] = {
            "n": int(mask.sum()),
            "roberta": int(((p_roberta >= AMBER) & mask).sum()),
            "live_recipe": int(((p_live >= AMBER) & mask).sum()),
        }
    json.dump(out, open(OUT, "w", encoding="utf-8"), indent=1)
    print(json.dumps(out["models"], indent=1), flush=True)
    print(json.dumps(out["comparison"], indent=1), flush=True)
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
