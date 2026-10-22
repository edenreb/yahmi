"""ONE-SHOT evaluation of bec_final vs Yahmi Arraf-1 on the frozen bec_holdout_v3 set.

Run once; thresholds are the fixed production thresholds (amber 0.62, red 0.80).
Never tune on this set. The genuine side is a published-transactional-template proxy,
not captured customer email; see the manifest and FROZEN.txt.
Mirrors yahmi/app.py scoring: mean of embedding-GBM, embedding-LR and TF-IDF-LR,
with mostly-Arabic texts routed to bec_multi.
"""
import json
import math
import os
import sys

import joblib
import numpy as np
from sklearn.metrics import roc_auc_score

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

ROOT = os.path.join(os.path.dirname(__file__), "..")
AMBER, RED = 0.62, 0.80

from fastembed import TextEmbedding
from yahmi.cues import cue_hits  # noqa


class _Ensemble:
    def __init__(self, path):
        self.path = path
        self.emb = TextEmbedding("BAAI/bge-small-en-v1.5", max_length=128)
        self.m = joblib.load(path)
        self.multi = None

    def _arabic_share(self, t):
        letters = [c for c in t if c.isalpha()]
        return sum("\u0600" <= c <= "\u06ff" for c in letters) / max(len(letters), 1)

    def predict_proba(self, texts):
        mpath = os.path.join(os.path.dirname(self.path), "bec_multi.joblib")
        E = np.array(list(self.emb.embed([t[:700] for t in texts])))
        C = np.array([[float(v) for v in cue_hits(t).values()] for t in texts]) * self.m["cue_weight"]
        X = np.hstack([E, C])
        p = (self.m["gbm"].predict_proba(X)[:, 1]
             + self.m["lr"].predict_proba(X)[:, 1]
             + self.m["tlr"].predict_proba(self.m["tfidf"].transform(texts))[:, 1]) / 3
        ar = [i for i, t in enumerate(texts) if self._arabic_share(t) > 0.3]
        if ar and os.path.exists(mpath):
            if self.multi is None:
                self.multi = joblib.load(mpath)
                self.memb = TextEmbedding(self.multi["emb_model"], max_length=128)
            sub = [texts[i] for i in ar]
            Em = np.array(list(self.memb.embed([t[:700] for t in sub])))
            Cm = np.array([[float(v) for v in cue_hits(t).values()] for t in sub]) * self.multi["cue_weight"]
            p[ar] = self.multi["lr"].predict_proba(np.hstack([Em, Cm]))[:, 1]
        return p


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (100 * (centre - half), 100 * (centre + half))


d = json.load(open(os.path.join(ROOT, "data", "bec_holdout_v3.json"), encoding="utf-8"))
texts = [(x.get("subject") or "") + "\n" + x["body"] for x in d]
y = np.array([x["label"] == "fraud" for x in d])
attack = [x.get("attack_type") or "unknown" for x in d]
source = [x.get("source") or "unknown" for x in d]


def st(p):
    flagged = p >= AMBER
    red = p >= RED
    caught_amp = int((flagged & y).sum())
    caught_red = int((red & y).sum())
    fa_amp = int((flagged & ~y).sum())
    fa_red = int((red & ~y).sum())
    out = {
        "n_fraud": int(y.sum()), "n_legit": int((~y).sum()),
        "fraud_caught_amber": caught_amp,
        "fraud_caught_red": caught_red,
        "false_alarms_amber": fa_amp, "false_alarms_red": fa_red,
        "auc": round(roc_auc_score(y, p), 3) if len(set(y.tolist())) > 1 else None,
        "amber_ci": [round(v, 1) for v in wilson(caught_amp, int(y.sum()))],
        "red_ci": [round(v, 1) for v in wilson(caught_red, int(y.sum()))],
        "fa_amber_ci": [round(v, 1) for v in wilson(fa_amp, int((~y).sum()))],
        "fa_red_ci": [round(v, 1) for v in wilson(fa_red, int((~y).sum()))],
        "amber_threshold": AMBER,
        "red_threshold": RED,
    }
    by_att = {}
    for a in sorted(set(attack)):
        m = np.array([ak == a for ak in attack]) & y
        if m.sum() == 0:
            continue
        by_att[a] = {"n": int(m.sum()), "amber": int((flagged & m).sum()), "red": int((red & m).sum())}
    leg_src = {}
    for s in sorted(set(source)):
        m = np.array([src == s for src in source]) & ~y
        if m.sum() == 0:
            continue
        leg_src[s] = {"n": int(m.sum()), "amber": int((flagged & m).sum()), "red": int((red & m).sum())}
    out["fraud_by_attack_type"] = by_att
    out["legit_by_source"] = leg_src
    return out


res = {
    "dataset": "data/bec_holdout_v3.json",
    "n": len(y), "fraud": int(y.sum()), "legit": int((~y).sum()),
    "dataset_caveats": [
        "Fraud is real published email text from Penn State, Hope College and Carnegie Mellon archives.",
        "Genuine is published transactional email templates (Magento, OpenMage, Odoo, Crater), not captured customer emails; placeholders remain.",
        "English only. Sources are new relative to training/v2; max text similarity to any training/v2/public-CSV item was <0.70 before freezing.",
        "attack_type labels are coarse and not hand-verified for every item; per-type numbers are descriptive only.",
    ],
    "models": {},
}
probs = {}
for name, rel in [("bec_final", "models/bec_final.joblib"),
                  ("Yahmi Arraf-1", "models/candidates/yahmi_arraf_1.joblib")]:
    path = os.path.join(ROOT, rel)
    if not os.path.exists(path):
        res["models"][name] = {"error": "missing model file"}
        continue
    model = _Ensemble(path)
    p = model.predict_proba(texts)
    probs[name] = p
    res["models"][name] = st(p)

if "bec_final" in probs and "Yahmi Arraf-1" in probs:
    f = res["models"]["bec_final"]
    v = res["models"]["Yahmi Arraf-1"]
    checks = {
        "arraf_1_amber_caught_at_least_live": v["fraud_caught_amber"] >= f["fraud_caught_amber"],
        "arraf_1_amber_false_no_more_than_live": v["false_alarms_amber"] <= f["false_alarms_amber"],
        "arraf_1_red_false_no_more_than_live": v["false_alarms_red"] <= f["false_alarms_red"],
    }
    res["decision"] = {
        "rule": "promote only if Yahmi Arraf-1 amber caught >= live, Yahmi Arraf-1 amber false alarms <= live, Yahmi Arraf-1 red false alarms <= live",
        "checks": checks,
        "promote_arraf_1": all(checks.values()),
        "note": "Template-proxy genuine side; do not promote on this set alone. Live model stays unless a human accepts the caveat.",
    }

print(json.dumps(res, indent=1))
json.dump(res, open(os.path.join(os.path.dirname(__file__), "result_bec_holdout_v3.json"), "w"), indent=1)
