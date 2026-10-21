# Pilot measurement

Pilot invoices are real business documents. They stay outside this repo, outside public chats, and are never used as examples
in code, tests or docs (see AGENTS.md rules 7 and 8). Use generic names ("pilot A", "pilot B") in anything written down.

1. Collect invoices (English, Arabic, bilingual; PDFs and phone photos) into a private folder with one sub-folder per business, after
   the business has agreed and personal data not needed for the check has been removed.
2. Optional but best: a human types a labels CSV from the paper invoices (`file,supplier_name,supplier_trn,iban,invoice_number,invoice_date,subtotal,vat,total`).
3. `python3 eval/pilot_report.py "<private folder>" --labels labels.csv`

The script replays each business's invoices in date order against a throw-away history (every invoice counted as paid afterwards,
since the invoices are assumed genuine) and reports: verdicts, warnings per 100 invoices by cause, how many "first payment" ambers are
unavoidable (one per new account), how many invoices are flagged only by first payment, reader confidence, language mix and, with
labels, per-field accuracy. Console output is masked; the JSON report holds file names only.

How to read it: a warning on a genuine invoice is a false alarm unless a human confirms it is real (for example a supplier that really
changed banks). "Bank details changed" on a genuine invoice usually means a supplier with several accounts, or a name read differently
by OCR, which is exactly what the pilot should measure. Holdout rule: tune only on data you have not used to report results.
