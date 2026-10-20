import os

from yahmi.extract import extract, norm_digits

HERE = os.path.dirname(__file__)
AR = os.path.join(HERE, "fixtures", "ar")


def test_eastern_digits_normalised():
    assert norm_digits("الإجمالي ٥٨٬٥٧٤٫٢٥") == "الإجمالي 58,574.25"
    assert norm_digits("TRN ۱۰۰۸") == "TRN 1008"


def test_bilingual_pdf_with_eastern_digits():
    import json
    labels = json.load(open(os.path.join(AR, "labels.json")))
    lab = next(l for l in labels if l["template"] == "ar_eastern")
    inv = extract(os.path.join(AR, lab["file"]))
    assert inv.iban == lab["iban"]
    assert inv.supplier_trn == lab["supplier_trn"]
    assert str(inv.total) == lab["total"]


def test_whatsapp_arabic_verdict():
    from yahmi.whatsapp import format_verdict
    r = {"verdict": "stop", "findings": [{"check": "history", "level": "red", "message": "Bank details changed."}]}
    out = format_verdict(r, "ar")
    assert out.startswith("🛑 توقف") and "تغيّرت بيانات الحساب" in out and "Bank details changed." in out
    assert format_verdict(r).startswith("🛑 STOP")
