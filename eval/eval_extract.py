"""Field-level extraction accuracy. Usage: python3 eval_extract.py SET_DIR pdf|jpg [limit] [holdout]
Scores the dev split by default (labels without a split count as dev); pass "holdout" only for the final run."""
import json
import os
import re
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from yahmi.extract import extract, parse_date  # noqa
from yahmi.rules import iban_valid  # noqa

D, kind = sys.argv[1], sys.argv[2]
HOLDOUT = "holdout" in sys.argv[3:]  # holdout split: run once at the end and log it in TODO.md
limit = next((int(a) for a in sys.argv[3:] if a.isdigit()), 10**9)
split = "holdout" if HOLDOUT else "dev"
labels = [l for l in json.load(open(os.path.join(D, "labels.json"))) if l.get("split", "dev") == split][:limit]
F = ["supplier_name", "supplier_trn", "iban", "invoice_number", "invoice_date", "subtotal", "vat", "total"]
ok = {f: 0 for f in F}
den = {f: 0 for f in F}  # labelled count per field (real datasets may lack some fields: label null = not scored)
silent_iban_err = flagged_iban = all_ok = iban_label_bad = 0
silent_cases = []
errors = []


def norm(f, v):
    if v is None:
        return None
    if f in ("subtotal", "vat", "total"):
        return str(Decimal(str(v)).quantize(Decimal("0.01")))
    if f == "supplier_name":
        return re.sub(r"[^a-z0-9]", "", str(v).lower())
    if f == "invoice_number":
        return re.sub(r"^NO\.?", "", re.sub(r"\s", "", str(v)).upper())
    if f == "invoice_date":  # compare parsed dates (day-first), so 05-Mar-26 equals 05/03/2026
        d = parse_date(str(v))
        return d.isoformat() if d else re.sub(r"\s", "", str(v)).upper()
    return re.sub(r"\s", "", str(v)).upper()


for lab in labels:
    inv = extract(os.path.join(D, lab["file"].replace(".pdf", "." + kind)))
    good = True
    for f in F:
        if lab.get(f) is None:
            continue
        if f == "iban" and not iban_valid(lab[f]):
            iban_label_bad += 1  # the dataset's own label fails the checksum (annotation noise): not scored
            continue
        den[f] += 1
        if norm(f, getattr(inv, f)) == norm(f, lab[f]):
            ok[f] += 1
        else:
            good = False
            errors.append((lab["file"], f, getattr(inv, f), lab[f]))
    all_ok += good
    got = inv.iban
    if not lab.get("iban") or not iban_valid(lab["iban"]):
        pass
    elif got and got != lab["iban"]:
        if iban_valid(got):
            silent_iban_err += 1
            silent_cases.append((lab["file"], got, lab["iban"]))
        else:
            flagged_iban += 1
    elif not got:
        flagged_iban += 1
    if not lab.get("iban") and not lab.get("iban_unannotated") and got and iban_valid(got):
        silent_iban_err += 1  # invented an IBAN that isn't on the invoice

n = len(labels)
res = {"set": os.path.basename(D), "format": kind, "n": n, "field_accuracy": {f: round(ok[f] / den[f], 4) for f in F if den[f]}, "labelled": {f: den[f] for f in F},
       "all_fields_correct": round(all_ok / n, 4), "iban_labels_failing_checksum_not_scored": iban_label_bad, "iban_wrong_but_flagged": flagged_iban, "iban_wrong_and_silent": silent_iban_err}
print(json.dumps(res, indent=1))
json.dump({"result": res, "silent_iban_cases": silent_cases, "errors": [list(map(str, e)) for e in errors[:200]]}, open(f"result_{os.path.basename(D)}_{kind}{'_holdout' if HOLDOUT else ''}.json", "w"), indent=1)
