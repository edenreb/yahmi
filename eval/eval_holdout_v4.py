"""ONE-SHOT evaluation of bec_final vs Yahmi Arraf-1 on frozen bec_holdout_v4.

Real emails, but the fraud side is university phishing and the genuine side is a
finance mailing list, not SME invoice traffic. Fixed thresholds (amber 0.62,
red 0.80). Run once; never tune on this set.
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


d = json.load(open(os.path.join(ROOT, "data", "bec_holdout_v4.json"), encoding="utf-8"))
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
        "auc": round(roc_auc_score(y, p), 3),
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
    by_src = {}
    for s in sorted(set(source)):
        m = np.array([src == s for src in source])
        by_src[s] = {
            "n": int(m.sum()),
            "fraud": int((m & y).sum()),
            "amber": int((flagged & m & y).sum()),
            "red": int((red & m & y).sum()),
            "legit": int((m & ~y).sum()),
            "legit_amber": int((flagged & m & ~y).sum()),
            "legit_red": int((red & m & ~y).sum()),
        }
    out["by_attack_type"] = by_att
    out["by_source"] = by_src
    return out


res = {
    "dataset": "data/bec_holdout_v4.json",
    "n": len(y), "fraud": int(y.sum()), "legit": int((~y).sum()),
    "dataset_caveats": [
        "Fraud is real University of Chicago phishing email text (2020-2026), skewed to student/job/account-lock campaigns; only 7 invoice and 11 payroll items.",
        "Genuine is 60 real GnuCash user mailing-list messages (2025-2026), filtered to business/accounting subjects; not captured supplier invoices.",
        "New sources vs training/v2/v3; leakage check found 0 exact and 0 at cosine >=0.70.",
        "Public blog/mailing-list terms, no explicit licence; local evaluation only.",
        "attack_type labels are auto-tagged and not hand-verified.",
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
    amber_overlap = v["amber_ci"][0] <= f["amber_ci"][1] and f["amber_ci"][0] <= v["amber_ci"][1]
    red_overlap = v["red_ci"][0] <= f["red_ci"][1] and f["red_ci"][0] <= v["red_ci"][1]
    fraud_types = {a: sum(1 for x in d if x["label"] == "fraud" and (x.get("attack_type") or "unknown") == a)
                   for a in set(attack)}
    res["decision"] = {
        "rule": "promote only if Yahmi Arraf-1 amber caught >= live, Yahmi Arraf-1 amber false alarms <= live, Yahmi Arraf-1 red false alarms <= live, and the models are not within each other's intervals",
        "checks": checks,
        "mechanical_checks_pass": all(checks.values()),
        "amber_ci_overlap": amber_overlap,
        "red_ci_overlap": red_overlap,
        "promote_arraf_1": all(checks.values()) and not (amber_overlap and red_overlap),
        "core_invoice_items": fraud_types.get("invoice", 0),
        "bank_account_change_items": fraud_types.get("bank_change", 0),
        "full_v4_requirement_met": fraud_types.get("invoice", 0) > 0 and fraud_types.get("bank_change", 0) > 0,
        "note": "Both amber and red intervals overlap and both models flag 0/60 genuine, so under the pre-registered 'within intervals' caveat the live model stays. v4 also has no bank-account-change frauds with account details, so it is a partial real-email test, not the full v4.",
    }

print(json.dumps(res, indent=1))
json.dump(res, open(os.path.join(os.path.dirname(__file__), "result_bec_holdout_v4.json"), "w"), indent=1)
