"""Fraud-email model v3: sentence embeddings (BAAI/bge-small-en-v1.5) + logistic regression.
Trained on the public phishing dataset (80% split) + synthetic invoice emails. Tested on the held-out 20%
and, zero-shot, on the 70 real published emails it never saw. Also tests embeddings + cue features."""
import json
import os
import re
import sys

import joblib
import numpy as np
import pandas as pd
from fastembed import TextEmbedding
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from yahmi.cues import cue_hits, cue_score  # noqa

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
emb = TextEmbedding("BAAI/bge-small-en-v1.5", max_length=128)
E = lambda xs: np.array(list(emb.embed([x[:700] for x in xs], batch_size=64)))

df = pd.read_csv(os.path.join(ROOT, "data", "dl", "phishing_email.csv")).dropna(subset=["Email Text"])
df["text"] = df["Email Text"].astype(str)
df = df[df["text"].str.strip().str.len() > 20].drop_duplicates("text")
df["y"] = (df["Email Type"] == "Phishing Email").astype(int)
tr, te = train_test_split(df, test_size=0.2, random_state=42, stratify=df["y"])
tr = tr.sample(n=min(2000, len(tr)), random_state=1)
te = te.sample(n=min(500, len(te)), random_state=1)
syn = pd.DataFrame(json.load(open(os.path.join(HERE, "synthetic_bec_train.json"))))
Xtr = np.vstack([E(tr["text"].tolist()), E(syn["text"].tolist())]); ytr = np.concatenate([tr["y"].values, syn["y"].values])
clf = LogisticRegression(C=2.0, class_weight="balanced", max_iter=3000).fit(Xtr, ytr)
pte = clf.predict_proba(E(te["text"].tolist()))[:, 1]

d = json.load(open(os.path.join(ROOT, "data", "bec_realworld.json")))
texts = [(x.get("subject") or "") + "\n" + x["body"] for x in d]
y = np.array([x["label"] == "fraud" for x in d])
prw = clf.predict_proba(E(texts))[:, 1]
cue = np.array([cue_score(t) for t in texts])
comb = np.maximum(cue, prw)


def st(yy, p, thr):
    yy = np.asarray(yy).astype(bool); pr = p >= thr
    return {"caught": f"{int((pr & yy).sum())}/{int(yy.sum())}", "false_alarms": f"{int((pr & ~yy).sum())}/{int((~yy).sum())}", "auc": round(roc_auc_score(yy, p), 3)}


res = {"heldout_dataset": st(te["y"].values, pte, 0.5),
       "real_world_embed": {f"thr_{t}": st(y, prw, t) for t in (0.5, 0.6, 0.7)},
       "real_world_embed_plus_cues": {f"thr_{t}": st(y, comb, t) for t in (0.5, 0.6, 0.7)}}
print(json.dumps(res, indent=1))
json.dump(res, open(os.path.join(HERE, "result_bec_embed.json"), "w"), indent=1)
joblib.dump(clf, os.path.join(ROOT, "models", "bec_embed_lr.joblib"))
