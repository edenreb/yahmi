"""Train the final fraud-email ensemble on all real + public + synthetic emails and save it for the app.
Ensemble = mean of (embedding gradient-boosting, embedding logistic regression, TF-IDF logistic regression on real emails).
Validated by leave-one-source-out CV in compare_bec.py: AUC 0.927; at threshold 0.62, 162/212 real frauds caught, 13/136 real legit flagged."""
import os, sys, json
import joblib, numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import HistGradientBoostingClassifier
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import train_bec_v4 as V
from yahmi.cues import cue_score

R, Xr, Xp, Xs, pub, syn = V.R, V.Xr, V.Xp, V.Xs, V.pub, V.syn
X = np.vstack([Xr] * 3 + [Xp, Xs]); Y = np.concatenate([R["y"].values] * 3 + [pub["y"].values, syn["y"].values])
gbm = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.08).fit(X, Y)
lr = LogisticRegression(C=1.0, class_weight="balanced", max_iter=3000).fit(X, Y)
tf = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)
A = tf.fit_transform(R["text"].tolist())
tlr = LogisticRegression(C=4.0, class_weight="balanced", max_iter=3000).fit(A, R["y"].values)
joblib.dump({"gbm": gbm, "lr": lr, "tfidf": tf, "tlr": tlr, "threshold": 0.62, "cue_weight": 0.5}, os.path.join(V.ROOT, "models", os.environ.get("BEC_OUT", "bec_final.joblib")))
# precision of the hand rules (used for RED) on all real legit emails
y = R["y"].values.astype(bool); c = np.array([cue_score(t) for t in R["text"]])
print(json.dumps({"saved": True, "cue_red_caught": f"{int(((c>=0.5)&y).sum())}/{int(y.sum())}", "cue_red_false_alarms": f"{int(((c>=0.5)&~y).sum())}/{int((~y).sum())}"}))
