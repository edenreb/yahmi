"""Yahmi web app. Run: uvicorn yahmi.app:app --port 8000"""
from __future__ import annotations

import os
import tempfile

import joblib
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .email_checks import check_email, domain_of, parse as parse_email
from .email_meta import DomainAge
from .extract import extract
from .memory import Memory, supplier_id
from .registry import FtaTrnClient, check_trn_registry
from .rules import check_invoice

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = FastAPI(title="Yahmi")
FTA = FtaTrnClient()  # official TRN-to-name check; reports "not connected" until the API credentials are set
DOMAIN_AGE = DomainAge()  # asks the domain registry how old the sender's domain is; YAHMI_DOMAIN_AGE=0 turns it off
MEM = Memory(os.environ.get("YAHMI_DB", os.path.join(ROOT, "data", "yahmi.db")))
BEC_PATH = os.path.join(ROOT, "models", "bec_final.joblib")
BEC = None
if os.path.exists(BEC_PATH):
    from fastembed import TextEmbedding

    MULTI_PATH = os.path.join(os.path.dirname(BEC_PATH), "bec_multi.joblib")

    def _arabic_share(t):
        letters = [c for c in t if c.isalpha()]
        return sum("\u0600" <= c <= "\u06ff" for c in letters) / max(len(letters), 1)

    class _Ensemble:
        """Mean of embedding-GBM, embedding-LR and TF-IDF-LR (validated AUC 0.927 on 348 real emails)."""
        def __init__(self):
            self.emb = TextEmbedding("BAAI/bge-small-en-v1.5", max_length=128)
            self.m = joblib.load(BEC_PATH)
            self.multi = None

        def predict_proba(self, texts):
            import numpy as np
            from .cues import cue_hits
            E = np.array(list(self.emb.embed([t[:700] for t in texts])))
            C = np.array([[float(v) for v in cue_hits(t).values()] for t in texts]) * self.m["cue_weight"]
            X = np.hstack([E, C])
            p = (self.m["gbm"].predict_proba(X)[:, 1] + self.m["lr"].predict_proba(X)[:, 1] + self.m["tlr"].predict_proba(self.m["tfidf"].transform(texts))[:, 1]) / 3
            # Mostly-Arabic messages: the English model over-flags them, so use the multilingual model instead.
            ar = [i for i, t in enumerate(texts) if _arabic_share(t) > 0.3]
            if ar and os.path.exists(MULTI_PATH):
                if self.multi is None:
                    self.multi = joblib.load(MULTI_PATH)
                    self.memb = TextEmbedding(self.multi["emb_model"], max_length=128)
                sub = [texts[i] for i in ar]
                Em = np.array(list(self.memb.embed([t[:700] for t in sub])))
                Cm = np.array([[float(v) for v in cue_hits(t).values()] for t in sub]) * self.multi["cue_weight"]
                p[ar] = self.multi["lr"].predict_proba(np.hstack([Em, Cm]))[:, 1]
            return np.column_stack([1 - p, p])

    BEC = _Ensemble()
ORDER = {"red": 0, "amber": 1, "green": 2, "info": 3}


def _save(upload: UploadFile) -> str:
    suffix = os.path.splitext(upload.filename or "")[1].lower() or ".pdf"
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(upload.file.read())
    return path


def verdict(findings):
    levels = {f.level for f in findings}
    if "red" in levels:
        return "stop"
    if "amber" in levels:
        return "check"
    return "ok"


def run_check(path: str, email_text: str = "", business: str = "default") -> dict:
    """Core check used by the web app and WhatsApp."""
    inv = extract(path)
    findings = check_invoice(inv)
    findings += check_trn_registry(inv.supplier_name, inv.supplier_trn, FTA)
    if inv.iban and not inv.extra.get("iban_confident"):
        findings.insert(0, _f("iban_read", "amber", "We could not read the IBAN with certainty. Please type it in to confirm.", "Yahmi reader"))
    em = parse_email(email_text) if email_text.strip() else None
    dom = domain_of(em["from"]) if em else None
    sup = supplier_id(inv.supplier_trn, inv.supplier_name)
    findings += MEM.check(business, sup, inv.iban, dom)
    if em:
        score = float(BEC.predict_proba([(em["subject"] or "") + "\n" + em["body"]])[0, 1]) if BEC else None
        known = MEM.known_domains(business)
        findings += check_email(em, known, score, supplier_name=inv.supplier_name, domain_age=DOMAIN_AGE)
    findings.sort(key=lambda f: ORDER.get(f.level, 9))
    return {
        "verdict": verdict(findings),
        "invoice": {k: (str(v) if v is not None else None) for k, v in inv.__dict__.items() if k not in ("raw_text", "extra")},
        "read_method": inv.extra.get("method"),
        "findings": [f.to_dict() for f in findings],
    }


def add_history(path: str, business: str = "default", email_domain: str | None = None) -> str | None:
    """Record an already-paid invoice in this business's history. Returns a short label or None."""
    inv = extract(path)
    sup = supplier_id(inv.supplier_trn, inv.supplier_name)
    if sup and inv.iban and inv.extra.get("iban_confident"):
        MEM.record(business, sup, inv.iban, email_domain or None)
        return f"{inv.supplier_name or 'supplier'} (account ending {inv.iban[-4:]})"
    return None


@app.post("/api/check")
async def check(invoice: UploadFile = File(...), email_text: str = Form(""), business: str = Form("default")):
    path = _save(invoice)
    try:
        return JSONResponse(run_check(path, email_text, business))
    finally:
        os.remove(path)


@app.post("/api/history")
async def history(files: list[UploadFile] = File(...), business: str = Form("default"), email_domain: str = Form("")):
    """Day-one onboarding: read past paid invoices to build this business's supplier history."""
    added = []
    for up in files:
        path = _save(up)
        try:
            a = add_history(path, business, email_domain or None)
        finally:
            os.remove(path)
        if a:
            added.append({"supplier": a})
    return {"added": added}


def _f(check, level, message, source):
    from .rules import Finding
    return Finding(check, level, message, source)


from .whatsapp import router as wa_router  # noqa: E402
app.include_router(wa_router)


app.mount("/assets", StaticFiles(directory=os.path.join(ROOT, "web", "assets")), name="assets")


@app.get("/landing")
def landing():
    return FileResponse(os.path.join(ROOT, "web", "landing.html"))


@app.get("/")
def index():
    return FileResponse(os.path.join(ROOT, "web", "index.html"))
