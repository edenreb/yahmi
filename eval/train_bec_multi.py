"""Arabic/multilingual email model: multilingual embeddings + cue flags, logistic regression trained on the
English data only (same pool as train_bec_v4). Used by the app for messages that are mostly Arabic.
Tested on 82 real Arabic messages it never saw (result_ar_transfer.json, 'lr' at the app's fixed thresholds)."""
import os, joblib, numpy as np
os.environ["EMB_MODEL"] = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
import train_bec_v4 as V
from sklearn.linear_model import LogisticRegression
X = np.vstack([V.Xr, V.Xr, V.Xr, V.Xp, V.Xs]); Y = np.concatenate([V.R["y"].values] * 3 + [V.pub["y"].values, V.syn["y"].values])
joblib.dump({"lr": LogisticRegression(C=1.0, class_weight="balanced", max_iter=3000).fit(X, Y), "emb_model": V.EMB_MODEL, "cue_weight": 0.5},
            os.path.join(V.ROOT, "models", "bec_multi.joblib"))
print("saved")
