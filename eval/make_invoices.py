"""Generate a labelled set of synthetic UAE tax invoices for measuring extraction accuracy.

Usage: python3 make_invoices.py OUT_DIR N SEED TEMPLATES
  TEMPLATES: comma-separated template ids (0-5). Hold some out to test layouts the parser never saw.
Each invoice is saved as a digital PDF (text layer) and a degraded "phone photo" JPEG (no text layer),
with ground truth in labels.json. Company names are invented.
"""
import json
import os
import random
import sys
from decimal import Decimal, ROUND_HALF_UP

from PIL import Image, ImageFilter
import fitz  # PyMuPDF
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT, N, SEED = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
TEMPLATES = [int(x) for x in sys.argv[4].split(",")]
rnd = random.Random(SEED)
os.makedirs(OUT, exist_ok=True)

BANK_CODES = ["003", "023", "024", "026", "033", "034", "035", "040", "041", "044", "050", "057"]
WORDS1 = ["Al Noor", "Golden Sands", "Desert Rose", "Blue Creek", "Falcon", "Marina Star", "Oasis", "Palm Line", "Crescent", "Gulf Bridge", "Sahara", "Pearl Coast", "Nakheel View", "Silver Dune", "Jumeira Park", "Emirates Line"]
WORDS2 = ["Trading", "General Contracting", "Technical Services", "Building Materials", "Logistics", "Facilities Management", "Electromechanical", "Catering Supplies", "IT Solutions", "Printing Press", "Interiors", "Auto Spare Parts"]
SUFFIX = ["LLC", "L.L.C", "FZE", "FZ-LLC", "Est.", "Co. LLC"]
ITEMS = ["Cement bags 50kg", "Cleaning services - monthly", "A4 paper cartons", "AC maintenance visit", "Steel rebar 12mm (ton)", "Delivery charges", "Laptop repair", "Office chairs", "Paint 18L drums", "Plumbing works", "Network cabling", "Security services"]
CITIES = ["Al Quoz, Dubai", "Mussafah, Abu Dhabi", "Industrial Area 4, Sharjah", "Al Jurf, Ajman", "Deira, Dubai", "Ras Al Khor, Dubai", "JLT, Dubai"]


def iban_check(bban_country="AE", bban=""):
    s = bban + "".join(str(ord(c) - 55) for c in bban_country) + "00"
    return f"{98 - int(s) % 97:02d}"


def make_iban():
    bban = rnd.choice(BANK_CODES) + "".join(rnd.choice("0123456789") for _ in range(16))
    return "AE" + iban_check("AE", bban) + bban


def fmt_iban(iban, style):
    if style == 0:
        return iban
    if style == 1:
        return " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))
    return iban[:4] + " " + iban[4:7] + " " + iban[7:]


def trn():
    return "100" + "".join(rnd.choice("0123456789") for _ in range(12))


def money(x):
    return f"{x:,.2f}"


def q2(x):
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def one(i):
    t = rnd.choice(TEMPLATES)
    name = f"{rnd.choice(WORDS1)} {rnd.choice(WORDS2)} {rnd.choice(SUFFIX)}"
    cust = f"{rnd.choice(WORDS1)} {rnd.choice(WORDS2)} {rnd.choice(SUFFIX)}"
    s_trn, c_trn, iban = trn(), trn(), make_iban()
    inv_no = rnd.choice(["INV-", "TI-", "", "No. ", "INV/2026/"]) + str(rnd.randint(1000, 99999))
    d = f"{rnd.randint(1, 28):02d}/{rnd.randint(1, 12):02d}/2026"
    lines = []
    for _ in range(rnd.randint(1, 5)):
        qty = rnd.randint(1, 40)
        unit = Decimal(rnd.randint(500, 250000)) / 100
        lines.append((rnd.choice(ITEMS), qty, unit, q2(unit * qty)))
    sub = sum(l[3] for l in lines)
    vat = q2(sub * Decimal("0.05"))
    tot = sub + vat
    path = os.path.join(OUT, f"inv_{i:04d}.pdf")
    c = canvas.Canvas(path, pagesize=A4)
    W, H = A4
    y = H - 60
    lab = {
        0: dict(title="TAX INVOICE", trn="TRN:", iban="IBAN:", sub="Subtotal", vat="VAT 5%", tot="Total (AED)", no="Invoice No:", date="Date:"),
        1: dict(title="Tax Invoice", trn="Tax Registration No.", iban="Bank Account (IBAN)", sub="Taxable Amount", vat="VAT Amount", tot="Amount Payable", no="Invoice #", date="Invoice Date"),
        2: dict(title="TAX INVOICE", trn="VAT Reg. No:", iban="Account IBAN:", sub="Net Amount", vat="VAT (5%)", tot="Grand Total", no="Inv. No.", date="Dated"),
        3: dict(title="Tax Invoice / Fatoorah Dareebiya", trn="TRN No.", iban="IBAN No.", sub="Total excl. VAT", vat="VAT @ 5%", tot="Total incl. VAT", no="Bill No:", date="Issue Date:"),
        4: dict(title="TAX INVOICE", trn="Supplier TRN", iban="Pay to IBAN", sub="Sub Total", vat="Tax", tot="TOTAL DUE AED", no="Reference", date="Date of Issue"),
        5: dict(title="INVOICE (TAX)", trn="Tax Reg #", iban="Beneficiary IBAN", sub="Amount before VAT", vat="Value Added Tax", tot="Balance Due", no="Document No", date="Doc Date"),
        6: dict(title="TAX INVOICE", trn="VAT Registration Number:", iban="Bank IBAN:", sub="Total Before Tax", vat="VAT Payable", tot="Net Payable (AED)", no="Our Ref:", date="Invoice Date:"),
        7: dict(title="Tax Invoice", trn="TRN #", iban="IBAN", sub="Sub-total", vat="VAT @5%", tot="Total Amount Due", no="Invoice Number:", date="Date of Supply:"),
        8: dict(title="TAX INVOICE  /  فاتورة ضريبية", trn="TRN (UAE):", iban="IBAN Number -", sub="Value of Supply", vat="VAT Charged", tot="Invoice Value", no="Invoice Serial:", date="Supply Date -"),
        10: dict(title="TAX INVOICE", trn="Supplier Tax Registration (TRN)", iban="Account (IBAN)", sub="Taxable Value", vat="5% VAT", tot="Invoice Total AED", no="Bill Number", date="Billing Date"),
        11: dict(title="Tax Invoice - Original", trn="TRN Number", iban="IBAN for payment", sub="Net Total", vat="VAT Amount (5%)", tot="Gross Total", no="Tax Invoice No.", date="Date"),
        9: dict(title="Commercial Tax Invoice", trn="Tax ID", iban="Remit to IBAN", sub="Goods & Services", vat="Output VAT", tot="To Pay", no="Serial", date="On"),
    }[t]
    font = ["Helvetica", "Times-Roman", "Courier"][t % 3]
    bold = {"Helvetica": "Helvetica-Bold", "Times-Roman": "Times-Bold", "Courier": "Courier-Bold"}[font]
    def tx(x, yy, s, f=font, sz=10):
        c.setFont(f, sz); c.drawString(x, yy, s)
    if t in (10, 11):
        tx(40, y, lab["title"], bold, 14)
        rows = [("Supplier", name), ("Address", rnd.choice(CITIES)), (lab["trn"], s_trn), (lab["no"], inv_no), (lab["date"], d)]
        for k, v in rows:
            y -= 16; tx(40, y, k + ":"); tx(230, y, v, bold if k == "Supplier" else font)
        y += 40
    elif t in (8, 9):
        cur = "AED " if t == 8 else ""
        tx(40, y, lab["title"].split("/")[0].strip(), bold, 13)
        tx(40, y - 22, name.upper() if t == 9 else name, bold, 12); tx(40, y - 36, rnd.choice(CITIES) + ", United Arab Emirates")
        tx(40, y - 50, f"{lab['trn']} {s_trn}"); tx(330, y - 22, f"{lab['no']} {inv_no}"); tx(330, y - 36, f"{lab['date']} {d}")
    elif t in (6, 7):
        tx(W - 260, y, name, bold, 13); tx(W - 260, y - 15, rnd.choice(CITIES)); tx(W - 260, y - 29, f"{lab['trn']} {s_trn}")
        tx(40, y, lab["title"], bold, 16); tx(40, y - 20, f"{lab['no']} {inv_no}"); tx(40, y - 34, f"{lab['date']} {d}")
    elif t in (0, 2, 4):
        tx(40, y, name, bold, 15); tx(40, y - 16, rnd.choice(CITIES)); tx(40, y - 30, f"{lab['trn']} {s_trn}")
        tx(W - 200, y, lab["title"], bold, 14); tx(W - 200, y - 18, f"{lab['no']} {inv_no}"); tx(W - 200, y - 32, f"{lab['date']} {d}")
    else:
        tx(W / 2 - 60, y, lab["title"], bold, 14); y -= 26
        tx(40, y, "From:", bold); tx(40, y - 14, name, bold, 12); tx(40, y - 28, rnd.choice(CITIES)); tx(40, y - 42, f"{lab['trn']} {s_trn}")
        tx(W - 220, y, f"{lab['no']} {inv_no}"); tx(W - 220, y - 14, f"{lab['date']} {d}")
        y -= 14
    y -= 70
    tx(40, y, "Bill To:", bold); tx(40, y - 14, cust); tx(40, y - 28, f"Customer TRN: {c_trn}")
    y -= 60
    tx(40, y, "Description", bold); tx(300, y, "Qty", bold); tx(360, y, "Unit Price", bold); tx(460, y, "Amount", bold)
    for desc, qty, unit, amt in lines:
        y -= 16; tx(40, y, desc); tx(300, y, str(qty)); tx(360, y, money(unit)); tx(460, y, money(amt))
    y -= 30
    mf = (lambda x: "AED " + money(x)) if t == 8 else money
    tx(340, y, lab["sub"]); tx(450, y, mf(sub)); y -= 15
    tx(340, y, lab["vat"]); tx(450, y, mf(vat)); y -= 15
    tx(340, y, lab["tot"], bold); tx(450, y, mf(tot), bold)
    y -= 50
    tx(40, y, "Payment details", bold); y -= 15
    bank = {"003": "ADCB", "023": "Commercial Bank of Dubai", "024": "Dubai Islamic Bank", "026": "Emirates NBD", "033": "Mashreq", "034": "Emirates Islamic", "035": "First Abu Dhabi Bank", "040": "RAKBANK", "041": "Sharjah Islamic Bank", "044": "Standard Chartered", "050": "Abu Dhabi Islamic Bank", "057": "Ajman Bank"}[iban[4:7]]
    tx(40, y, f"Bank: {bank}"); y -= 15
    tx(40, y, f"{lab['iban']} {fmt_iban(iban, rnd.randint(0, 2))}"); y -= 15
    tx(40, y, f"Account name: {name}")
    c.save()
    # degraded "phone photo"
    doc = fitz.open(path)
    pix = doc[0].get_pixmap(dpi=rnd.choice([150, 170, 200]))
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    img = img.rotate(rnd.uniform(-2.5, 2.5), expand=True, fillcolor=(235, 235, 230))
    img = img.filter(ImageFilter.GaussianBlur(rnd.uniform(0.3, 1.0)))
    img.save(path.replace(".pdf", ".jpg"), quality=rnd.choice([55, 70, 85]))
    return dict(file=os.path.basename(path), template=t, supplier_name=name, supplier_trn=s_trn, customer_trn=c_trn, iban=iban,
                invoice_number=inv_no.strip(), invoice_date=d, subtotal=str(sub), vat=str(vat), total=str(tot))


labels = [one(i) for i in range(N)]
json.dump(labels, open(os.path.join(OUT, "labels.json"), "w"), indent=1)
print(len(labels), "invoices in", OUT)
