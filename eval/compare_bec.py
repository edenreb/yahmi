"""Compare model variants on the real emails with leave-one-source-out CV (same folds for all)."""
import json, os, sys, hashlib
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import train_bec_v4 as V  # reuses data loading + cached embeddings (also refits v4; cheap with cache)
from yahmi.cues import cue_hits

R, Xr, Xp, Xs, pub, syn = V.R, V.Xr, V.Xp, V.Xs, V.pub, V.syn
y = R["y"].values.astype(bool); groups = R["group"].values
texts = R["text"].tolist(); ptext = pub["text"].tolist(); stext = syn["text"].tolist()


def cv(fn):
    P = np.zeros(len(R))
    for g in np.unique(groups):
        te = groups == g
        P[te] = fn(~te, te)
    return P


def lr_emb(tr, te):
    X = np.vstack([Xr[tr]] * 3 + [Xp, Xs]); Y = np.concatenate([R["y"].values[tr]] * 3 + [pub["y"].values, syn["y"].values])
    return LogisticRegression(C=1.0, class_weight="balanced", max_iter=3000).fit(X, Y).predict_proba(Xr[te])[:, 1]


def lr_real_only(tr, te):
    return LogisticRegression(C=1.0, class_weight="balanced", max_iter=3000).fit(Xr[tr], R["y"].values[tr]).predict_proba(Xr[te])[:, 1]


def tfidf_real(tr, te):
    v = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)
    A = v.fit_transform([texts[i] for i in np.where(tr)[0]])
    m = LogisticRegression(C=4.0, class_weight="balanced", max_iter=3000).fit(A, R["y"].values[tr])
    return m.predict_proba(v.transform([texts[i] for i in np.where(te)[0]]))[:, 1]


def hgb(tr, te):
    X = np.vstack([Xr[tr]] * 3 + [Xp, Xs]); Y = np.concatenate([R["y"].values[tr]] * 3 + [pub["y"].values, syn["y"].values])
    return HistGradientBoostingClassifier(max_iter=200, learning_rate=0.08).fit(X, Y).predict_proba(Xr[te])[:, 1]


res = {}
preds = {}
for name, fn in [("emb_lr_mixed", lr_emb), ("emb_lr_real_only", lr_real_only), ("tfidf_real_only", tfidf_real), ("emb_gbm_mixed", hgb)]:
    P = cv(fn); preds[name] = P
    res[name] = {"auc": round(roc_auc_score(y, P), 3)}
ens = (preds["emb_lr_mixed"] + preds["tfidf_real_only"] + preds["emb_lr_real_only"]) / 3
preds["ensemble"] = ens; res["ensemble"] = {"auc": round(roc_auc_score(y, ens), 3)}
from yahmi.cues import cue_score
cue = np.array([cue_score(t) for t in texts])
e2 = (preds["emb_gbm_mixed"] + preds["tfidf_real_only"] + preds["emb_lr_mixed"]) / 3
preds["ensemble2_gbm_tfidf_lr"] = e2; res["ensemble2_gbm_tfidf_lr"] = {"auc": round(roc_auc_score(y, e2), 3)}
e3 = 0.85 * e2 + 0.15 * cue
preds["ensemble3_plus_cues"] = e3; res["ensemble3_plus_cues"] = {"auc": round(roc_auc_score(y, e3), 3)}
ens = e3
for name, P in preds.items():
    # operating point: best catch rate with false alarms <= 10%
    best = None
    for thr in np.linspace(0.05, 0.95, 91):
        pr = P >= thr; fa = (pr & ~y).sum() / (~y).sum(); ca = (pr & y).sum() / y.sum()
        if fa <= 0.10 and (best is None or ca > best[1]):
            best = (round(float(thr), 2), round(float(ca), 3), round(float(fa), 3), f"{int((pr & y).sum())}/{int(y.sum())}", f"{int((pr & ~y).sum())}/{int((~y).sum())}")
    res[name]["at_<=10%_false_alarms"] = best
types = R["type"].values
res["e3_by_type_at_best"] = {}
thr = res["ensemble3_plus_cues"]["at_<=10%_false_alarms"][0]
for t in sorted(set(types)):
    m = types == t
    res["e3_by_type_at_best"][t or "(old set)"] = f"{int((ens[m] >= thr).sum())}/{int(m.sum())} flagged"
print(json.dumps(res, indent=1))
np.savez(os.path.join(os.path.dirname(__file__), "cv_preds" + ("" if V.EMB_MODEL.startswith("BAAI/bge-small-en") else "_" + V.EMB_MODEL.split("/")[-1]) + ".npz"), y=y, e2=preds["ensemble2_gbm_tfidf_lr"], types=types)
json.dump(res, open(os.path.join(os.path.dirname(__file__), "result_bec_compare" + ("" if V.EMB_MODEL.startswith("BAAI/bge-small-en") else "_" + V.EMB_MODEL.split("/")[-1]) + ".json"), "w"), indent=1)
