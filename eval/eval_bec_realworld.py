"""Compare fraud-email detectors on the 70 REAL published emails (45 fraud, 25 legit).
A: wording model trained on public phishing + synthetic (never saw these emails).
B: hand-written cue score with fixed weights (never fitted to these emails).
C: combined: max-style blend of A and B.
Also reports a cross-validated learned model where folds are split by SOURCE WEBSITE, so the
model is never tested on emails from a site it learned from."""
import json
import os
import sys
from collections import Counter

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from yahmi.cues import cue_hits, cue_score  # noqa

ROOT = os.path.join(os.path.dirname(__file__), "..")
d = json.load(open(os.path.join(ROOT, "data", "bec_realworld.json")))
texts = [(x.get("subject") or "") + "\n" + x["body"] for x in d]
y = np.array([x["label"] == "fraud" for x in d])
src = [x["source_url"].split("/")[2] for x in d]
warn = np.array(["warning" in (x.get("notes") or "").lower() or "notice" in (x.get("notes") or "").lower() for x in d])
model = joblib.load(os.path.join(ROOT, "models", "bec.joblib"))
A = model.predict_proba(texts)[:, 1]
B = np.array([cue_score(t) for t in texts])
C = np.maximum(B, A * 0.8)


def st(p, thr, mask=None):
    m = np.ones(len(y), bool) if mask is None else mask
    yy, pp = y[m], p[m] >= thr
    return {"caught": f"{int((pp & yy).sum())}/{int(yy.sum())}", "false_alarms": f"{int((pp & ~yy).sum())}/{int((~yy).sum())}", "auc": round(roc_auc_score(yy, p[m]), 3)}


res = {"n": len(y), "fraud": int(y.sum()), "legit": int((~y).sum()), "sources": dict(Counter(src))}
for name, p in [("A_wording_model", A), ("B_cue_rules", B), ("C_combined", C)]:
    res[name] = {f"thr_{t}": st(p, t) for t in (0.4, 0.5, 0.6)}
# learned on cues + wording score, cross-validated by source website
X = np.column_stack([np.array([[float(v) for v in cue_hits(t).values()] for t in texts]), A])
groups = sorted(set(src))
P = np.zeros(len(y))
for g in groups:
    te = np.array([s == g for s in src]); tr = ~te
    if len(set(y[tr])) < 2:
        P[te] = 0.5; continue
    clf = LogisticRegression(C=1.0, class_weight="balanced", max_iter=1000).fit(X[tr], y[tr])
    P[te] = clf.predict_proba(X[te])[:, 1]
res["D_learned_cv_by_source"] = {f"thr_{t}": st(P, t) for t in (0.4, 0.5, 0.6)}
print(json.dumps(res, indent=1))
json.dump(res, open(os.path.join(os.path.dirname(__file__), "result_bec_realworld.json"), "w"), indent=1)
misses = [(round(float(c), 2), x["label"], t[:90].replace("\n", " ")) for c, x, t in zip(C, d, texts) if (c >= 0.5) != (x["label"] == "fraud")]
for m in misses:
    print(m)
