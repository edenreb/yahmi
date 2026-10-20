"""Generate synthetic TRAINING emails for the invoice-fraud model: fraud (bank-detail change, urgent
payment, CEO/payroll diversion) and legitimate supplier emails (invoices, reminders, remittance,
statements). Both classes come from the same generator so that writing style alone cannot separate
them; the model has to learn the intent. Never used for testing: the test set is real published emails.
"""
import json
import random
import sys

rnd = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 7)
N = int(sys.argv[1]) if len(sys.argv) > 1 else 1500

GREET = ["Dear {n},", "Hi {n},", "Hello {n},", "Good morning {n},", "Dear Sir/Madam,", "Dear Accounts Team,", "Hi team,", "{n},", "Greetings,"]
NAMES = ["Ahmed", "Priya", "Sara", "Mohammed", "John", "Fatima", "Ravi", "Maria", "Accounts", "Omar", "Aisha", "David"]
SIGN = ["Regards,\n{s}", "Best regards,\n{s}\nAccounts Department", "Thanks,\n{s}", "Kind regards,\n{s}\nFinance Manager", "Sent from my iPhone", "Thank you,\n{s}", "Warm regards,\n{s}"]
SENDERS = ["Rashid", "Neha", "Khalid", "Anna", "Mark", "Layla", "Sunil", "Finance Team", "Accounts Receivable"]
INV = lambda: f"{rnd.choice(['INV-','TI-','#',''])}{rnd.randint(1000, 99999)}"
AMT = lambda: f"AED {rnd.randint(1, 400) * 250:,}"

FRAUD = [
    "Please note that we have changed our bank account. Kindly make all future payments, including invoice {i}, to our new account below.",
    "Due to an ongoing audit, our usual account is temporarily unavailable. Please remit the outstanding {a} to the new account details attached.",
    "Our bank details have been updated. Please update your records and pay invoice {i} to the new IBAN in the attached letter before end of day.",
    "We are currently changing banks, so payments to the old account will be returned. Please use the new beneficiary details for {a}.",
    "Can you process a wire transfer of {a} today? It is urgent and confidential. I am in meetings and cannot take calls, just email me when done.",
    "I need you to handle a payment for an acquisition we are working on. Keep this between us until it is announced. Amount is {a}.",
    "Kindly confirm that you will settle invoice {i} to our new account. Our previous account is under review and can no longer receive funds.",
    "Please hold all payments to our old bank account. We will send you the updated banking details shortly. Reply to this email only.",
    "I have changed my bank and would like my salary deposited into the new account before the next payroll. Details are below.",
    "Our accounts department has moved to a new bank due to the year-end audit. Please send the payment of {a} to the new IBAN today to avoid a late fee.",
    "This is a reminder that invoice {i} is overdue. Note our new bank details as the old account has been closed for international transfers.",
    "Are you at your desk? I need a quick favour, a payment of {a} must go out today to a new supplier. I will explain later, do not call.",
    "Please disregard the bank details on the previous invoice; there was an error. The correct account for {a} is attached. Kindly process urgently.",
    "We have opened a new account with another bank for tax reasons. Kindly route invoice {i} there. Please do not use the details on our letterhead.",
    "Payment for {i} bounced because of a change in our banking partner. Please resend {a} to the new account below at your earliest.",
]
LEGIT = [
    "Please find attached invoice {i} for {a}, payable within 30 days to the account shown on the invoice.",
    "This is a friendly reminder that invoice {i} for {a} is now due. Payment details are unchanged from previous invoices.",
    "Thank you, we have received your payment of {a} against invoice {i}. A receipt is attached for your records.",
    "Please find attached our statement of account for this month. Kindly let us know if any items do not match your records.",
    "Remittance advice: we have today transferred {a} in settlement of invoice {i}. Please allow two working days for the funds.",
    "Invoice {i} is attached for the services delivered last week. Our bank details remain the same as before.",
    "Our bank details have not changed. If you receive any request to change them, please call us on our usual number before paying.",
    "Please note that invoice {i} is overdue by 15 days. We would appreciate settlement of {a} at your earliest convenience.",
    "Attached is the quotation you requested. If approved, we will issue a tax invoice and deliver within one week.",
    "We have updated our company address on our letterhead; bank details and TRN are unchanged. Updated invoice {i} attached.",
    "Could you share the PO number for invoice {i}? Our finance team needs it before they can process your payment of {a}.",
    "Your payment for invoice {i} is scheduled for Thursday through our usual payment run. Please send the original receipt.",
    "Please find the credit note for {a} against invoice {i}. The balance will be adjusted in your next statement.",
    "As discussed on the phone, attached is the revised invoice {i}. The only change is the quantity on line two.",
    "Kindly confirm receipt of invoice {i}. Payment terms are 45 days as per our agreement.",
]
EXTRA_FRAUD = ["Please treat this as urgent.", "Kindly confirm once done.", "Reply to this email only as I am travelling.", "Do not use the old details anymore.", "Let me know when payment is made so I can update the system.", ""]
EXTRA_LEGIT = ["Please let us know if you have any questions.", "Thank you for your business.", "Kindly confirm once received.", "Have a good day.", ""]


def email(tpl, extra):
    body = "\n\n".join([
        rnd.choice(GREET).format(n=rnd.choice(NAMES)),
        tpl.format(i=INV(), a=AMT()) + " " + rnd.choice(extra),
        rnd.choice(SIGN).format(s=rnd.choice(SENDERS)),
    ])
    subj = rnd.choice(["Invoice " + INV(), "Payment", "RE: Payment", "Urgent", "Account update", "Statement", "Outstanding invoice", "Request", "FW: invoice", ""])
    return (subj + "\n" + body).strip()


rows = [{"text": email(rnd.choice(FRAUD), EXTRA_FRAUD), "y": 1} for _ in range(N)] + [{"text": email(rnd.choice(LEGIT), EXTRA_LEGIT), "y": 0} for _ in range(N)]
json.dump(rows, open("synthetic_bec_train.json", "w"))
print(len(rows))
