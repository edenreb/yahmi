"""Cross-lingual test: train on English only (348 real + public + synthetic), test on 82 real Arabic messages.
Nothing Arabic is used for training, so this measures transfer, not memorisation."""
import json, os, numpy as np
os.environ.setdefault("EMB_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
import train_bec_v4 as V
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
X = np.vstack([V.Xr, V.Xr, V.Xr, V.Xp, V.Xs]); Y = np.concatenate([V.R["y"].values] * 3 + [V.pub["y"].values, V.syn["y"].values])
A = json.load(open(os.path.join(V.ROOT, "data", "bec_arabic.json")))
ta = [((a.get("subject") or "") + "\n" + a["body"]).strip() for a in A]; ya = np.array([a["label"] == "fraud" for a in A])
Xa = V.feats(ta)
lr = LogisticRegression(C=1.0, class_weight="balanced", max_iter=3000).fit(X, Y)
gb = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=0).fit(X, Y)
out = {"model": V.EMB_MODEL, "n": len(A), "fraud": int(ya.sum())}
for name, p in (("lr", lr.predict_proba(Xa)[:, 1]), ("gbm", gb.predict_proba(Xa)[:, 1]), ("mean", (lr.predict_proba(Xa)[:, 1] + gb.predict_proba(Xa)[:, 1]) / 2)):
    r = {"auc": round(roc_auc_score(ya, p), 3)}
    for th in (0.5, 0.62, 0.8):
        r[str(th)] = f"caught {int((p[ya] >= th).sum())}/{ya.sum()}, false {int((p[~ya] >= th).sum())}/{(~ya).sum()}"
    out[name] = r
    if name == "mean":
        np.save(os.path.join(V.HERE, "ar_preds.npy"), p)
print(json.dumps(out, indent=1, ensure_ascii=False))
json.dump(out, open(os.path.join(V.HERE, "result_ar_transfer.json"), "w"), indent=1)
