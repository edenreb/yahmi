"""Deterministic checks for a UAE supplier invoice. Every check returns a finding with a level and a source.

Levels: "red" = stop and verify, "amber" = check before paying, "green" = passed, "info" = context.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from decimal import Decimal, ROUND_HALF_UP

HERE = os.path.dirname(os.path.abspath(__file__))
BANKS = json.load(open(os.path.join(HERE, "..", "data", "uae_banks.json"), encoding="utf-8"))
VAT_RATE = Decimal("0.05")


@dataclass
class Finding:
    check: str
    level: str
    message: str
    source: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class Invoice:
    supplier_name: str | None = None
    supplier_trn: str | None = None
    customer_trn: str | None = None
    iban: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    subtotal: Decimal | None = None
    vat: Decimal | None = None
    total: Decimal | None = None
    is_tax_invoice_titled: bool = False
    raw_text: str = ""
    extra: dict = field(default_factory=dict)


def normalise_iban(s: str | None) -> str | None:
    if not s:
        return None
    s = re.sub(r"[\s\-]", "", s).upper()
    return s or None


def iban_valid(iban: str) -> bool:
    """ISO 13616 mod-97 check."""
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{1,30}", iban):
        return False
    r = iban[4:] + iban[:4]
    digits = "".join(str(int(ch, 36)) for ch in r)
    return int(digits) % 97 == 1


def iban_bank(iban: str) -> dict | None:
    if not iban.startswith("AE") or len(iban) != 23:
        return None
    code = iban[4:7]
    b = BANKS["banks"].get(code)
    return dict(b, code=code) if b else {"code": code, "name": None}


def check_iban(iban: str | None) -> list[Finding]:
    src_iban = "ISO 13616 IBAN checksum (mod 97)"
    src_bank = "UAE IBAN bank-identifier list (CBUAE)"
    iban = normalise_iban(iban)
    if not iban:
        return [Finding("iban", "amber", "No IBAN found on the invoice. Confirm the payment account with the supplier by phone.", "")]
    if not iban.startswith("AE"):
        return [Finding("iban", "amber", f"The account is outside the UAE ({iban[:2]}). A UAE supplier asking to be paid abroad is a common fraud pattern.", src_iban)]
    if len(iban) != 23:
        return [Finding("iban", "red", f"A UAE IBAN has 23 characters; this one has {len(iban)}.", src_iban)]
    if not iban_valid(iban):
        return [Finding("iban", "red", "The IBAN fails its checksum, so it contains a typo or was made up.", src_iban)]
    out = [Finding("iban", "green", "IBAN checksum is valid.", src_iban)]
    b = iban_bank(iban)
    if not b or not b.get("name"):
        out.append(Finding("bank", "amber", f"Bank code {iban[4:7]} is not in the UAE bank-identifier list. Check the CBUAE register before paying.", src_bank))
    else:
        kind = b.get("type", "bank")
        msg = f"Account is held at {b['name']} (bank code {b['code']})."
        if b.get("status") == "legacy":
            out.append(Finding("bank", "amber", msg + f" This code belongs to a bank that no longer operates under it: {b['note']}.", src_bank))
        elif kind == "exchange house":
            out.append(Finding("bank", "amber", msg + " This is an exchange house, not a bank. Suppliers rarely invoice into exchange-house accounts.", src_bank))
        else:
            out.append(Finding("bank", "green", msg, src_bank))
    return out


def check_trn(trn: str | None, label: str = "supplier") -> list[Finding]:
    src = "FTA: a Tax Registration Number is 15 digits"
    if not trn:
        level = "amber" if label == "supplier" else "info"
        return [Finding(f"{label}_trn", level, f"No {label} TRN found. A UAE tax invoice must show the supplier's TRN.", "VAT Executive Regulation, Art. 59")]
    t = re.sub(r"\D", "", trn)
    if len(t) != 15:
        return [Finding(f"{label}_trn", "red", f"The {label} TRN has {len(t)} digits; a UAE TRN has 15.", src)]
    if not t.startswith("1"):
        return [Finding(f"{label}_trn", "amber", f"The {label} TRN does not start with 1, which UAE TRNs normally do.", src)]
    return [Finding(f"{label}_trn", "green", f"{label.capitalize()} TRN has the correct format. Verify that it belongs to {'this company' if label == 'supplier' else 'you'} on the FTA TRN check.", src)]


def q2(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def check_vat(inv: Invoice) -> list[Finding]:
    src = "UAE VAT at 5% (Federal Decree-Law No. 8 of 2017)"
    s, v, t = inv.subtotal, inv.vat, inv.total
    if s is None or v is None or t is None:
        return [Finding("vat", "info", "Could not read subtotal, VAT and total, so the VAT arithmetic was not checked.", src)]
    out = []
    if abs(q2(s * VAT_RATE) - v) > Decimal("0.05"):
        out.append(Finding("vat", "amber", f"VAT should be AED {q2(s * VAT_RATE):,} (5% of {s:,}) but the invoice shows AED {v:,}.", src))
    if abs(s + v - t) > Decimal("0.05"):
        out.append(Finding("total", "red", f"Subtotal plus VAT is AED {q2(s + v):,} but the invoice asks for AED {t:,}.", src))
    if not out:
        out.append(Finding("vat", "green", "VAT is 5% and the total adds up.", src))
    return out


def check_fields(inv: Invoice) -> list[Finding]:
    src = "VAT Executive Regulation (Cabinet Decision 52/2017), Art. 59"
    missing = []
    if not inv.is_tax_invoice_titled:
        missing.append('the words "Tax Invoice"')
    if not inv.invoice_number:
        missing.append("an invoice number")
    if not inv.invoice_date:
        missing.append("a date of issue")
    if not inv.supplier_name:
        missing.append("the supplier's name")
    if missing:
        return [Finding("fields", "amber", "This is not a complete UAE tax invoice. It is missing " + ", ".join(missing) + ".", src)]
    return [Finding("fields", "green", "Has the main fields a UAE tax invoice needs.", src)]


def check_invoice(inv: Invoice) -> list[Finding]:
    return check_iban(inv.iban) + check_trn(inv.supplier_trn, "supplier") + check_vat(inv) + check_fields(inv)
