"""Build the test fixtures: 3 past genuine invoices from one supplier, a genuine new invoice, and a fraudulent
copy with changed bank details, plus the two emails. All companies and numbers are invented."""
import os

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = os.path.dirname(os.path.abspath(__file__))
SUP = "Falcon Building Materials LLC"
TRN = "100384920571003"
GOOD = "AE460260001015583920101"   # Emirates NBD (026)
BAD = "AE950330000019284756302"    # Mashreq (033)


def iban_fix(iban):
    bban = iban[4:]
    s = bban + "1014" + "00"
    return "AE" + f"{98 - int(s) % 97:02d}" + bban


GOOD, BAD = iban_fix(GOOD), iban_fix(BAD)


def inv(path, no, date, items, iban, bank):
    c = canvas.Canvas(path, pagesize=A4); W, H = A4; y = H - 60
    c.setFont("Helvetica-Bold", 15); c.drawString(40, y, SUP)
    c.setFont("Helvetica", 10); c.drawString(40, y - 16, "Al Quoz Industrial 3, Dubai"); c.drawString(40, y - 30, f"TRN: {TRN}")
    c.setFont("Helvetica-Bold", 14); c.drawString(W - 200, y, "TAX INVOICE")
    c.setFont("Helvetica", 10); c.drawString(W - 200, y - 18, f"Invoice No: {no}"); c.drawString(W - 200, y - 32, f"Date: {date}")
    y -= 100; c.setFont("Helvetica-Bold", 10); c.drawString(40, y, "Bill To:")
    c.setFont("Helvetica", 10); c.drawString(40, y - 14, "Sample Customer LLC"); c.drawString(40, y - 28, "Customer TRN: 100771234560003")
    y -= 60; c.setFont("Helvetica-Bold", 10)
    for x, t in [(40, "Description"), (300, "Qty"), (360, "Unit Price"), (460, "Amount")]:
        c.drawString(x, y, t)
    c.setFont("Helvetica", 10); sub = 0
    for d, q, u in items:
        y -= 16; a = q * u; sub += a
        c.drawString(40, y, d); c.drawString(300, y, str(q)); c.drawString(360, y, f"{u:,.2f}"); c.drawString(460, y, f"{a:,.2f}")
    vat = round(sub * 0.05, 2); y -= 30
    c.drawString(360, y, "Subtotal"); c.drawString(460, y, f"{sub:,.2f}"); y -= 15
    c.drawString(360, y, "VAT 5%"); c.drawString(460, y, f"{vat:,.2f}"); y -= 15
    c.setFont("Helvetica-Bold", 10); c.drawString(360, y, "Total (AED)"); c.drawString(460, y, f"{sub + vat:,.2f}")
    y -= 50; c.drawString(40, y, "Payment details"); c.setFont("Helvetica", 10)
    c.drawString(40, y - 15, f"Bank: {bank}"); c.drawString(40, y - 30, f"IBAN: {' '.join(iban[i:i+4] for i in range(0, 23, 4))}"); c.drawString(40, y - 45, f"Account name: {SUP}")
    c.save()


os.makedirs(os.path.join(OUT, "past"), exist_ok=True)
inv(f"{OUT}/past/past_1.pdf", "INV-2041", "12/05/2026", [("Gypsum board 12mm", 120, 28.5), ("Delivery charges", 1, 150.0)], GOOD, "Emirates NBD")
inv(f"{OUT}/past/past_2.pdf", "INV-2177", "18/07/2026", [("Plywood 18mm sheets", 60, 92.0)], GOOD, "Emirates NBD")
inv(f"{OUT}/past/past_3.pdf", "INV-2290", "02/09/2026", [("Aluminium profiles", 40, 145.0), ("Delivery charges", 1, 150.0)], GOOD, "Emirates NBD")
inv(f"{OUT}/genuine_new.pdf", "INV-2391", "14/10/2026", [("MDF panels 18mm", 80, 110.0), ("Delivery charges", 1, 150.0)], GOOD, "Emirates NBD")
inv(f"{OUT}/fraud_new.pdf", "INV-2391", "14/10/2026", [("MDF panels 18mm", 80, 110.0), ("Delivery charges", 1, 150.0)], BAD, "Mashreq")
open(f"{OUT}/email_genuine.txt", "w").write(
    "From: Rashid Accounts <accounts@falconbm.ae>\nSubject: Invoice INV-2391\n\nDear Accounts Team,\n\n"
    "Please find attached invoice INV-2391 for the MDF panels delivered on Monday, payable within 30 days to the account shown on the invoice.\n\nKind regards,\nRashid\nFalcon Building Materials LLC\n")
open(f"{OUT}/email_fraud.txt", "w").write(
    "From: Rashid Accounts <accounts@falconbrn.ae>\nReply-To: rashid.falcon.accounts@gmail.com\nSubject: URGENT - updated bank details INV-2391\n\nDear Accounts Team,\n\n"
    "Due to an ongoing audit, our Emirates NBD account is temporarily unavailable. Please remit invoice INV-2391 to our new Mashreq account shown on the attached invoice today to avoid a late fee. "
    "I am travelling and cannot take calls, kindly reply to this email only once the transfer is done.\n\nRegards,\nRashid\n")
print("fixtures written", GOOD, BAD)
