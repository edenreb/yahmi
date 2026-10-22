"""ONE-SHOT evaluation on frozen data/bec_holdout_v5.json.

Pre-registered decision rule, written before scoring:
- A candidate beats live only if it catches at least as many frauds at amber,
  has no more amber false alarms, and has no more red false alarms.
- If both candidates beat live, compare them directly: more amber captures wins;
  ties go to more red captures, then fewer amber false alarms.
- Promotion needs the winner to beat live on at least one metric without losing
  on another, and to beat the other passing candidate with a two-sided exact
  McNemar p < 0.05 on amber captures (or red captures when amber captures tie).
  Otherwise the live model stays.

Fixed thresholds (amber 0.62, red 0.80). Run once; never tune on this set.
"""
import hashlib
import json
import math
import os
import sys

import joblib
import numpy as np
from scipy.stats import binomtest
from sklearn.metrics import roc_auc_score

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

ROOT = os.path.join(os.path.dirname(__file__), "..")
AMBER, RED = 0.62, 0.80
DATASET = os.path.join(ROOT, "data", "bec_holdout_v5.json")
EXPECTED_SHA = "0ba2f4502e9cb7fa3085ab3cdeac0e519abe36ea3b922d816bff9619a6c58363"

from fastembed import TextEmbedding
from yahmi.cues import cue_hits  # noqa


class _Ensemble:
    def __init__(self, path):
        self.path = path
        self.emb = TextEmbedding("BAAI/bge-small-en-v1.5", max_length=128)
        self.m = joblib.load(path)
        self.multi = None
        self.memb = None

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
    return (max(0.0, 100 * (centre - half)), min(100.0, 100 * (centre + half)))


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def exact_mcnemar(a, b):
    discordant = int(np.sum(a ^ b))
    if discordant == 0:
        return 1.0, 0, 0
    only_a = int(np.sum(a & ~b))
    only_b = int(np.sum(~a & b))
    return min(1.0, float(binomtest(min(only_a, only_b), discordant, 0.5).pvalue * 2)), only_a, only_b


def stats(p, y):
    flagged = p >= AMBER
    red = p >= RED
    caught_amp = int((flagged & y).sum())
    caught_red = int((red & y).sum())
    fa_amp = int((flagged & ~y).sum())
    fa_red = int((red & ~y).sum())
    return {
        "n_fraud": int(y.sum()),
        "n_legit": int((~y).sum()),
        "fraud_caught_amber": caught_amp,
        "fraud_caught_red": caught_red,
        "false_alarms_amber": fa_amp,
        "false_alarms_red": fa_red,
        "auc": round(roc_auc_score(y, p), 3),
        "amber_ci": [round(v, 1) for v in wilson(caught_amp, int(y.sum()))],
        "red_ci": [round(v, 1) for v in wilson(caught_red, int(y.sum()))],
        "fa_amber_ci": [round(v, 1) for v in wilson(fa_amp, int((~y).sum()))],
        "fa_red_ci": [round(v, 1) for v in wilson(fa_red, int((~y).sum()))],
        "amber_threshold": AMBER,
        "red_threshold": RED,
        "_flagged": flagged,
    }


def public_stats(s):
    return {k: v for k, v in s.items() if not k.startswith("_")}


def compare(a, b, y, label):
    aa = a & y
    bb = b & y
    p_amber, only_a, only_b = exact_mcnemar(aa, bb)
    ar = a & ~y
    br = b & ~y
    p_fa, fa_only_a, fa_only_b = exact_mcnemar(ar, br)
    return {
        "pair": label,
        "amber_capture_only_first": only_a,
        "amber_capture_only_second": only_b,
        "amber_capture_mcnemar_p": round(p_amber, 4),
        "amber_false_alarm_only_first": fa_only_a,
        "amber_false_alarm_only_second": fa_only_b,
        "amber_false_alarm_mcnemar_p": round(p_fa, 4),
    }


def main():
    got = sha256(DATASET)
    if got != EXPECTED_SHA:
        raise SystemExit(f"holdout hash mismatch: {got} != {EXPECTED_SHA}")

    d = json.load(open(DATASET, encoding="utf-8"))
    texts = [(x.get("subject") or "") + "\n" + x["body"] for x in d]
    y = np.array([x["label"] == "fraud" for x in d])
    source = [x.get("source") or "unknown" for x in d]

    paths = [
        ("bec_final (live)", "models/bec_final.joblib"),
        ("bec_v5", "models/candidates/bec_v5.joblib"),
        ("Yahmi Arraf-1", "models/candidates/yahmi_arraf_1.joblib"),
    ]
    res = {
        "dataset": "data/bec_holdout_v5.json",
        "dataset_sha256": got,
        "n": int(len(y)),
        "fraud": int(y.sum()),
        "legit": int((~y).sum()),
        "caveats": [
            "Fraud side is real cw-l/email-corpus spam/scam/phishing, mostly consumer product spam; NOT mainly BEC or invoice fraud.",
            "Genuine side is real Apache OFBiz user-list technical support traffic, not captured supplier invoices.",
            "Labels are source-level; attack types are not hand-verified. This cannot measure invoice false alarms or payment-history coverage.",
            "New sources vs training/v2/v3/v4; no Enron; leakage exact=0, max cosine=0.6671, 0 at >=0.70.",
            "Public sources; local evaluation only. Do not quote as BEC or invoice accuracy.",
        ],
        "models": {},
    }
    probs = {}
    flags = {}
    for name, rel in paths:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            raise SystemExit(f"missing model: {rel}")
        model = _Ensemble(path)
        p = model.predict_proba(texts)
        probs[name] = p
        s = stats(p, y)
        flags[name] = s.pop("_flagged")
        s["file"] = rel
        s["sha256"] = sha256(path)
        res["models"][name] = s
        print(name, res["models"][name]["fraud_caught_amber"], "/", int(y.sum()),
              "amber;", res["models"][name]["false_alarms_amber"], "/", int((~y).sum()),
              "false alarms", flush=True)

    live = res["models"]["bec_final (live)"]
    candidates = ["bec_v5", "Yahmi Arraf-1"]
    passed = {}
    for name in candidates:
        c = res["models"][name]
        passed[name] = (
            c["fraud_caught_amber"] >= live["fraud_caught_amber"]
            and c["false_alarms_amber"] <= live["false_alarms_amber"]
            and c["false_alarms_red"] <= live["false_alarms_red"]
        )

    decision = {
        "rule": "candidate must catch >= live at amber and have <= live amber/red false alarms; if both pass, more amber catches wins, tie broken by red catches then fewer amber false alarms; promotion also needs McNemar p<0.05 on the direct capture comparison",
        "live": "bec_final (live)",
        "mechanical_pass": passed,
    }

    for name in candidates:
        decision[f"{name}_vs_live"] = compare(
            flags[name], flags["bec_final (live)"], y, f"{name} vs live"
        )

    if "bec_v5" in passed and "Yahmi Arraf-1" in passed and passed["bec_v5"] and passed["Yahmi Arraf-1"]:
        a, b = "bec_v5", "Yahmi Arraf-1"
        ca, cb = res["models"][a], res["models"][b]
        if ca["fraud_caught_amber"] != cb["fraud_caught_amber"]:
            leader = a if ca["fraud_caught_amber"] > cb["fraud_caught_amber"] else b
            loser = b if leader == a else a
        elif ca["fraud_caught_red"] != cb["fraud_caught_red"]:
            leader = a if ca["fraud_caught_red"] > cb["fraud_caught_red"] else b
            loser = b if leader == a else a
        elif ca["false_alarms_amber"] != cb["false_alarms_amber"]:
            leader = a if ca["false_alarms_amber"] < cb["false_alarms_amber"] else b
            loser = b if leader == a else a
        else:
            leader, loser = None, None
        decision["direct_comparison"] = compare(flags[a], flags[b], y, f"{a} vs {b}")
        if leader is None:
            decision["winner"] = None
            decision["promote"] = False
            decision["reason"] = "both candidates beat live but are tied on amber, red and amber false alarms"
        else:
            if res["models"][leader]["fraud_caught_amber"] != res["models"][loser]["fraud_caught_amber"]:
                p = decision["direct_comparison"]["amber_capture_mcnemar_p"]
                metric = "amber captures"
            else:
                p_red, only_a, only_b = exact_mcnemar(
                    flags[leader] & (y == 1) & (probs[leader] >= RED),
                    flags[loser] & (y == 1) & (probs[loser] >= RED),
                )
                decision["direct_red_comparison"] = {
                    "red_capture_only_first": only_a,
                    "red_capture_only_second": only_b,
                    "red_capture_mcnemar_p": round(p_red, 4),
                }
                p = p_red
                metric = "red captures"
            decision["winner"] = leader
            decision["promote"] = p < 0.05
            decision["reason"] = (
                f"{leader} leads descriptively on {metric}; direct McNemar p={p:.4f}"
                + ("; meets pre-registered significance" if p < 0.05 else "; not significant, keep live")
            )
    else:
        winners = [n for n in candidates if passed[n]]
        decision["direct_comparison"] = None
        if len(winners) == 1:
            c = res["models"][winners[0]]
            strict = (
                c["fraud_caught_amber"] > live["fraud_caught_amber"]
                or c["false_alarms_amber"] < live["false_alarms_amber"]
                or c["false_alarms_red"] < live["false_alarms_red"]
            )
            decision["winner"] = winners[0]
            decision["promote"] = strict
            decision["reason"] = (
                f"only {winners[0]} beat live on all mechanical gates; "
                + ("strict improvement" if strict else "no strict improvement, keep live")
            )
        else:
            decision["winner"] = None
            decision["promote"] = False
            decision["reason"] = "no candidate beat live on all mechanical gates"
    res["decision"] = decision
    res["scores"] = {name: [round(float(v), 6) for v in p] for name, p in probs.items()}

    out = os.path.join(os.path.dirname(__file__), "result_bec_holdout_v5.json")
    json.dump(res, open(out, "w", encoding="utf-8"), indent=1)
    print(json.dumps(res["decision"], indent=1), flush=True)
    print("wrote", out, flush=True)


if __name__ == "__main__":
    main()
