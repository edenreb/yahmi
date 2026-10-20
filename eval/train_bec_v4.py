"""Fraud-email model v4: learns from REAL BEC emails as well, evaluated honestly with leave-one-SOURCE-out
cross-validation (each source page/site is held out entirely, so the model is never tested on an email
from a page it learned from). Features: sentence embeddings + explainable cue flags.
Training pool per fold = real emails from other sources + public phishing sample + synthetic emails.
Embeddings are cached in eval/emb_cache.npz."""
import hashlib
import json
import os
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from yahmi.cues import cue_hits  # noqa

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
EMB_MODEL = os.environ.get("EMB_MODEL", "BAAI/bge-small-en-v1.5")
CACHE = os.path.join(HERE, "emb_cache.npz" if EMB_MODEL.startswith("BAAI/bge-small-en") else "emb_cache_" + EMB_MODEL.split("/")[-1] + ".npz")
cache = dict(np.load(CACHE, allow_pickle=True)) if os.path.exists(CACHE) else {}
_emb = None


def embed(texts):
    global _emb
    keys = [hashlib.md5(t[:700].encode()).hexdigest() for t in texts]
    todo = [t for t, k in zip(texts, keys) if k not in cache]
    if todo:
        if _emb is None:
            from fastembed import TextEmbedding
            _emb = TextEmbedding(EMB_MODEL, max_length=128)
        for t, v in zip(todo, _emb.embed([t[:700] for t in todo], batch_size=64)):
            cache[hashlib.md5(t[:700].encode()).hexdigest()] = v
        np.savez(CACHE, **cache)
    return np.array([cache[k] for k in keys])


def feats(texts):
    cues = np.array([[float(v) for v in cue_hits(t).values()] for t in texts])
    return np.hstack([embed(texts), cues * 0.5])


real = []
for f in os.environ.get("BEC_FILES", "bec_realworld.json,bec_realworld_more.json").split(","):
    p = os.path.join(ROOT, "data", f)
    if os.path.exists(p):
        real += json.load(open(p))
seen, R = set(), []
for x in real:
    t = (x.get("subject") or "") + "\n" + x["body"]
    if t in seen:
        continue
    seen.add(t); R.append({"text": t, "y": int(x["label"] == "fraud"), "group": x["source_url"].split("#")[0], "type": x.get("attack_type", "")})
R = pd.DataFrame(R)
df = pd.read_csv(os.path.join(ROOT, "data", "dl", "phishing_email.csv")).dropna(subset=["Email Text"])
df["text"] = df["Email Text"].astype(str); df = df[df["text"].str.len() > 20].drop_duplicates("text")
df["y"] = (df["Email Type"] == "Phishing Email").astype(int)
pub = df.sample(n=1500, random_state=3)
syn = pd.DataFrame(json.load(open(os.path.join(HERE, "synthetic_bec_train.json"))))
Xr, Xp, Xs = feats(R["text"].tolist()), feats(pub["text"].tolist()), feats(syn["text"].tolist())

P = np.zeros(len(R))
for g in R["group"].unique():
    te = (R["group"] == g).values
    Xtr = np.vstack([Xr[~te], Xr[~te], Xr[~te], Xp, Xs])  # real emails weighted x3
    ytr = np.concatenate([R["y"].values[~te]] * 3 + [pub["y"].values, syn["y"].values])
    clf = LogisticRegression(C=1.0, class_weight="balanced", max_iter=3000).fit(Xtr, ytr)
    P[te] = clf.predict_proba(Xr[te])[:, 1]

y = R["y"].values.astype(bool)
res = {"n_real": len(R), "fraud": int(y.sum()), "legit": int((~y).sum()), "sources": int(R["group"].nunique()), "auc": round(roc_auc_score(y, P), 3)}
for thr in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
    pr = P >= thr
    res[f"thr_{thr}"] = {"caught": f"{int((pr & y).sum())}/{int(y.sum())}", "false_alarms": f"{int((pr & ~y).sum())}/{int((~y).sum())}"}
print(json.dumps(res, indent=1))
json.dump(res, open(os.path.join(HERE, "result_bec_v4.json"), "w"), indent=1)
# final model on everything, for the app
X = np.vstack([Xr, Xr, Xr, Xp, Xs]); Y = np.concatenate([R["y"].values] * 3 + [pub["y"].values, syn["y"].values])
import joblib
if __name__ == "__main__":
    joblib.dump(LogisticRegression(C=1.0, class_weight="balanced", max_iter=3000).fit(X, Y), os.path.join(ROOT, "models", "bec_v4.joblib"))
