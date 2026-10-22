"""Coverage analysis (analysis, not an eval): how many labelled fraud emails carry
payment-account details, and how many of the ones the email model misses would the
per-business payment-history rule still flag on its own.

Why: the product's core claim is that every payment-diversion fraud must send money
to an account the business has never paid, or a different account from the usual one.
memory.py flags amber for a first payment to an account and red when a known
supplier's account changed. That check only fires when the material under check
contains an account (an invoice IBAN, or an account typed by the user).

This script reads local, git-ignored corpora, scores frauds with the live model,
tags account details heuristically, prints previews for manual adjudication and
writes aggregate counts only (no email text) next to the input files.

Usage: python eval/history_coverage.py [file.json ...]
"""
import json
import os
import re
import sys

import joblib
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)

from fastembed import TextEmbedding
from yahmi.cues import cue_hits
from yahmi.rules import iban_valid

AMBER = 0.62
IBAN_RX = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?:[ \-]?[A-Za-z0-9]){11,34}")
ACC_RX = re.compile(
    r"(?:account|a/c|acc\.?|acct|beneficiary|sort\s*code|routing(?:\s*number)?|iban)"
    r"[^.\n]{0,40}?((?:\d[\- ]?){7,20}\d)", re.I)
SWIFT_RX = re.compile(r"\b(?:SWIFT|BIC)\b[^.\n]{0,20}\b[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b")
NEW_WORDS = re.compile(
    r"\b(?:new|updated|changed|change of|recently changed|another|different|temporary|revised)\b"
    r"[^.\n]{0,40}\b(?:account|bank|details|beneficiary|iban|transfer)\b"
    r"|\b(?:account|bank\s+details|beneficiary|iban)\b[^.\n]{0,30}\b(?:has|have|was|is|been|will)\b"
    r"[^.\n]{0,20}\b(?:changed|updated|new|change)\b", re.I)
BANK_WORD = re.compile(r"\b(?:bank|swift|bic|sort\s*code|routing|aba|ifsc|iban|wire|transfer|remit|beneficiary)\b", re.I)


class Ensemble:
    def __init__(self, path):
        self.emb = TextEmbedding("BAAI/bge-small-en-v1.5", max_length=128)
        self.m = joblib.load(path)

    @staticmethod
    def _arabic_share(t):
        letters = [c for c in t if c.isalpha()]
        return sum("\u0600" <= c <= "\u06ff" for c in letters) / max(len(letters), 1)

    def predict(self, texts):
        E = np.array(list(self.emb.embed([t[:700] for t in texts])))
        C = np.array([[float(v) for v in cue_hits(t).values()] for t in texts]) * self.m["cue_weight"]
        X = np.hstack([E, C])
        p = (self.m["gbm"].predict_proba(X)[:, 1]
             + self.m["lr"].predict_proba(X)[:, 1]
             + self.m["tlr"].predict_proba(self.m["tfidf"].transform(texts))[:, 1]) / 3
        ar = [i for i, t in enumerate(texts) if self._arabic_share(t) > 0.3]
        if ar:
            mp = os.path.join(ROOT, "models", "bec_multi.joblib")
            multi = joblib.load(mp)
            memb = TextEmbedding(multi["emb_model"], max_length=128)
            sub = [texts[i] for i in ar]
            Em = np.array(list(memb.embed([t[:700] for t in sub])))
            Cm = np.array([[float(v) for v in cue_hits(t).values()] for t in sub]) * multi["cue_weight"]
            p[ar] = multi["lr"].predict_proba(np.hstack([Em, Cm]))[:, 1]
        return p


def context(body, start, n=70):
    a = max(0, start - n)
    return body[a:start + n].replace("\n", " ").replace("\r", " ")


def analyse(path, model):
    d = json.load(open(path, encoding="utf-8"))
    texts = [(x.get("subject") or "") + "\n" + (x.get("body") or "") for x in d]
    p = model.predict(texts) if texts else np.array([])
    rows = []
    for i, x in enumerate(d):
        if x.get("label") != "fraud":
            continue
        body = x.get("body") or ""
        text = texts[i]
        ibans = [m.group(0).replace(" ", "").replace("-", "") for m in IBAN_RX.finditer(body)]
        valid = [b for b in ibans if iban_valid(b)]
        accs = [re.sub(r"\D", "", m.group(1)) for m in ACC_RX.finditer(body)]
        swift = bool(SWIFT_RX.search(body))
        has_acc = bool(valid or accs or swift)
        newchg = bool(NEW_WORDS.search(text))
        rows.append({
            "i": i, "attack": x.get("attack_type") or "unknown",
            "score": round(float(p[i]), 3), "ai_miss": bool(p[i] < AMBER),
            "ibans": len(valid), "accs": len(accs), "swift": swift,
            "has_account": has_acc, "new_or_changed": newchg,
            "subject": (x.get("subject") or "")[:70],
            "ctx": context(body, min([m.start() for m in IBAN_RX.finditer(body)] + [m.start(1) for m in ACC_RX.finditer(body)] or [0])) if has_acc else "",
        })
    summary = {}
    for r in rows:
        a = r["attack"]
        s = summary.setdefault(a, {"n": 0, "with_account": 0, "new_or_changed": 0, "ai_miss": 0,
                                   "ai_miss_with_account": 0, "ai_miss_with_account_new_or_changed": 0})
        s["n"] += 1
        s["with_account"] += r["has_account"]
        s["new_or_changed"] += r["new_or_changed"]
        s["ai_miss"] += r["ai_miss"]
        if r["has_account"]:
            s["ai_miss_with_account"] += r["ai_miss"]
            if r["new_or_changed"]:
                s["ai_miss_with_account_new_or_changed"] += r["ai_miss"]
    out = {"file": os.path.basename(path), "n_fraud": len(rows),
           "totals": {k: sum(s[k] for s in summary.values()) for k in next(iter(summary.values()))},
           "by_attack": summary,
           "note": "aggregate counts only; per-record previews printed to the console for manual review"}
    print("=" * 100)
    print(os.path.basename(path), json.dumps(out["totals"]))
    for r in rows:
        if r["has_account"] or r["new_or_changed"]:
            print(f'{r["i"]:3d} {r["attack"]:26s} p={r["score"]:.2f} miss={int(r["ai_miss"])} '
                  f'acc={int(r["has_account"])} new={int(r["new_or_changed"])} '
                  f'ib={r["ibans"]} ac={r["accs"]} sw={int(r["swift"])} | {r["subject"]}')
            if r["ctx"]:
                print("      ctx:", r["ctx"][:150])
    return out


def main():
    files = sys.argv[1:] or [os.path.join(ROOT, "data", "bec_realworld.json"),
                             os.path.join(ROOT, "data", "bec_realworld_more.json"),
                             os.path.join(ROOT, "data", "bec_more2.json")]
    model = Ensemble(os.path.join(ROOT, "models", "bec_final.joblib"))
    results = [analyse(f, model) for f in files]
    dest = os.path.join(HERE, "result_history_coverage.json")
    json.dump(results, open(dest, "w"), indent=1)
    print("\nwrote", dest)


if __name__ == "__main__":
    main()
