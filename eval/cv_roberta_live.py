import gc
import hashlib
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import torch
from fastembed import TextEmbedding
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.model_selection import StratifiedGroupKFold

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from roberta_common import seed_all, train_roberta, predict_roberta  # noqa: E402
from eval_holdout_v5 import compare, stats  # noqa: E402
from yahmi.cues import cue_hits  # noqa: E402

AMBER, RED = 0.62, 0.80
SEED = 42
FOLDS = 5
CACHE = os.path.join(HERE, "emb_cache.npz")
OUT = os.path.join(HERE, "result_cv_roberta_vs_live.json")
PARTIAL = os.path.join(ROOT, "data", "dl", "roberta_cv_partial.npz")


def load_real():
    corpus = []
    for name in ("bec_realworld.json", "bec_realworld_more.json"):
        corpus += json.load(open(os.path.join(ROOT, "data", name), encoding="utf-8"))
    seen = set()
    texts, labels, groups, types = [], [], [], []
    for row in corpus:
        text = (row.get("subject") or "") + "\n" + row["body"]
        if text in seen:
            continue
        seen.add(text)
        texts.append(text)
        labels.append(int(row["label"] == "fraud"))
        groups.append(row["source_url"].split("#")[0])
        types.append(row.get("attack_type", ""))
    return texts, np.array(labels), np.array(groups), np.array(types)


def load_aux():
    frame = pd.read_csv(os.path.join(ROOT, "data", "dl", "phishing_email.csv")).dropna(subset=["Email Text"])
    frame["text"] = frame["Email Text"].astype(str)
    frame = frame[frame["text"].str.len() > 20].drop_duplicates("text")
    frame["y"] = (frame["Email Type"] == "Phishing Email").astype(int)
    public = frame.sample(n=1500, random_state=3)
    synthetic = pd.DataFrame(json.load(open(os.path.join(HERE, "synthetic_bec_train.json"), encoding="utf-8")))
    return public, synthetic


def bge_features(texts):
    cache = dict(np.load(CACHE, allow_pickle=True)) if os.path.exists(CACHE) else {}
    emb_model = TextEmbedding("BAAI/bge-small-en-v1.5", max_length=128)
    keys = [hashlib.md5(t[:700].encode()).hexdigest() for t in texts]
    todo = [t for t, key in zip(texts, keys) if key not in cache]
    if todo:
        for text, vector in zip(todo, emb_model.embed([t[:700] for t in todo], batch_size=64)):
            cache[hashlib.md5(text[:700].encode()).hexdigest()] = vector
        np.savez(CACHE, **cache)
    emb = np.array([cache[key] for key in keys])
    cues = np.array([[float(v) for v in cue_hits(text).values()] for text in texts])
    return np.hstack([emb, cues * 0.5])


def fit_live_recipe(real_x, real_y, real_texts, train_idx, test_idx, pub_x, pub_y, syn_x, syn_y):
    x = np.vstack([real_x[train_idx]] * 3 + [pub_x, syn_x])
    y = np.concatenate([real_y[train_idx]] * 3 + [pub_y, syn_y])
    gbm = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.08).fit(x, y)
    lr = LogisticRegression(C=1.0, class_weight="balanced", max_iter=3000).fit(x, y)
    tfidf = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)
    a = tfidf.fit_transform([real_texts[i] for i in train_idx])
    tlr = LogisticRegression(C=4.0, class_weight="balanced", max_iter=3000).fit(a, real_y[train_idx])
    p = (
        gbm.predict_proba(real_x[test_idx])[:, 1]
        + lr.predict_proba(real_x[test_idx])[:, 1]
        + tlr.predict_proba(tfidf.transform([real_texts[i] for i in test_idx]))[:, 1]
    ) / 3
    return p


def roberta_pool(real_texts, real_y, train_idx, pub_texts, pub_y, syn_texts, syn_y):
    texts = [real_texts[i] for i in train_idx] * 3 + pub_texts + syn_texts
    labels = np.concatenate([real_y[train_idx]] * 3 + [pub_y, syn_y])
    return texts, labels


def result_block(p, y):
    y = np.asarray(y).astype(bool)
    block = stats(p, y)
    block.pop("_flagged")
    block["average_precision"] = round(float(average_precision_score(y, p)), 3)
    return block


def at_budget(p, y, target):
    best = None
    for threshold in np.linspace(0.0, 1.0, 10001):
        false_alarms = int(((p >= threshold) & ~y).sum())
        caught = int(((p >= threshold) & y).sum())
        if false_alarms <= target and (best is None or caught > best["caught"]):
            best = {"threshold": round(float(threshold), 4), "caught": caught, "false_alarms": false_alarms}
    return best


def main():
    seed_all(SEED)
    torch.set_num_threads(max(1, min(16, os.cpu_count() or 1)))
    real_texts, real_y, groups, types = load_real()
    public, synthetic = load_aux()
    pub_texts, pub_y = public["text"].tolist(), public["y"].to_numpy()
    syn_texts, syn_y = synthetic["text"].tolist(), synthetic["y"].to_numpy()

    print(f"real n={len(real_y)} fraud={int(real_y.sum())} legit={int((real_y == 0).sum())} sources={len(set(groups))}", flush=True)
    real_x = bge_features(real_texts)
    pub_x = bge_features(pub_texts)
    syn_x = bge_features(syn_texts)

    p_live = np.zeros(len(real_y))
    p_roberta = np.zeros(len(real_y))
    done = 0
    if os.path.exists(PARTIAL):
        with np.load(PARTIAL) as saved:
            p_live, p_roberta, done = saved["p_live"].copy(), saved["p_roberta"].copy(), int(saved["done"])
        print(f"resuming after fold {done}", flush=True)
    splitter = StratifiedGroupKFold(n_splits=FOLDS, shuffle=True, random_state=SEED)
    for fold, (train_idx, test_idx) in enumerate(splitter.split(real_x, real_y, groups), start=1):
        if fold <= done:
            continue
        started = time.time()
        print(f"fold {fold}/{FOLDS} train={len(train_idx)} test={len(test_idx)}", flush=True)
        p_live[test_idx] = fit_live_recipe(
            real_x, real_y, real_texts, train_idx, test_idx, pub_x, pub_y, syn_x, syn_y
        )
        pool_texts, pool_y = roberta_pool(real_texts, real_y, train_idx, pub_texts, pub_y, syn_texts, syn_y)
        model, tokenizer = train_roberta(pool_texts, pool_y)
        p_roberta[test_idx] = predict_roberta(model, tokenizer, [real_texts[i] for i in test_idx])
        del model, tokenizer
        gc.collect()
        np.savez(PARTIAL, p_live=p_live, p_roberta=p_roberta, done=fold)
        print(f"fold {fold} done in {(time.time() - started) / 60:.1f} min", flush=True)

    out = {
        "dataset": "data/bec_realworld.json + data/bec_realworld_more.json",
        "n": int(len(real_y)),
        "fraud": int(real_y.sum()),
        "legit": int((real_y == 0).sum()),
        "sources": int(len(set(groups))),
        "folds": FOLDS,
        "thresholds": {"amber": AMBER, "red": RED},
        "roberta": {
            "base_model": os.environ.get("ROBERTA_MODEL", "roberta-base"),
            "epochs": int(os.environ.get("ROBERTA_EPOCHS", "2")),
            "batch_size": int(os.environ.get("ROBERTA_BATCH", "16")),
            "max_len": int(os.environ.get("ROBERTA_MAX_LEN", "192")),
            "learning_rate": float(os.environ.get("ROBERTA_LR", "2e-5")),
        },
        "caveats": [
            "Source-grouped 5-fold development CV; public and synthetic pools are fixed across folds.",
            "The live artifact cannot be scored honestly here because it was trained on all real emails, so the live recipe is retrained per fold.",
            "Public and synthetic data may share wording with some real sources; both models see the same pool.",
            "This is not a holdout result and cannot support promotion.",
        ],
        "models": {
            "bec_final_recipe_cv": result_block(p_live, real_y),
            "roberta_cv": result_block(p_roberta, real_y),
        },
        "comparison": compare(p_roberta >= AMBER, p_live >= AMBER, real_y.astype(bool), "roberta vs live recipe, amber"),
        "comparison_red": compare(p_roberta >= RED, p_live >= RED, real_y.astype(bool), "roberta vs live recipe, red"),
        "by_type_amber": {},
        "operating_points_post_hoc": {
            "caveat": "Thresholds chosen on the same CV folds for diagnostic comparison only; not promotion thresholds.",
            "amber_equal_false_alarms": {
                "target": int(((p_live >= AMBER) & ~real_y.astype(bool)).sum()),
                "live_recipe": at_budget(p_live, real_y.astype(bool), int(((p_live >= AMBER) & ~real_y.astype(bool)).sum())),
                "roberta": at_budget(p_roberta, real_y.astype(bool), int(((p_live >= AMBER) & ~real_y.astype(bool)).sum())),
            },
            "red_equal_false_alarms": {
                "target": int(((p_live >= RED) & ~real_y.astype(bool)).sum()),
                "live_recipe": at_budget(p_live, real_y.astype(bool), int(((p_live >= RED) & ~real_y.astype(bool)).sum())),
                "roberta": at_budget(p_roberta, real_y.astype(bool), int(((p_live >= RED) & ~real_y.astype(bool)).sum())),
            },
            "red_zero_false_alarms": {
                "target": 0,
                "live_recipe": at_budget(p_live, real_y.astype(bool), 0),
                "roberta": at_budget(p_roberta, real_y.astype(bool), 0),
            },
        },
        "scores": {
            "bec_final_recipe_cv": [round(float(v), 6) for v in p_live],
            "roberta_cv": [round(float(v), 6) for v in p_roberta],
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
    if os.path.exists(PARTIAL):
        os.remove(PARTIAL)
    print(json.dumps(out["models"], indent=1), flush=True)
    print(json.dumps(out["comparison"], indent=1), flush=True)
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
