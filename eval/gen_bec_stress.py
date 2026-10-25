"""Build the SYNTHETIC email stress set `data/bec_stress_synth_v1.json`.

Every item is invented by this script (fictional companies, people and bank details, no links, no
attachments) and carries `synthetic: true`. It is a stress / smoke set for the email checks. It is NOT
real-email accuracy and NOT a promotion holdout: the generator's author also wrote the model-facing
cues, so scores here say little about real mail. Real emails stay the only basis for promotion.

Parts: `ext` = 150 fraud + 150 genuine general business mail; `uae` = 40 fraud + 40 genuine UAE-flavoured
supplier mail (a stand-in for the pilot set until the partner shares real redacted emails). Hard cases
are included on purpose: genuine bank-detail notices that tell the reader to verify by phone, genuine
urgent payment requests, and fraud written with no trigger words at all.
Usage: python3 eval/gen_bec_stress.py [seed]
"""
import json
import os
import random
import sys

rnd = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 2026)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "bec_stress_synth_v1.json")
SRC = "synthetic: eval/gen_bec_stress.py (fictional, no real person, company or account)"

FIRST = ["Ahmed", "Priya", "Sara", "Mohammed", "John", "Fatima", "Ravi", "Maria", "Omar", "Aisha", "David", "Hessa", "Tariq",
         "Nadia", "Vikram", "Elena", "Yousef", "Grace", "Imran", "Sofia", "Khalid", "Rania", "Peter", "Mei", "Joseph", "Lina"]
LAST = ["Al Mazrouei", "Nair", "Khan", "Thompson", "D'Souza", "Haddad", "Iyer", "Rossi", "Al Suwaidi", "Fernandes", "Chen",
        "Mathew", "Qureshi", "Bianchi", "Al Hashemi", "Walker", "Menon", "Saleh", "Pereira", "Hussain"]
CO_A = ["Gulf", "Falcon", "Oasis", "Crescent", "Pearl", "Horizon", "Delta", "Summit", "Marina", "Desert", "Zenith", "Najm",
        "Bluewave", "Atlas", "Meridian", "Sahara", "Tawazun", "Lotus", "Harbour", "Cedar"]
CO_B = ["Trading", "Logistics", "Engineering", "Printing", "Facilities Management", "Stationery", "IT Solutions", "Catering",
        "Packaging", "Electrical", "Interiors", "Marketing", "Freight", "Building Materials", "Cleaning Services", "Office Supplies"]
CO_S = ["LLC", "FZE", "FZCO", "Ltd", "Co. LLC", "Est."]
CITY = ["Dubai", "Sharjah", "Abu Dhabi", "Ajman", "Jebel Ali", "Al Quoz", "Deira", "Ras Al Khaimah"]
BANK = ["Emirates NBD", "Abu Dhabi Commercial Bank", "Mashreq Bank", "First Abu Dhabi Bank", "RAKBANK", "Dubai Islamic Bank",
        "Commercial Bank of Dubai", "Sharjah Islamic Bank"]
GOODS = ["printer toner", "office furniture", "forklift servicing", "website maintenance", "packaging cartons", "AC maintenance",
         "uniforms", "pallet racking", "catering for the staff event", "IT support hours", "courier charges", "signage", "pest control",
         "laptop batteries", "cleaning materials", "freight forwarding", "stationery order", "security guard services"]
MONTH = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def person():
    return f"{rnd.choice(FIRST)} {rnd.choice(LAST)}"


def company():
    return f"{rnd.choice(CO_A)} {rnd.choice(CO_B)} {rnd.choice(CO_S)}"


def inv():
    return rnd.choice(["INV-", "TI-", "SI-", "INV/", ""]) + str(rnd.randint(1000, 99999))


def aed():
    return f"AED {rnd.randint(8, 900) * 125 + rnd.choice([0, 0, 40, 75, 250]):,}"


def iban():
    """Fictional AE IBAN with a valid mod-97 checksum (so the reader treats it as well-formed)."""
    bban = "0" + str(rnd.randint(10, 99)) + "".join(str(rnd.randint(0, 9)) for _ in range(16))
    chk = 98 - int(bban + "142800") % 97
    return f"AE{chk:02d}{bban}"


def date():
    return f"{rnd.randint(1, 28)} {rnd.choice(MONTH)} 2026"


def pick(*xs):
    return rnd.choice(xs)


def sign(name, role=None):
    return pick(f"Regards,\n{name}", f"Best regards,\n{name}\n{role or 'Accounts'}", f"Thanks,\n{name}",
                f"Kind regards,\n{name}\n{role or 'Finance'}", f"Thank you,\n{name}", f"{name}\n{role or ''}".strip(),
                f"Sent from my iPhone\n\n{name}")


def greet(n):
    return pick(f"Dear {n},", f"Hi {n},", f"Hello {n},", f"{n},", "Dear Accounts Team,", "Hi team,", "Good morning,", "Dear Sir/Madam,")


# ---- fraud generators: each returns (subject, body, attack_type) -------------------------------------------------
def f_bank_change(c, me, uae):
    sup, who = company(), person()
    new = iban()
    return (pick(f"Updated bank details - {sup}", "Change of bank account", "Important: banking information update",
                 f"RE: Invoice {inv()}", "Account update"),
            "\n\n".join([greet(me), pick(
                f"We have recently changed our bank. Please use the account below for invoice {inv()} ({aed()}) and all payments going forward.",
                f"Following our year-end restructuring we have moved to a different bank. Kindly update your vendor records and pay {aed()} to the new account.",
                f"Please note our previous account is now closed. Payment for the outstanding balance should be made to the new account on the attached letter."),
                f"Bank: {pick(*BANK)}\nAccount name: {sup}\nIBAN: {new}", pick(
                "Please confirm by reply once updated.", "Kindly acknowledge receipt and process this week.", "Reply to this email only, our phone lines are being migrated.", ""),
                sign(who, "Finance Manager")]), "bank_change")


def f_overdue_new_acct(c, me, uae):
    return (pick(f"OVERDUE: invoice {inv()}", "Final notice - payment outstanding", f"Reminder {inv()}"),
            "\n\n".join([greet(me), pick(
                f"Our records show invoice {inv()} for {aed()} is still unpaid. To avoid a late charge please remit today to the account below; the details on the original invoice are no longer valid.",
                f"This is the second reminder for {aed()}. Note that our collections account has changed, use the IBAN below.",
                f"Payment of {aed()} is {rnd.randint(14, 60)} days late. Please settle immediately to our new collections account."),
                f"IBAN: {iban()}\nBeneficiary: {company()}", sign(person(), "Accounts Receivable")]), "overdue_new_account")


def f_ceo_wire(c, me, uae):
    boss = person()
    return (pick("Quick favour", "Are you available?", "Urgent", "Request", "Confidential", "Task for today"),
            "\n\n".join([pick(f"{me},", f"Hi {me},"), pick(
                f"Are you at your desk? I need you to process a transfer of {aed()} today. I am in a meeting all day so cannot take calls. Send me the confirmation when it is done.",
                f"I need a payment made to a new supplier today, {aed()}. It is time sensitive and I will explain later. Please keep this between us.",
                f"Can you handle something discreetly for me? A payment of {aed()} for a deal we have not announced yet. Reply and I will send the beneficiary details.",
                f"Please buy {rnd.randint(3, 8)} gift cards of AED {pick(500, 1000, 2000)} each for a client meeting and send me the codes by email. I will reimburse you."),
                pick(f"{boss}\nManaging Director", f"{boss}\nGeneral Manager", f"Sent from my iPhone\n{boss}", f"{boss}")]), "ceo_fraud")


def f_payroll(c, me, uae):
    emp = person()
    return (pick("Salary account change", "Payroll update", "New bank for my salary", "Direct deposit"),
            "\n\n".join([greet(me), pick(
                "I have changed my bank and need my salary paid into a new account from this month. Please update payroll before the cut-off.",
                "My old card was blocked so please move my salary to the account below. I will send the bank letter later.",
                "Kindly change my salary transfer details, the new account is below. I am travelling so please reply by email only."),
                f"IBAN: {iban()}\nBank: {pick(*BANK)}", sign(emp, "Staff")]), "payroll_diversion")


def f_fake_invoice(c, me, uae):
    sup = company()
    return (pick(f"Invoice {inv()}", f"{sup} - invoice for {pick(*GOODS)}", "Tax invoice attached", f"Payment due {date()}"),
            "\n\n".join([greet(me), pick(
                f"Please find our invoice {inv()} for {pick(*GOODS)} ({aed()}) as agreed with your manager. Payment is due within 3 days.",
                f"Attached is the invoice for the {pick(*GOODS)} delivered last month. Please arrange payment of {aed()} to the account on the invoice.",
                f"Following our call, please see the invoice for {aed()}. Kindly pay by Thursday."),
                f"Account: {iban()} ({pick(*BANK)})", sign(person(), sup)]), "fake_supplier_invoice")


def f_quiet(c, me, uae):
    """No trigger words: reads like routine mail, only the account differs from what the business pays."""
    sup = company()
    return (pick(f"Invoice {inv()} - {sup}", f"{sup}: invoice for {MONTH[rnd.randint(0, 11)]}", f"Re: {pick(*GOODS)}"),
            "\n\n".join([greet(me), pick(
                f"Invoice {inv()} for {aed()} is attached. Transfer to IBAN {iban()} please.",
                f"Hope you are well. Here is this month's invoice, {aed()}. Pay to {iban()}.",
                f"Sending the invoice for {pick(*GOODS)}. Total {aed()}, account {iban()}, thank you."),
                sign(person(), sup)]), "quiet_account_swap")


def f_remittance(c, me, uae):
    return (pick("Payment confirmation", f"Remittance advice {rnd.randint(100000, 999999)}", "SWIFT copy attached", "Transfer completed"),
            "\n\n".join([greet(me), pick(
                f"We have transferred {aed()} to your account today. Attached is the SWIFT confirmation. Kindly release the goods and confirm shipment.",
                f"Payment of {aed()} has been made. Please open the attached remittance to see the details and reply with your delivery date.",
                f"Our bank has sent {aed()} but a correction fee is pending. Please send the fee of AED {rnd.randint(2, 9) * 150} so the transfer can complete."),
                sign(person(), "Treasury")]), "fake_remittance")


def f_thread_hijack(c, me, uae):
    sup = company()
    return (f"RE: {pick(*GOODS)} - invoice {inv()}",
            "\n\n".join([greet(me), pick(
                "Thanks for the update on the delivery. One more thing, our bank has asked us to switch accounts for all incoming payments, so please use the details below for the invoice we discussed.",
                "Good to hear it arrived. By the way our finance team has moved the receivables account, the new one is below. Please use it for this and later invoices."),
                f"IBAN {iban()}", sign(person(), sup), "On " + date() + ", " + person() + " wrote:\n> Please confirm the delivery date and send the invoice."]),
            "thread_hijack")


def f_lawyer(c, me, uae):
    return (pick("Confidential acquisition", "Legal matter - strictly confidential", "Time-sensitive transaction"),
            "\n\n".join([f"{me},", pick(
                f"I am the external counsel handling a confidential acquisition for the CEO. A deposit of {aed()} is needed today. Please do not discuss with anyone until it is announced.",
                f"The CEO has asked me to coordinate a payment of {aed()} for a pending transaction. I will send the escrow account details once you confirm availability."),
                sign(person(), "Legal Counsel")]), "lawyer_impersonation")


FRAUD_GENS = [f_bank_change, f_overdue_new_acct, f_ceo_wire, f_payroll, f_fake_invoice, f_quiet, f_remittance, f_thread_hijack, f_lawyer]
FRAUD_W = [4, 2, 2, 1, 2, 3, 1, 2, 1]


# ---- genuine generators -------------------------------------------------------------------------------------------
def g_invoice(c, me, uae):
    sup = company()
    return (pick(f"Invoice {inv()} from {sup}", f"Tax invoice {inv()}", f"Invoice for {pick(*GOODS)}"),
            "\n\n".join([greet(me), pick(
                f"Please find attached tax invoice {inv()} for {pick(*GOODS)}, {aed()} including 5% VAT. Payment terms are {pick(30, 45, 60)} days to the account shown on the invoice.",
                f"Attached is this month's invoice, {aed()}. Our bank details are unchanged.",
                f"Invoice {inv()} for {aed()} is attached. Please quote the invoice number when paying and let us know if the PO number differs."),
                sign(person(), sup)]))


def g_reminder(c, me, uae):
    return (pick(f"Reminder: invoice {inv()}", "Payment reminder", f"Statement and reminder - {MONTH[rnd.randint(0, 11)]}"),
            "\n\n".join([greet(me), pick(
                f"A friendly reminder that invoice {inv()} for {aed()} fell due on {date()}. If you have already paid, please ignore this and send the remittance advice.",
                f"Our statement shows {aed()} outstanding across {rnd.randint(2, 4)} invoices. Payment details are as on previous invoices. Let us know if anything does not match your records.",
                f"Invoice {inv()} is {rnd.randint(7, 21)} days past due. We would appreciate settlement, or a date by which you expect to pay."),
                sign(person(), "Accounts Receivable")]))


def g_receipt(c, me, uae):
    return (pick(f"Receipt for invoice {inv()}", "Payment received - thank you", f"Payment received {date()}"),
            "\n\n".join([greet(me), pick(
                f"Thank you, we received {aed()} on {date()} against invoice {inv()}. The receipt is attached.",
                f"Confirming receipt of your transfer of {aed()}. Your account is now up to date."), sign(person(), "Accounts")]))


def g_remittance(c, me, uae):
    return (pick(f"Remittance advice - {inv()}", "Payment advice", f"Paid: invoice {inv()}"),
            "\n\n".join([greet(me), pick(
                f"We released {aed()} today against invoice {inv()} through our normal payment run. Funds should reach your account within two working days.",
                f"Payment advice: {aed()} paid on {date()} to the account you have on file. Reference {inv()}."), sign(person(), "Accounts Payable")]))


def g_po_query(c, me, uae):
    return (pick(f"PO number for {inv()}", "Query on invoice", f"Invoice {inv()} - missing information"),
            "\n\n".join([greet(me), pick(
                f"Our accounts system rejected invoice {inv()} because it has no PO number. Could you resend it with the PO reference? We will then pay in the next run.",
                f"The quantity on line 2 of invoice {inv()} does not match the delivery note ({rnd.randint(10, 80)} received). Please send a corrected invoice or a credit note.",
                f"Could you confirm your TRN and VAT registration details? We need them on file before we can pay {aed()}."), sign(person(), "Accounts Payable")]))


def g_bank_notice_verified(c, me, uae):
    """Hard negative: a real bank-detail notice that itself tells the reader to verify by phone."""
    sup = company()
    return (pick(f"Notice of bank account change - {sup}", "Change in our banking details", "Bank details update (please verify by phone)"),
            "\n\n".join([greet(me), pick(
                f"As notified in our letter dated {date()}, our account moves to {pick(*BANK)} from {date()}. Before you update anything, please call our finance office on the number in your contract and ask for {person()} to confirm. We will not change details by email alone.",
                f"We are changing our bank from next month. A signed letter on company letterhead follows by courier. Please verify these details with your usual contact by phone before paying; do not act on this email only.",
                f"Our new account details are below, effective with the next invoice. For your protection, confirm them by calling us on the number you already have. We have also emailed your account manager."),
                f"New IBAN: {iban()}", sign(person(), "Finance Manager")]))


def g_urgent(c, me, uae):
    """Hard negative: genuine urgency / deadline, no account change."""
    return (pick("Urgent: payment run closes today", "Please approve today", f"Deadline {date()}", "Time sensitive"),
            "\n\n".join([greet(me), pick(
                f"The payment run closes at 3 pm today. Invoice {inv()} for {aed()} is approved, could you confirm the PO so it can be included? Otherwise it moves to next week.",
                f"We need your signed approval on invoice {inv()} ({aed()}) before the end of day so the supplier is paid on time. It is the same supplier and account as usual.",
                f"The customs clearance fee of {aed()} must be paid before the shipment is released tomorrow. The invoice from the broker is attached, same broker as previous shipments."),
                sign(person(), "Finance")]))


def g_quotation(c, me, uae):
    return (pick(f"Quotation {rnd.randint(100, 999)}", f"Quote: {pick(*GOODS)}", "Proposal and pricing"),
            "\n\n".join([greet(me), pick(
                f"Thanks for your enquiry. Our quotation for {pick(*GOODS)} is attached, {aed()} excluding VAT, valid for 14 days.",
                f"As discussed, here is the revised price for {pick(*GOODS)}. If it works for you, send a PO and we will schedule delivery."),
                sign(person(), company())]))


def g_credit(c, me, uae):
    return (pick(f"Credit note for invoice {inv()}", "Credit note issued", "Adjustment to your account"),
            "\n\n".join([greet(me), f"We have issued a credit note of {aed()} against invoice {inv()} for the returned goods. It will show on your next statement and be netted off the next payment.",
                         sign(person(), "Accounts")]))


def g_internal(c, me, uae):
    return (pick("Approval for supplier payment", "Month end checklist", "Invoices awaiting approval", "Budget query"),
            "\n\n".join([greet(me), pick(
                f"Three invoices totalling {aed()} are waiting for your approval in the system. All are from existing suppliers with the usual details.",
                f"Reminder that month-end close is on {date()}. Please send all outstanding supplier invoices to accounts by then.",
                f"Can you confirm whether the {pick(*GOODS)} cost of {aed()} falls under this quarter's budget? Finance needs it for the accrual."),
                sign(person(), "Finance")]))


GEN_GENUINE = [g_invoice, g_reminder, g_receipt, g_remittance, g_po_query, g_bank_notice_verified, g_urgent, g_quotation, g_credit, g_internal]
GEN_W = [4, 3, 2, 2, 2, 2, 2, 2, 1, 2]

# ---- Arabic items (small, for the UAE part) -----------------------------------------------------------------------
AR_FRAUD = [
    ("تغيير الحساب البنكي", "السلام عليكم،\n\nنود إبلاغكم بأننا قمنا بتغيير حسابنا البنكي. يرجى تحويل مبلغ الفاتورة {a} إلى الحساب الجديد أدناه اليوم.\nآيبان: {i}\n\nمع التحية،\n{n}"),
    ("عاجل: دفعة", "مرحبا،\n\nأحتاج منك تحويل مبلغ {a} اليوم إلى مورد جديد. أنا في اجتماع ولا أستطيع الرد على المكالمات. أبلغني فور الانتهاء.\n\n{n}\nالمدير العام"),
    ("فاتورة متأخرة", "تحية طيبة،\n\nفاتورتكم رقم {v} بمبلغ {a} متأخرة. تم إغلاق حسابنا القديم، يرجى الدفع إلى الحساب الجديد: {i}\n\n{n}\nالحسابات"),
]
AR_GENUINE = [
    ("فاتورة ضريبية", "السلام عليكم،\n\nنرفق لكم الفاتورة الضريبية رقم {v} بمبلغ {a} شاملة ضريبة القيمة المضافة. تفاصيل الحساب البنكي كما في الفواتير السابقة.\n\nمع التحية،\n{n}"),
    ("تذكير بالدفع", "تحية طيبة،\n\nنود تذكيركم بأن الفاتورة رقم {v} بمبلغ {a} مستحقة السداد. إذا تم الدفع يرجى تزويدنا بإشعار التحويل.\n\n{n}\nالحسابات"),
    ("إشعار استلام دفعة", "السلام عليكم،\n\nنؤكد استلام مبلغ {a} مقابل الفاتورة رقم {v}. شكراً لتعاملكم معنا.\n\n{n}"),
]


def ar(tpls):
    s, b = rnd.choice(tpls)
    return s, b.format(a=aed().replace("AED", "درهم"), i=iban(), v=inv(), n=person())


def build(n, label, gens, weights, uae, part):
    rows = []
    for k in range(n):
        me = rnd.choice(FIRST)
        if uae and rnd.random() < 0.15:
            subj, body = ar(AR_FRAUD if label == "fraud" else AR_GENUINE)
            kind, lang = ("arabic_" + ("fraud" if label == "fraud" else "genuine")), "ar"
        else:
            g = rnd.choices(gens, weights)[0]
            out = g(None, me, uae)
            subj, body = out[0], out[1]
            kind, lang = (out[2] if label == "fraud" else g.__name__[2:]), "en"
        sender = person()
        rows.append({
            "label": label, "subject": subj, "body": body, "attack_type": kind if label == "fraud" else "genuine_" + kind,
            "part": part, "lang": lang, "synthetic": True, "source_title": f"Synthetic {part} {label} #{k + 1}",
            "source_url": SRC, "licence": "Project-generated; no third-party text", "same_site_as_training": False,
            "notes": "Synthetic stress item; do not quote as real-email accuracy.",
        })
    return rows


rows = (build(150, "fraud", FRAUD_GENS, FRAUD_W, False, "ext") + build(150, "genuine", GEN_GENUINE, GEN_W, False, "ext")
        + build(40, "fraud", FRAUD_GENS, FRAUD_W, True, "uae") + build(40, "genuine", GEN_GENUINE, GEN_W, True, "uae"))
rnd.shuffle(rows)
for i, r in enumerate(rows, 1):
    r["id"] = f"synth_{i:03d}"
json.dump(rows, open(OUT, "w"), ensure_ascii=False, indent=1)
print(len(rows), "items ->", os.path.relpath(OUT))
