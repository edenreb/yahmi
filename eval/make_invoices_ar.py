"""Bilingual (Arabic + English) UAE tax invoices, the way many UAE suppliers print them.

Usage: python3 make_invoices_ar.py OUT_DIR N SEED
Variants (chosen at random per invoice):
  digits="latin"   - Arabic labels, Latin digits (most common)
  digits="eastern" - Arabic labels and Eastern Arabic digits for amounts, TRN and dates (٠١٢٣...)
The IBAN is always printed in Latin letters/digits, as banks issue it. Ground truth in labels.json.
"""
import json
import os
import random
import sys
from decimal import Decimal, ROUND_HALF_UP

import arabic_reshaper
import fitz
from bidi.algorithm import get_display
from PIL import Image, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

OUT, N, SEED = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
rnd = random.Random(SEED)
os.makedirs(OUT, exist_ok=True)
pdfmetrics.registerFont(TTFont("DV", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DVB", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))

BANK = {"003": "ADCB", "024": "Dubai Islamic Bank", "026": "Emirates NBD", "033": "Mashreq", "035": "First Abu Dhabi Bank", "040": "RAKBANK", "050": "Abu Dhabi Islamic Bank"}
NAMES = [("Al Waha Trading", "الواحة للتجارة"), ("Rimal Building Materials", "رمال لمواد البناء"), ("Noor Al Khaleej Contracting", "نور الخليج للمقاولات"),
         ("Bawabat Al Sahra Logistics", "بوابة الصحراء للخدمات اللوجستية"), ("Lulu Al Bahr Technical Services", "لؤلؤة البحر للخدمات الفنية"),
         ("Al Fajr Electromechanical", "الفجر للأعمال الكهروميكانيكية"), ("Zahrat Al Madina Catering", "زهرة المدينة للتموين"), ("Al Manara Printing Press", "المنارة للطباعة")]
SUFFIX = [("LLC", "ذ.م.م"), ("L.L.C", "ش.ذ.م.م"), ("FZE", "م.م.ح"), ("Est.", "مؤسسة")]
ITEMS = [("Cement bags 50kg", "أكياس أسمنت"), ("Cleaning services", "خدمات تنظيف"), ("AC maintenance", "صيانة مكيفات"), ("Steel rebar 12mm", "حديد تسليح"), ("Delivery charges", "رسوم توصيل"), ("Paint 18L", "دهان")]
EAST = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def ar(s):
    return get_display(arabic_reshaper.reshape(s))


def iban():
    bban = rnd.choice(list(BANK)) + "".join(rnd.choice("0123456789") for _ in range(16))
    s = bban + "1014" + "00"
    return "AE" + f"{98 - int(s) % 97:02d}" + bban


def q2(x):
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def one(i):
    digits = rnd.choice(["latin", "latin", "eastern"])
    num = (lambda s: s.translate(EAST)) if digits == "eastern" else (lambda s: s)
    (en, arn), (sen, sar) = rnd.choice(NAMES), rnd.choice(SUFFIX)
    name, name_ar = f"{en} {sen}", f"{arn} {sar}"
    s_trn = "100" + "".join(rnd.choice("0123456789") for _ in range(12))
    c_trn = "100" + "".join(rnd.choice("0123456789") for _ in range(12))
    ib = iban()
    inv_no = rnd.choice(["INV-", "TI-", ""]) + str(rnd.randint(1000, 99999))
    d = f"{rnd.randint(1, 28):02d}/{rnd.randint(1, 12):02d}/2026"
    lines = []
    for _ in range(rnd.randint(1, 4)):
        it = rnd.choice(ITEMS); qty = rnd.randint(1, 30); unit = Decimal(rnd.randint(500, 200000)) / 100
        lines.append((it, qty, unit, q2(unit * qty)))
    sub = sum(l[3] for l in lines); vat = q2(sub * Decimal("0.05")); tot = sub + vat
    money = lambda x: num(f"{x:,.2f}")
    path = os.path.join(OUT, f"inv_{i:04d}.pdf")
    c = canvas.Canvas(path, pagesize=A4); W, H = A4

    def L(x, y, s, f="DV", sz=10):
        c.setFont(f, sz); c.drawString(x, y, s)

    def R(x, y, s, f="DV", sz=10):
        c.setFont(f, sz); c.drawRightString(x, y, s)

    y = H - 60
    L(40, y, "TAX INVOICE", "DVB", 14); R(W - 40, y, ar("فاتورة ضريبية"), "DVB", 14)
    y -= 24; L(40, y, name, "DVB", 12); R(W - 40, y, ar(name_ar), "DVB", 12)
    y -= 16; L(40, y, "Dubai, United Arab Emirates"); R(W - 40, y, ar("دبي، الإمارات العربية المتحدة"))
    y -= 16; L(40, y, f"TRN: {num(s_trn)}"); R(W - 40, y, ar("الرقم الضريبي"))
    y -= 16; L(40, y, f"Invoice No: {inv_no}"); R(W - 40, y, ar("رقم الفاتورة"))
    y -= 16; L(40, y, f"Date: {num(d)}"); R(W - 40, y, ar("التاريخ"))
    y -= 34; L(40, y, "Bill To:", "DVB"); R(W - 40, y, ar("إلى"), "DVB")
    y -= 14; L(40, y, "Customer: Sample Customer LLC")
    y -= 14; L(40, y, f"Customer TRN: {num(c_trn)}")
    y -= 34
    L(40, y, "Description", "DVB"); L(300, y, "Qty", "DVB"); L(360, y, "Unit Price", "DVB"); L(460, y, "Amount", "DVB")
    for (ien, iar), qty, unit, amt in lines:
        y -= 16; L(40, y, f"{ien} / "); c.drawString(40 + c.stringWidth(f"{ien} / ", "DV", 10), y, ar(iar))
        L(300, y, num(str(qty))); L(360, y, money(unit)); L(460, y, money(amt))
    y -= 30
    for lab_en, lab_ar, val, f in (("Subtotal", "المجموع قبل الضريبة", sub, "DV"), ("VAT 5%", "ضريبة القيمة المضافة", vat, "DV"), ("Total (AED)", "الإجمالي", tot, "DVB")):
        L(250, y, lab_en, f); c.setFont(f, 10); c.drawRightString(440, y, ar(lab_ar)); L(460, y, money(val), f); y -= 15
    y -= 35
    L(40, y, "Payment details", "DVB"); R(W - 40, y, ar("بيانات الدفع"), "DVB"); y -= 15
    L(40, y, f"Bank: {BANK[ib[4:7]]}"); y -= 15
    L(40, y, f"IBAN: {' '.join(ib[k:k + 4] for k in range(0, len(ib), 4))}"); R(W - 40, y, ar("رقم الآيبان")); y -= 15
    L(40, y, f"Account name: {name}")
    c.save()
    doc = fitz.open(path)
    pix = doc[0].get_pixmap(dpi=rnd.choice([150, 170, 200]))
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    img = img.rotate(rnd.uniform(-2.5, 2.5), expand=True, fillcolor=(235, 235, 230))
    img = img.filter(ImageFilter.GaussianBlur(rnd.uniform(0.3, 1.0)))
    img.save(path.replace(".pdf", ".jpg"), quality=rnd.choice([55, 70, 85]))
    return dict(file=os.path.basename(path), template=f"ar_{digits}", supplier_name=name, supplier_trn=s_trn, customer_trn=c_trn, iban=ib,
                invoice_number=inv_no, invoice_date=d, subtotal=str(sub), vat=str(vat), total=str(tot))


labels = [one(i) for i in range(N)]
json.dump(labels, open(os.path.join(OUT, "labels.json"), "w"), indent=1)
print(len(labels), "invoices in", OUT)
