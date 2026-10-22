"""ONE-SHOT Arabic stress test of the live multilingual model on arabic_holdout_v1.

Translated APEC + Ghabban + Odoo templates, not native captured email. Fixed
thresholds (amber 0.62, red 0.80). Run once; never tune on this set.
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


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (100 * (centre - half), 100 * (centre + half))


d = json.load(open(os.path.join(ROOT, "data", "arabic_holdout_v1.json"), encoding="utf-8"))
texts = [(x.get("subject") or "") + "\n" + x["body"] for x in d]
y = np.array([x["label"] == "fraud" for x in d])
attack = [x.get("attack_type") or "unknown" for x in d]
source = [x.get("source_title") or "unknown" for x in d]

m = joblib.load(os.path.join(ROOT, "models", "bec_multi.joblib"))
emb = TextEmbedding(m["emb_model"], max_length=128)
E = np.array(list(emb.embed([t[:700] for t in texts])))
C = np.array([[float(v) for v in cue_hits(t).values()] for t in texts]) * m["cue_weight"]
p = m["lr"].predict_proba(np.hstack([E, C]))[:, 1]

flagged = p >= AMBER
red = p >= RED
caught_amp = int((flagged & y).sum())
caught_red = int((red & y).sum())
fa_amp = int((flagged & ~y).sum())
fa_red = int((red & ~y).sum())

by_att = {}
for a in sorted(set(attack)):
    mask = np.array([ak == a for ak in attack]) & y
    if mask.sum() == 0:
        continue
    by_att[a] = {
        "n": int(mask.sum()),
        "amber": int((flagged & mask).sum()),
        "red": int((red & mask).sum()),
    }

def source_class(title):
    if title.startswith("APEC"):
        return "APEC (machine-translated)"
    if title.startswith("Odoo"):
        return "Odoo template"
    if title.startswith("Ghabban"):
        return "Ghabban sample"
    return "other"


leg_src = {}
for s in sorted(set(source)):
    mask = np.array([src == s for src in source]) & ~y
    if mask.sum() == 0:
        continue
    key = source_class(s)
    row = leg_src.setdefault(key, {"n": 0, "amber": 0, "red": 0})
    row["n"] += int(mask.sum())
    row["amber"] += int((flagged & mask).sum())
    row["red"] += int((red & mask).sum())

res = {
    "dataset": "data/arabic_holdout_v1.json",
    "model": "models/bec_multi.joblib",
    "n": len(y), "fraud": int(y.sum()), "legit": int((~y).sum()),
    "amber_threshold": AMBER,
    "red_threshold": RED,
    "fraud_caught_amber": caught_amp,
    "fraud_caught_red": caught_red,
    "false_alarms_amber": fa_amp,
    "false_alarms_red": fa_red,
    "auc": round(roc_auc_score(y, p), 3),
    "amber_ci": [round(v, 1) for v in wilson(caught_amp, int(y.sum()))],
    "red_ci": [round(v, 1) for v in wilson(caught_red, int(y.sum()))],
    "fa_amber_ci": [round(v, 1) for v in wilson(fa_amp, int((~y).sum()))],
    "fa_red_ci": [round(v, 1) for v in wilson(fa_red, int((~y).sum()))],
    "fraud_by_attack_type": by_att,
    "legit_by_source": leg_src,
    "dataset_caveats": [
        "APEC Arabic is machine-translated, not native; 17 APEC legitimate rows are curated business-like text.",
        "16 legitimate items are Odoo Arabic transactional templates, not captured email.",
        "APEC is CC BY-NC-SA 4.0 with an underlying NDA restriction; local evaluation only.",
        "Labels were curated by the collector, not independently hand-verified item by item.",
        "This is a translated/template stress test, not a native Arabic customer-email holdout.",
    ],
}
print(json.dumps(res, ensure_ascii=False, indent=1))
json.dump(res, open(os.path.join(os.path.dirname(__file__), "result_arabic_holdout.json"), "w"), ensure_ascii=False, indent=1)
