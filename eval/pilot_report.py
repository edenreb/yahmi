"""Measure Yahmi on a folder of real pilot invoices. Nothing leaves the machine and nothing is stored in the repo.

Usage:  python3 eval/pilot_report.py PILOT_FOLDER [--labels labels.csv] [--out reports/name.json]

PILOT_FOLDER holds the invoices (pdf, jpg, png), directly or in one sub-folder per business. Invoices are replayed in date
order per business against a throw-away history, each one counted as paid afterwards (the invoices are assumed genuine), so the
numbers answer: how often would Yahmi have raised a warning on a genuine invoice, and why?

Reports: verdicts and warnings per 100 invoices by cause, how many "first payment" ambers are unavoidable (one per new account),
reader confidence, language mix, and, with a labels CSV typed by a human (columns in labels_template.csv), per-field accuracy.
Console output is masked (no names, IBANs or TRNs); the JSON report keeps file names only. Keep the folder outside the repo.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
EXTS = (".pdf", ".jpg", ".jpeg", ".png")
FIELDS = ["supplier_name", "supplier_trn", "iban", "invoice_number", "invoice_date", "subtotal", "vat", "total"]


def _date(s):
    m = re.search(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", s or "")
    if m:
        d, mo, y = map(int, m.groups())
        return (y, mo, d) if 1 <= mo <= 12 else None
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s or "")
    return tuple(map(int, m.groups())) if m else None


def _norm(field, v):
    v = "" if v is None else str(v).strip()
    if not v:
        return None
    if field in ("subtotal", "vat", "total"):
        try:
            return str(Decimal(re.sub(r"[^\d.\-]", "", v.replace(",", ""))).quantize(Decimal("0.01")))
        except InvalidOperation:
            return v
    if field == "invoice_date":
        return _date(v) or re.sub(r"\s", "", v).upper()
    if field == "supplier_name":
        return re.sub(r"[^\w]", "", v.lower())
    return re.sub(r"[\s\-]", "", v).upper() if field in ("iban", "supplier_trn") else re.sub(r"\s", "", v).upper()


def _mask(v):
    v = "" if v is None else str(v)
    return "-" if not v else (v if len(v) <= 4 else f"{v[:2]}…{v[-2:]}({len(v)})")


def _arabic_share(text):
    letters = re.findall(r"[A-Za-z؀-ۿ]", text or "")
    return len(re.findall(r"[؀-ۿ]", text or "")) / len(letters) if letters else 0.0


def _cause(f):
    """Why a warning was raised, in terms a pilot review cares about."""
    c, lvl, msg = f["check"], f["level"], f["message"]
    if c == "history":
        if msg.startswith("First payment"):
            return "first_payment_new_account"
        if msg.startswith("Bank details changed"):
            return "bank_details_changed"
        return "history_other"
    if c in ("iban_read", "iban", "bank"):
        return "iban_or_bank"
    if c in ("vat", "total"):
        return "vat_or_total"
    if c in ("supplier_trn", "customer_trn"):
        return "trn"
    if c == "fields":
        return "missing_fields"
    if c in ("history_domain", "network", "reply_to", "bec", "lookalike", "freemail"):
        return c
    return c


def run(folder, labels_path=None):
    from yahmi import app as A
    from yahmi.memory import Memory, supplier_id

    old_key = os.environ.get("YAHMI_KEY")
    os.environ["YAHMI_KEY"] = "pilot-report-throwaway-key"
    tmp = tempfile.mkdtemp()
    saved = (A.MEM, getattr(A, "FTA", None), A.extract)
    A.MEM = Memory(os.path.join(tmp, "replay.db"))
    if saved[1] is not None:
        from yahmi.registry import FtaTrnClient
        A.FTA = FtaTrnClient(env={})   # the official check is not part of this measurement
    cache = {}
    orig = A.extract
    A.extract = lambda p: cache.setdefault(p, orig(p))
    try:
        files = []
        for dp, _, fs in os.walk(folder):
            for f in fs:
                if f.lower().endswith(EXTS) and not f.startswith("."):
                    full = os.path.join(dp, f)
                    rel = os.path.relpath(full, folder)
                    files.append((rel.split(os.sep)[0] if os.sep in rel else os.path.basename(os.path.abspath(folder)), rel, full))
        by_biz = defaultdict(list)
        for biz, rel, full in sorted(files):
            by_biz[biz].append((rel, full))
        labels = {}
        if labels_path:
            with open(labels_path, newline="", encoding="utf-8") as fh:
                labels = {r["file"]: r for r in csv.DictReader(fh)}
        rows, accounts = [], set()
        for biz, items in by_biz.items():
            dated = sorted(items, key=lambda it: (_date(A.extract(it[1]).invoice_date) or (9999, 0, 0), it[0]))
            for rel, full in dated:
                inv = A.extract(full)
                res = A.run_check(full, "", biz)
                acc = (biz, inv.iban) if inv.iban else None
                A.add_history(full, biz)
                fnd = res["findings"]
                share = _arabic_share(inv.raw_text)
                rows.append({
                    "file": rel, "business": biz, "verdict": res["verdict"], "method": inv.extra.get("method"),
                    "iban_confident": bool(inv.extra.get("iban_confident")), "iban_found": bool(inv.iban),
                    "amounts_confident": bool(inv.extra.get("amounts_confident")),
                    "has_trn": bool(inv.supplier_trn), "has_date": bool(inv.invoice_date), "has_number": bool(inv.invoice_number),
                    "has_supplier": bool(inv.supplier_name), "language": "ar" if share > 0.3 else ("bilingual" if share >= 0.05 else "en"),
                    "warnings": sorted({(_cause(f), f["level"]) for f in fnd if f["level"] in ("amber", "red")}),
                    "new_account": bool(acc and acc not in accounts),
                    "read": {k: (str(getattr(inv, k)) if getattr(inv, k) is not None else None) for k in FIELDS},
                })
                if acc:
                    accounts.add(acc)
        n = len(rows)
        per = lambda x: round(100 * x / n, 1) if n else 0.0
        causes = Counter()
        for r in rows:
            for cause, lvl in r["warnings"]:
                causes[f"{cause}:{lvl}"] += 1
        only_first = sum(1 for r in rows if r["verdict"] != "ok" and all(c == "first_payment_new_account" for c, _ in r["warnings"]))
        rep = {
            "invoices": n, "businesses": {b: len(v) for b, v in by_biz.items()},
            "verdicts": {k: Counter(r["verdict"] for r in rows).get(k, 0) for k in ("stop", "check", "ok")},
            "per_100": {k: per(v) for k, v in sorted(causes.items())},
            "new_accounts": sum(r["new_account"] for r in rows), "new_accounts_per_100": per(sum(r["new_account"] for r in rows)),
            "flagged_only_by_first_payment": only_first,
            "flagged_per_100": per(sum(r["verdict"] != "ok" for r in rows)),
            "flagged_per_100_excluding_first_payment": per(sum(1 for r in rows if r["verdict"] != "ok") - only_first),
            "reader": {k: per(sum(r[k] for r in rows)) for k in ("iban_confident", "amounts_confident", "has_trn", "has_date", "has_number", "has_supplier")},
            "method": dict(Counter(r["method"] for r in rows)), "language": dict(Counter(r["language"] for r in rows)),
        }
        if labels:
            ok, den, errs = Counter(), Counter(), []
            for r in rows:
                lab = labels.get(os.path.basename(r["file"])) or labels.get(r["file"])
                if not lab:
                    continue
                for f in FIELDS:
                    want = _norm(f, lab.get(f))
                    if want is None:
                        continue
                    den[f] += 1
                    got = _norm(f, r["read"][f])
                    if got == want:
                        ok[f] += 1
                    else:
                        errs.append({"file": r["file"], "field": f, "read": _mask(r["read"][f]), "label": _mask(lab.get(f))})
            rep["field_accuracy"] = {f: {"correct": ok[f], "labelled": den[f], "rate": round(ok[f] / den[f], 3)} for f in FIELDS if den[f]}
            rep["field_errors_masked"] = errs[:200]
        rep["rows"] = [{k: v for k, v in r.items() if k != "read"} for r in rows]
        return rep
    finally:
        A.MEM, A.extract = saved[0], saved[2]
        if saved[1] is not None:
            A.FTA = saved[1]
        if old_key is None:
            os.environ.pop("YAHMI_KEY", None)
        else:
            os.environ["YAHMI_KEY"] = old_key


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--labels")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    rep = run(a.folder, a.labels)
    n = rep["invoices"]
    print(f"{n} invoices {rep['businesses']}  languages {rep['language']}  read by {rep['method']}")
    print("verdicts", rep["verdicts"], "| flagged per 100:", rep["flagged_per_100"], "| excluding first-payment-only:", rep["flagged_per_100_excluding_first_payment"])
    print(f"new accounts: {rep['new_accounts']} ({rep['new_accounts_per_100']} per 100: the first-payment ambers that cannot be avoided)")
    print("warnings per 100 invoices:", json.dumps(rep["per_100"]))
    print("reader (% of invoices):", json.dumps(rep["reader"]))
    for f, v in rep.get("field_accuracy", {}).items():
        print(f"  {f:15s} {v['correct']}/{v['labelled']}  {v['rate']:.0%}")
    out = a.out or os.path.join(os.path.abspath(a.folder), "..", "reports", os.path.basename(os.path.abspath(a.folder)) + ".json")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    json.dump(rep, open(out, "w"), indent=1)
    print("report written to", os.path.abspath(out))
    return rep


if __name__ == "__main__":
    main()
