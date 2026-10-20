"""Train and measure the fraud-email classifier.

Data: zefang-liu/phishing-email-dataset (Hugging Face, LGPL-3.0): 18,650 real emails labelled Phishing / Safe.
Held-out test: 20% stratified split never seen in training. Also reports the false-alarm rate on real,
legitimate emails that talk about invoices, payments or bank details (the cases that matter for Yahmi).
"""
import json
import os
import re
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_fscore_support, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import FeatureUnion, Pipeline

HERE = os.path.dirname(os.path.abspath(__file__))
df = pd.read_csv(os.path.join(HERE, "..", "data", "dl", "phishing_email.csv"))
df = df.dropna(subset=["Email Text"])
df["text"] = df["Email Text"].astype(str).str.slice(0, 5000)
df = df[df["text"].str.strip().str.len() > 20].drop_duplicates("text")
df["y"] = (df["Email Type"] == "Phishing Email").astype(int)
PAY = re.compile(r"bank details|account details|new account|change of bank|update(?:d)? (?:our )?(?:bank|banking|account)|wire transfer|remittance|invoice|payment", re.I)
df["pay"] = df["text"].str.contains(PAY)

tr, te = train_test_split(df, test_size=0.2, random_state=42, stratify=df["y"])
model = Pipeline([
    ("feats", FeatureUnion([
        ("w", TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=200000, sublinear_tf=True)),
        ("c", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3, max_features=200000, sublinear_tf=True)),
    ])),
    ("clf", LogisticRegression(max_iter=2000, C=4, class_weight="balanced")),
])
model.fit(tr["text"], tr["y"])
p = model.predict_proba(te["text"])[:, 1]


def report(mask, name, thr=0.5):
    y, pp = te["y"][mask].values, p[mask.values]
    pred = (pp >= thr).astype(int)
    pr, rc, f1, _ = precision_recall_fscore_support(y, pred, average="binary", zero_division=0)
    fp = int(((pred == 1) & (y == 0)).sum()); neg = int((y == 0).sum())
    out = {"subset": name, "n": int(len(y)), "fraud": int(y.sum()), "precision": round(pr, 4), "recall": round(rc, 4), "f1": round(f1, 4),
           "false_alarm_rate_on_legit": round(fp / neg, 4) if neg else None}
    if len(set(y)) > 1:
        out["roc_auc"] = round(roc_auc_score(y, pp), 4)
    return out


res = {"train_n": int(len(tr)), "test": [report(te["y"] >= 0, "all held-out emails"), report(te["pay"], "held-out emails about invoices, payments or bank details")]}
print(json.dumps(res, indent=1))
os.makedirs(os.path.join(HERE, "..", "models"), exist_ok=True)
joblib.dump(model, os.path.join(HERE, "..", "models", "bec.joblib"))
json.dump(res, open(os.path.join(HERE, "result_bec_heldout.json"), "w"), indent=1)
