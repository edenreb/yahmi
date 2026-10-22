"""Refresh the local copy of the public sanctions lists Yahmi screens supplier names against.

    python3 tools/update_sanctions.py            (needs: pip install xlrd)

Sources (both public, published by the issuing bodies; nothing is sent to them but the download request):
- UN Security Council Consolidated List, XML: https://scsanctions.un.org/resources/xml/en/consolidated.xml
  (linked from https://main.un.org/securitycouncil/content/un-sc-consolidated-list)
- UAE Local Terrorist List, Excel, from the Executive Office for Control and Non-Proliferation (EOCN):
  https://www.uaeiec.gov.ae/en-us/un-page . The file id below changes when the EOCN republishes the list: if the download fails,
  copy the current "Excel" link from that page into EOCN_URL.

Writes data/sanctions/raw/* (the downloads) and data/sanctions/entries.json (names only, what Yahmi loads). Run it again whenever
the lists change; the EOCN expects reporting entities to screen within 24 hours of an update.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data", "sanctions")
UN_URL = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"
EOCN_URL = "https://www.uaeiec.gov.ae/API/Upload/DownloadFile?FileID=0433bfdb-8a3d-44db-9015-90cbbf48f6f6"


def fetch(url, path, magic):
    """Download with curl (a plain client; the EOCN site rejects some scripted clients with 'Request Rejected'). If the download does not
    return the expected file type, an already-downloaded file in data/sanctions/raw is used instead, so a list saved by hand from the
    source page also works. Returns (sha256, size, how)."""
    tmp = path + ".part"
    ok = subprocess.run(["curl", "-sSL", "--max-time", "120", "-o", tmp, url], capture_output=True).returncode == 0
    if ok and os.path.exists(tmp) and open(tmp, "rb").read(len(magic)) == magic:
        os.replace(tmp, path)
        how = "downloaded"
    else:
        if os.path.exists(tmp):
            os.remove(tmp)
        if not (os.path.exists(path) and open(path, "rb").read(len(magic)) == magic):
            sys.exit(f"Could not download {url}. Save the file from the source page into {path} and run this again.")
        how = f"download failed; used the existing file saved on {datetime.fromtimestamp(os.path.getmtime(path)).date()}"
    data = open(path, "rb").read()
    return hashlib.sha256(data).hexdigest(), len(data), how


def un_entries(path):
    root = ET.parse(path).getroot()
    out = []
    for kind, tag in (("individual", "INDIVIDUAL"), ("entity", "ENTITY")):
        for e in root.iter(tag):
            if kind == "individual":
                names = [" ".join((e.findtext(k) or "").strip() for k in ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME")).strip()]
                alias_tag = "INDIVIDUAL_ALIAS"
            else:
                names = [(e.findtext("FIRST_NAME") or "").strip()]
                alias_tag = "ENTITY_ALIAS"
            for a in e.findall(alias_tag):
                if (a.findtext("QUALITY") or "").strip().lower() != "low":   # "low quality" aliases are too loose to match on
                    names.append((a.findtext("ALIAS_NAME") or "").strip())
            names = sorted({re.sub(r"\s+", " ", n) for n in names if n})
            if names:
                out.append({"list": "UN", "kind": kind, "ref": e.findtext("REFERENCE_NUMBER") or "", "names": names, "listed_on": e.findtext("LISTED_ON") or ""})
    return out, root.get("dateGenerated", "")


def uae_entries(path):
    """Sheets: individuals, organisations, entities. Sheets whose name says 'removed from the list' are skipped."""
    sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=str)
    cols = {"individual": (5, 6, 9), "organisation": (2, 3), "entity": (2, 3, 4)}   # columns holding names, by sheet kind
    out = []
    for name, df in sheets.items():
        if "رفع" in name:
            continue
        kind = "individual" if "الأفراد" in name else "organisation" if "التنظيمات" in name else "entity" if "الكيانات" in name else None
        if not kind:
            continue
        for _, row in df.iloc[3:].iterrows():
            names = {re.sub(r"\s+", " ", str(row.get(c, "")).strip()) for c in cols[kind] if c < len(row)}
            names = sorted(n for n in names if n and n not in ("-", "nan"))
            if names:
                out.append({"list": "UAE_LTL", "kind": "individual" if kind == "individual" else "entity", "ref": str(row.get(0, "")).strip(), "names": names, "listed_on": ""})
    return out


def main():
    os.makedirs(os.path.join(OUT, "raw"), exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    un_raw, uae_raw = os.path.join(OUT, "raw", "un_consolidated.xml"), os.path.join(OUT, "raw", "uae_local_terrorist_list.xls")
    h1, n1, how1 = fetch(UN_URL, un_raw, b"<?xml")
    h2, n2, how2 = fetch(EOCN_URL, uae_raw, b"\xd0\xcf\x11\xe0")
    un, generated = un_entries(un_raw)
    uae = uae_entries(uae_raw)
    meta = {"un": {"url": UN_URL, "generated": generated, "fetched_at": now, "sha256": h1, "bytes": n1, "how": how1, "entries": len(un)},
            "uae_ltl": {"url": EOCN_URL, "fetched_at": now, "sha256": h2, "bytes": n2, "how": how2, "entries": len(uae)}}
    with open(os.path.join(OUT, "entries.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "entries": un + uae}, f, ensure_ascii=False)
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
