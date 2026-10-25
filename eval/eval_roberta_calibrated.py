"""Compare the calibrated RoBERTa development policy with the live recipe on OOF scores."""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from cv_roberta_live import load_real  # noqa: E402
from eval_holdout_v5 import compare  # noqa: E402

CV_RESULT = os.path.join(HERE, "result_cv_roberta_vs_live.json")
CALIBRATION = os.path.join(HERE, "result_roberta_calibration.json")
OUT = os.path.join(HERE, "result_roberta_calibrated_vs_live.json")
EPS = 1e-6


def wilson(k, n, z=1.96):
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(100 * max(0.0, centre - half), 1), round(100 * min(1.0, centre + half), 1)]


def calibrated(p, temperature):
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    z = np.log(p / (1 - p))
    return 1 / (1 + np.exp(-z / temperature))


def block(p, y, amber, red):
    flagged = p >= amber
    red_flagged = p >= red
    caught_amber = int((flagged & y).sum())
    caught_red = int((red_flagged & y).sum())
    fa_amber = int((flagged & ~y).sum())
    fa_red = int((red_flagged & ~y).sum())
    return {
        "n_fraud": int(y.sum()),
        "n_legit": int((~y).sum()),
        "amber_threshold": amber,
        "red_threshold": red,
        "fraud_caught_amber": caught_amber,
        "fraud_caught_red": caught_red,
        "false_alarms_amber": fa_amber,
        "false_alarms_red": fa_red,
        "auc": round(float(roc_auc_score(y, p)), 4),
        "average_precision": round(float(average_precision_score(y, p)), 4),
        "amber_ci": wilson(caught_amber, int(y.sum())),
        "red_ci": wilson(caught_red, int(y.sum())),
        "fa_amber_ci": wilson(fa_amber, int((~y).sum())),
        "fa_red_ci": wilson(fa_red, int((~y).sum())),
    }


def by_type(p, y, types, amber, red):
    flagged = p >= amber
    red_flagged = p >= red
    out = {}
    for name in sorted(set(types)):
        mask = types == name
        out[name] = {
            "n": int((mask & y).sum()),
            "amber": int((flagged & mask & y).sum()),
            "red": int((red_flagged & mask & y).sum()),
            "false_alarms": int((flagged & mask & ~y).sum()),
        }
    return out


def main():
    cv = json.load(open(CV_RESULT, encoding="utf-8"))
    calibration = json.load(open(CALIBRATION, encoding="utf-8"))
    texts, y, groups, types = load_real()
    p_live = np.asarray(cv["scores"]["bec_final_recipe_cv"], dtype=float)
    p_raw = np.asarray(cv["scores"]["roberta_cv"], dtype=float)
    p_roberta = calibrated(p_raw, calibration["temperature"])
    amber = calibration["operating_points_development"]["amber_equal_live_false_alarms"]["threshold"]
    red = calibration["operating_points_development"]["red_equal_live_false_alarms"]["threshold"]

    live = block(p_live, y.astype(bool), 0.62, 0.80)
    roberta = block(p_roberta, y.astype(bool), amber, red)
    live_amber = p_live >= 0.62
    live_red = p_live >= 0.80
    roberta_amber = p_roberta >= amber
    roberta_red = p_roberta >= red

    out = {
        "dataset": cv["dataset"],
        "n": int(len(y)),
        "fraud": int(y.sum()),
        "legit": int((~y).sum()),
        "sources": int(len(set(groups))),
        "setup": "source-grouped 5-fold OOF scores; RoBERTa temperature and thresholds fitted on the same OOF data",
        "calibration": {
            "temperature": calibration["temperature"],
            "amber_threshold": amber,
            "red_threshold": red,
        },
        "models": {
            "bec_final_recipe": live,
            "roberta_calibrated": roberta,
        },
        "comparison_amber": compare(roberta_amber, live_amber, y.astype(bool), "roberta calibrated vs live, amber"),
        "comparison_red": compare(roberta_red, live_red, y.astype(bool), "roberta calibrated vs live, red"),
        "by_type": {
            "bec_final_recipe": by_type(p_live, y.astype(bool), types, 0.62, 0.80),
            "roberta_calibrated": by_type(p_roberta, y.astype(bool), types, amber, red),
        },
        "caveats": [
            "OOF development comparison, not a fresh holdout.",
            "Temperature and thresholds were fitted/selected on these same OOF scores, so the operating points are optimistic and frozen only for the future holdout.",
            "The live recipe was retrained on each fold because the live artifact trained on all 348 real emails.",
            "Public/synthetic training text may share wording with real sources; both models saw the same pool.",
            "No candidate artifact was scored here; this evaluates the calibrated policy, not the saved all-data model.",
        ],
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), indent=1)
    print(json.dumps({k: out[k] for k in ("models", "comparison_amber", "comparison_red", "calibration")}, indent=1))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
