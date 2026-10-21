"""Build eval/ext_fatura from FATURA (Dhiaf, Limam, Kessentini 2023; Zenodo record 10371464; CC BY 4.0).

Usage: python3 build_ext_fatura.py   (unzip FATURA2.zip into ext_fatura/raw first)
FATURA is a set of synthetic invoices (50 layouts, 10,000 images) filled with random data, with the printed text of
each field annotated. This takes a fixed sample of 12 images per layout (600) and writes fa_NNNN.jpg + labels.json.
A label is null when the annotation is missing or the printed value is ambiguous (day/month order of an all-numeric
date). Split is a hash of the file name: ~70% dev, ~30% holdout. Holdout is run once.
"""
import glob
import hashlib
import json
import os
import re
import shutil
from decimal import Decimal

from dateutil import parser as dparse

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "ext_fatura", "raw", "invoices_dataset_final")
OUT = os.path.join(HERE, "ext_fatura")


def last_amount(s):
    m = re.findall(r"\d[\d,]*\.\d{2}", s or "")
    return str(Decimal(m[-1].replace(",", ""))) if m else None


def date_iso(s):
    s = (s or "").split(":", 1)[-1] if ":" in (s or "") else (s or "")
    if re.fullmatch(r"\D*\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\D*", s):
        a, b = re.findall(r"\d+", s)[:2]
        if int(a) <= 12 and int(b) <= 12 and a != b:
            return None  # day/month order is ambiguous in the printed text
    try:
        return dparse.parse(s, fuzzy=True, dayfirst=True).date().isoformat()
    except Exception:
        return None


def inv_no(s):
    toks = [t for t in (s or "").replace(":", " ").split() if re.search(r"\d", t)]
    return toks[-1] if toks else None


by_tpl = {}
for p in sorted(glob.glob(os.path.join(RAW, "Annotations", "Original_Format", "*.json"))):
    m = re.match(r"(Template\d+)_Instance(\d+)", os.path.basename(p))
    by_tpl.setdefault(m.group(1), []).append((int(m.group(2)), p))

labels, n = [], 0
# interleave layouts (instance 0 of every layout, then instance 1, ...) so any first-N slice covers all layouts
order = [sorted(by_tpl[t])[k][1] for k in range(12) for t in sorted(by_tpl, key=lambda t: int(t[8:])) if len(by_tpl[t]) > k]
if True:
    for p in order:
        a = json.load(open(p))
        stem = os.path.basename(p)[:-5]
        src = os.path.join(RAW, "images", stem + ".jpg")
        if not os.path.exists(src):
            continue
        name = f"fa_{n:04d}"
        shutil.copy(src, os.path.join(OUT, name + ".jpg"))
        t = lambda k: (a.get(k) or {}).get("text") if isinstance(a.get(k), dict) else None
        labels.append({
            "file": name + ".pdf", "split": "holdout" if int(hashlib.md5(name.encode()).hexdigest(), 16) % 10 < 3 else "dev",
            "source": f"FATURA {stem}", "supplier_name": (t("SELLER_NAME") or "").strip() or None, "supplier_trn": None, "iban": None,
            "invoice_number": inv_no(t("NUMBER")), "invoice_date": date_iso(t("DATE")),
            "subtotal": last_amount(t("SUB_TOTAL")), "vat": last_amount(t("TAX")), "total": last_amount(t("TOTAL")),
        })
        n += 1
json.dump(labels, open(os.path.join(OUT, "labels.json"), "w"), indent=1)
print(n, "invoices;", sum(l["split"] == "dev" for l in labels), "dev,", sum(l["split"] == "holdout" for l in labels), "holdout")
