"""Cache the text extract() settles on for each invoice, so supplier-name rules can be iterated fast.
Usage: python3 sup_cache.py SET_DIR pdf|jpg OUT.json"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from yahmi.extract import extract  # noqa
D, kind, out = sys.argv[1:4]
rows = []
for lab in json.load(open(os.path.join(D, "labels.json"))):
    inv = extract(os.path.join(D, lab["file"].replace(".pdf", "." + kind)))
    rows.append(dict(file=lab["file"], template=lab.get("template"), label=lab["supplier_name"], text=inv.raw_text))
json.dump(rows, open(out, "w"))
print(out, len(rows))
