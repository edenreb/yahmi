"""Fair before/after on the 160 new emails (bec_more2.json): 5-fold grouped by source page.
Before = current model (trained on the 348 + public + synthetic; never saw these emails).
After  = same recipe retrained on 348 + frozen 114 + the other 4 folds of the new emails.
Thresholds fixed in advance: amber 0.62, red 0.80."""
import json, os, sys, numpy as np, joblib
sys.path.insert(0, ".."); sys.path.insert(0, ".")
os.environ["BEC_FILES"] = "bec_realworld.json,bec_realworld_more.json,bec_frozen_test.json,bec_more2.json"
import train_bec_v4 as V
from sklearn.linear_model import LogisticRegression
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold
new = set(json.dumps(x["body"]) for x in json.load(open("../data/bec_more2.json")))
R = V.R; isnew = np.array([json.dumps(t.split("\n", 1)[1]) in new for t in R["text"]])
y = R["y"].values
old = joblib.load("../models/archive/bec_final_v4_backup.joblib")
def ens(m, X, T): return (m["gbm"].predict_proba(X)[:, 1] + m["lr"].predict_proba(X)[:, 1] + m["tlr"].predict_proba(m["tfidf"].transform(T))[:, 1]) / 3
T = R["text"].tolist()
idx = np.where(isnew)[0]
before = ens(old, V.Xr[idx], [T[i] for i in idx])
after = np.zeros(len(idx))
for tr_f, te_f in GroupKFold(5).split(idx, groups=R["group"].values[idx]):
    tr = np.ones(len(R), bool); tr[idx[te_f]] = False
    X = np.vstack([V.Xr[tr]] * 3 + [V.Xp, V.Xs]); Y = np.concatenate([y[tr]] * 3 + [V.pub["y"].values, V.syn["y"].values])
    m = {"gbm": HistGradientBoostingClassifier(max_iter=200, learning_rate=0.08).fit(X, Y), "lr": LogisticRegression(C=1.0, class_weight="balanced", max_iter=3000).fit(X, Y)}
    tf = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True); A = tf.fit_transform([T[i] for i in np.where(tr)[0]])
    m["tfidf"] = tf; m["tlr"] = LogisticRegression(C=4.0, class_weight="balanced", max_iter=3000).fit(A, y[tr])
    after[te_f] = ens(m, V.Xr[idx[te_f]], [T[i] for i in idx[te_f]])
yt = y[idx].astype(bool); types = R["type"].values[idx]
out = {"n": int(len(idx)), "fraud": int(yt.sum())}
for name, p in (("before", before), ("after", after)):
    r = {"auc": round(roc_auc_score(yt, p), 3)}
    for th in (0.62, 0.80):
        r[str(th)] = f"caught {int((p[yt] >= th).sum())}/{yt.sum()}, false {int((p[~yt] >= th).sum())}/{(~yt).sum()}"
    r["amber_by_type"] = {t: f"{int((p[types == t] >= .62).sum())}/{int((types == t).sum())}" for t in sorted(set(types))}
    out[name] = r
print(json.dumps(out, indent=1)); json.dump(out, open("result_more2_before_after.json", "w"), indent=1)
