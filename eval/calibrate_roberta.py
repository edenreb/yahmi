"""Fit temperature scaling on source-grouped OOF RoBERTa scores and record thresholds."""
from __future__ import annotations

import hashlib
import json
import os
import sys

import numpy as np
from scipy.optimize import minimize_scalar
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from cv_roberta_live import load_real  # noqa: E402

RESULT = os.path.join(HERE, "result_cv_roberta_vs_live.json")
OUT = os.path.join(HERE, "result_roberta_calibration.json")
EPS = 1e-6


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def apply_temperature(p, temperature):
    z = logit(p)
    return 1 / (1 + np.exp(-z / temperature))


def fit_temperature(p, y):
    z = logit(p)

    def nll(temperature):
        q = 1 / (1 + np.exp(-z / temperature))
        return log_loss(y, q)

    result = minimize_scalar(nll, bounds=(0.05, 100.0), method="bounded")
    return float(result.x)


def at_false_alarm_budget(p, y, budget):
    best = None
    for threshold in np.linspace(0.0, 1.0, 100001):
        flagged = p >= threshold
        false_alarms = int((flagged & ~y).sum())
        caught = int((flagged & y).sum())
        if false_alarms <= budget and (best is None or caught > best["caught"]):
            best = {
                "threshold": round(float(threshold), 6),
                "caught": caught,
                "false_alarms": false_alarms,
            }
    return best


def block(p, y):
    return {
        "n_fraud": int(y.sum()),
        "n_legit": int((~y).sum()),
        "auc": round(float(roc_auc_score(y, p)), 4),
        "average_precision": round(float(average_precision_score(y, p)), 4),
        "log_loss": round(float(log_loss(y, p)), 4),
        "brier": round(float(brier_score_loss(y, p)), 4),
    }


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    result = json.load(open(RESULT, encoding="utf-8"))
    texts, labels, groups, types = load_real()
    scores = np.asarray(result["scores"]["roberta_cv"], dtype=float)
    if len(scores) != len(labels):
        raise SystemExit(f"score/label mismatch: {len(scores)} != {len(labels)}")

    y = labels.astype(bool)
    live = np.asarray(result["scores"]["bec_final_recipe_cv"], dtype=float)
    live_amber_fa = int(((live >= 0.62) & ~y).sum())
    live_red_fa = int(((live >= 0.80) & ~y).sum())

    temperature = fit_temperature(scores, y)
    calibrated = apply_temperature(scores, temperature)

    budgets = {
        "amber_equal_live_false_alarms": live_amber_fa,
        "red_equal_live_false_alarms": live_red_fa,
        "red_zero_false_alarms": 0,
    }
    operating_points = {
        name: at_false_alarm_budget(calibrated, y, budget)
        for name, budget in budgets.items()
    }

    at_fixed = {}
    for name, threshold in (("amber_0_62", 0.62), ("red_0_80", 0.80)):
        flagged = calibrated >= threshold
        at_fixed[name] = {
            "threshold": threshold,
            "caught": int((flagged & y).sum()),
            "false_alarms": int((flagged & ~y).sum()),
        }

    out = {
        "dataset": result["dataset"],
        "n": int(len(y)),
        "fraud": int(y.sum()),
        "legit": int((~y).sum()),
        "sources": int(len(set(groups))),
        "source_result": os.path.basename(RESULT),
        "source_result_sha256": sha256(RESULT),
        "method": "temperature scaling on source-grouped OOF scores",
        "temperature": round(temperature, 6),
        "raw": block(scores, y),
        "calibrated": block(calibrated, y),
        "live_recipe_fixed_thresholds": {
            "amber_0_62": {
                "caught": int(((live >= 0.62) & y).sum()),
                "false_alarms": live_amber_fa,
            },
            "red_0_80": {
                "caught": int(((live >= 0.80) & y).sum()),
                "false_alarms": live_red_fa,
            },
        },
        "operating_points_development": operating_points,
        "calibrated_at_fixed_thresholds": at_fixed,
        "caveats": [
            "Temperature is fitted on fold-model out-of-fold scores, not on the final all-data model.",
            "Thresholds were selected on development CV at live false-alarm budgets; they are provisional and must be frozen before the fresh holdout is scored.",
            "This is not a holdout result and does not support promotion.",
        ],
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), indent=1)
    print(json.dumps(out, indent=1))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
