"""Build eval/ext_sparrow from the public Sparrow invoice set (katanaml-org/invoices-donut-data-v1, MIT).

Usage: python3 build_ext_sparrow.py     (needs pyarrow: pip install pyarrow; the raw parquet files go in ext_sparrow/raw)
Writes sp_NNNN.jpg and labels.json. A label is null when the field is not printed in a form the reader should
return (US tax IDs are not TRNs). Split is fixed by a hash of the file name: ~70% dev, ~30% holdout. Holdout is run once.
supplier_name is the part of the seller string before the street address (the first token that starts with a digit).
"""
import glob
import hashlib
import io
import json
import os
import re
from decimal import Decimal

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "ext_sparrow")


def money(s):
    """'$1.234,56' / '$7,50' / '1,234.50' -> '1234.56' (None if not parseable)."""
    if not s:
        return None
    t = re.sub(r"[^\d.,]", "", s)
    if re.search(r"[.,]\d{2}$", t):
        t = re.sub(r"\D", "", t[:-3]) + "." + t[-2:]
    else:
        t = re.sub(r"\D", "", t)
    try:
        return str(Decimal(t).quantize(Decimal("0.01")))
    except Exception:
        return None


def iso_us(d):
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", d or "")
    return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else None


ADDR = {"USCGC", "USNS", "USS", "USNV", "Unit", "PSC", "FPO", "APO", "DPO", "Box", "Suite", "Apt.", "Apt"}


def seller_name(s):
    toks = (s or "").split()
    for i, t in enumerate(toks):
        if i and (t[0].isdigit() or t in ADDR):
            return " ".join(toks[:i]).rstrip(",")
    return (s or "").strip() or None


labels = []
n = 0
for f in sorted(glob.glob(os.path.join(OUT, "raw", "*.parquet"))):
    df = pd.read_parquet(f)
    for _, row in df.iterrows():
        gt = json.loads(row["ground_truth"])["gt_parse"]
        h, s = gt.get("header", {}), gt.get("summary", {})
        name = f"sp_{n:04d}"
        with open(os.path.join(OUT, name + ".jpg"), "wb") as fh:
            from PIL import Image
            Image.open(io.BytesIO(row["image"]["bytes"])).convert("RGB").save(fh, "JPEG", quality=92)
        split = "holdout" if int(hashlib.md5(name.encode()).hexdigest(), 16) % 10 < 3 else "dev"
        labels.append({
            "file": name + ".pdf", "split": split, "source": "katanaml-org/invoices-donut-data-v1",
            "supplier_name": seller_name(h.get("seller")), "supplier_trn": None, "iban": h.get("iban") or None, "iban_unannotated": not h.get("iban"),
            "invoice_number": h.get("invoice_no") or None, "invoice_date": iso_us(h.get("invoice_date")),
            "subtotal": money(s.get("total_net_worth")), "vat": money(s.get("total_vat")), "total": money(s.get("total_gross_worth")),
        })
        n += 1
json.dump(labels, open(os.path.join(OUT, "labels.json"), "w"), indent=1)
print(n, "invoices;", sum(l["split"] == "dev" for l in labels), "dev,", sum(l["split"] == "holdout" for l in labels), "holdout")
