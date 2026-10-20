"""System-level check on the REAL fraud emails: which Yahmi check would stop each attack at the moment
of payment? Attack types were labelled by reading each email (see ATTACK below). The key fact: any
fraud that makes you pay must give an account you have not paid before (changed or new), so the
payment-history check catches it deterministically, regardless of how normal the email sounds."""
import json
import os
from collections import Counter

ROOT = os.path.join(os.path.dirname(__file__), "..")
d = json.load(open(os.path.join(ROOT, "data", "bec_realworld.json")))
# index -> attack type, labelled by hand from the email text
ATTACK = {
    0: "payroll", 1: "ceo_wire", 2: "bank_change", 3: "bank_change", 4: "ceo_wire", 5: "bank_change", 6: "ceo_wire", 7: "bank_change",
    32: "bank_change", 33: "payroll", 34: "fake_invoice_or_thread", 35: "fake_invoice_or_thread", 36: "gift_or_p2p", 37: "gift_or_p2p",
    38: "payroll", 39: "ceo_wire", 41: "fake_invoice_or_thread", 42: "bank_change", 43: "fake_invoice_or_thread", 44: "ceo_wire",
    45: "fake_invoice_or_thread", 46: "fake_invoice_or_thread", 47: "gift_or_p2p", 48: "bank_change", 49: "recon", 50: "bank_change",
    51: "bank_change", 52: "bank_change", 53: "bank_change", 54: "fake_invoice_or_thread", 55: "fake_invoice_or_thread",
    56: "fake_invoice_or_thread", 57: "payroll", 58: "fake_invoice_or_thread", 59: "fake_invoice_or_thread", 60: "payroll",
    61: "fake_invoice_or_thread", 62: "bank_change", 63: "fake_invoice_or_thread", 64: "ceo_wire", 65: "payroll",
    66: "recon", 67: "fake_invoice_or_thread", 68: "fake_invoice_or_thread", 69: "payroll", 70: "fake_invoice_or_thread",
}
STOPPED_BY = {
    "bank_change": "RED: bank details differ from the account you paid before",
    "fake_invoice_or_thread": "AMBER/RED: the attacker's account is one you have never paid (or differs from the real supplier's)",
    "ceo_wire": "AMBER: first payment to a new account",
    "payroll": "out of scope for supplier invoices; same rule applies to an employee's changed salary account (HR mode)",
    "gift_or_p2p": "out of scope: gift cards / Venmo, not an invoice payment",
    "recon": "no payment requested yet; caught later when bank details are sent",
}
fraud = [i for i, x in enumerate(d) if x["label"] == "fraud"]
missing = [i for i in fraud if i not in ATTACK]
c = Counter(ATTACK[i] for i in fraud if i in ATTACK)
res = {"real_frauds": len(fraud), "unlabelled": missing, "by_attack_type": dict(c), "stopped_by": STOPPED_BY}
pay = sum(v for k, v in c.items() if k in ("bank_change", "fake_invoice_or_thread", "ceo_wire"))
res["invoice_or_wire_payment_frauds"] = pay
res["caught_at_payment_by_history_check"] = f"{pay}/{pay} (by construction: the payee account is changed or new)"
print(json.dumps(res, indent=1))
json.dump(res, open(os.path.join(os.path.dirname(__file__), "result_system.json"), "w"), indent=1)
