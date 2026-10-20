"""Score find_supplier on cached texts. Usage: python3 sup_eval.py CACHE.json [...] [-v]"""
import json, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from yahmi.extract import find_supplier  # noqa
if os.environ.get("SUP_MODULE"):  # score another copy of extract.py, e.g. a backup
    import importlib.util, types
    src = open(os.environ["SUP_MODULE"]).read().replace("from .rules", "from yahmi.rules")
    m = types.ModuleType("sup_alt"); exec(compile(src, "sup_alt", "exec"), m.__dict__); find_supplier = m.find_supplier
n = lambda v: re.sub(r"[^a-z0-9]", "", str(v).lower()) if v else None
for f in [a for a in sys.argv[1:] if a != "-v"]:
    rows = json.load(open(f)); bad = [r for r in rows if n(find_supplier(r["text"])) != n(r["label"])]
    print(f"{os.path.basename(f):28s} {1 - len(bad) / len(rows):.3f}")
    if "-v" in sys.argv:
        for r in bad[:15]:
            print("   ", r["file"], r["template"], repr(find_supplier(r["text"])), "!=", repr(r["label"]))
