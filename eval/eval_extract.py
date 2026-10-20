"""Field-level extraction accuracy. Usage: python3 eval_extract.py SET_DIR [pdf|jpg] [limit]"""
import json
import os
import re
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from yahmi.extract import extract  # noqa
from yahmi.rules import iban_valid  # noqa

D, kind = sys.argv[1], sys.argv[2]
limit = int(sys.argv[3]) if len(sys.argv) > 3 else 10**9
labels = json.load(open(os.path.join(D, "labels.json")))[:limit]
F = ["supplier_name", "supplier_trn", "iban", "invoice_number", "invoice_date", "subtotal", "vat", "total"]
ok = {f: 0 for f in F}
den = {f: 0 for f in F}  # labelled count per field (real datasets may lack some fields: label null = not scored)
silent_iban_err = flagged_iban = all_ok = 0
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
    return re.sub(r"\s", "", str(v)).upper()


for lab in labels:
    inv = extract(os.path.join(D, lab["file"].replace(".pdf", "." + kind)))
    good = True
    for f in F:
        if lab.get(f) is None:
            continue
        den[f] += 1
        if norm(f, getattr(inv, f)) == norm(f, lab[f]):
            ok[f] += 1
        else:
            good = False
            errors.append((lab["file"], f, getattr(inv, f), lab[f]))
    all_ok += good
    got = inv.iban
    if not lab.get("iban"):
        pass
    elif got and got != lab["iban"]:
        if iban_valid(got):
            silent_iban_err += 1
        else:
            flagged_iban += 1
    elif not got:
        flagged_iban += 1
    if not lab.get("iban") and got and iban_valid(got):
        silent_iban_err += 1  # invented an IBAN that isn't on the invoice

n = len(labels)
res = {"set": os.path.basename(D), "format": kind, "n": n, "field_accuracy": {f: round(ok[f] / den[f], 4) for f in F if den[f]}, "labelled": {f: den[f] for f in F},
       "all_fields_correct": round(all_ok / n, 4), "iban_wrong_but_flagged": flagged_iban, "iban_wrong_and_silent": silent_iban_err}
print(json.dumps(res, indent=1))
json.dump({"result": res, "errors": [list(map(str, e)) for e in errors[:200]]}, open(f"result_{os.path.basename(D)}_{kind}.json", "w"), indent=1)
