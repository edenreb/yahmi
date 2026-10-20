"""Invoice-fraud email model v2: trained on real phishing/safe emails PLUS synthetic invoice-fraud and
legitimate supplier emails, then tested only on REAL emails:
  (1) held-out 20% of the public phishing dataset,
  (2) held-out real legitimate emails about invoices, payments or bank details (false alarms),
  (3) real published BEC/invoice-fraud emails and real vendor notices collected from public sources.
"""
import json
import os
import re

import joblib
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import FeatureUnion, Pipeline

HERE = os.path.dirname(os.path.abspath(__file__))
df = pd.read_csv(os.path.join(HERE, "..", "data", "dl", "phishing_email.csv")).dropna(subset=["Email Text"])
df["text"] = df["Email Text"].astype(str).str.slice(0, 5000)
df = df[df["text"].str.strip().str.len() > 20].drop_duplicates("text")
df["y"] = (df["Email Type"] == "Phishing Email").astype(int)
PAY = re.compile(r"bank details|account details|new account|change of bank|update(?:d)? (?:our )?(?:bank|banking|account)|wire transfer|remittance|invoice|payment", re.I)
df["pay"] = df["text"].str.contains(PAY)
tr, te = train_test_split(df, test_size=0.2, random_state=42, stratify=df["y"])
syn = pd.DataFrame(json.load(open(os.path.join(HERE, "synthetic_bec_train.json"))))
train = pd.concat([tr[["text", "y"]], syn, syn], ignore_index=True)  # synthetic weighted x2

model = Pipeline([
    ("feats", FeatureUnion([
        ("w", TfidfVectorizer(ngram_range=(1, 3), min_df=2, max_features=300000, sublinear_tf=True)),
        ("c", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3, max_features=200000, sublinear_tf=True)),
    ])),
    ("clf", LogisticRegression(max_iter=3000, C=4, class_weight="balanced")),
])
model.fit(train["text"], train["y"])


def stats(y, p, thr):
    y, p = np.asarray(y), np.asarray(p)
    pred = p >= thr
    tp, fp = int((pred & (y == 1)).sum()), int((pred & (y == 0)).sum())
    pos, neg = int((y == 1).sum()), int((y == 0).sum())
    out = {"n": len(y), "fraud": pos, "legit": neg, "caught": f"{tp}/{pos}" if pos else None, "false_alarms": f"{fp}/{neg}" if neg else None}
    if pos and neg:
        out["roc_auc"] = round(roc_auc_score(y, p), 4)
    return out


res = {"threshold": 0.5, "train": {"real_emails": int(len(tr)), "synthetic_emails": int(len(syn))}}
p = model.predict_proba(te["text"])[:, 1]
res["heldout_dataset_all"] = stats(te["y"], p, 0.5)
m = te["pay"].values
res["heldout_dataset_payment_related"] = stats(te["y"][m], p[m], 0.5)
rw_path = os.path.join(HERE, "..", "data", "bec_realworld.json")
if os.path.exists(rw_path):
    rw = json.load(open(rw_path))
    texts = [(x.get("subject") or "") + "\n" + x["body"] for x in rw]
    y = [1 if x["label"] == "fraud" else 0 for x in rw]
    prw = model.predict_proba(texts)[:, 1]
    res["real_world_published"] = stats(y, prw, 0.5)
    res["real_world_items"] = [{"label": x["label"], "score": round(float(s), 3), "start": t[:60].replace("\n", " ")} for x, s, t in zip(rw, prw, texts)]
print(json.dumps({k: v for k, v in res.items() if k != "real_world_items"}, indent=1))
os.makedirs(os.path.join(HERE, "..", "models"), exist_ok=True)
joblib.dump(model, os.path.join(HERE, "..", "models", "bec.joblib"))
json.dump(res, open(os.path.join(HERE, "result_bec_v2.json"), "w"), indent=1)
