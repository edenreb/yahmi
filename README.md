<p align="center">
  <img width="300" height="91" alt="yahmi_logo_ar" src="web/assets/logo-ar.png"/><br><br>
  Yahmi it before you pay it.
</p>


Check a supplier invoice before you pay it. A UAE small business forwards an invoice (PDF or photo) and,
optionally, the email it came with. Yahmi answers **Stop**, **Check** or **OK**, and every warning names
the record it came from.

Built for the UAE Hackathon 2026, challenge: *SME protection from phishing, invoice fraud and ransomware*.

## What it checks

| Check | How | Level |
|---|---|---|
| Bank details changed vs. what you paid this supplier before | Your own payment history | Red |
| First payment ever to this account | Your own payment history | Amber |
| Other businesses pay this supplier into a different account | Shared network memory (keyed fingerprints only) | Red |
| IBAN valid? Which bank? Legacy/merged bank code or exchange house? | ISO 13616 checksum + UAE bank-identifier list | Red / Amber |
| Supplier TRN format, VAT = 5%, total adds up, tax-invoice fields | UAE VAT law and Executive Regulation Art. 59 | Red / Amber |
| Replies go to a different domain; sender domain imitates the real one | Email headers vs. history | Red |
| Wording reads like payment fraud | AI ensemble (see below) | Red / Amber |

The core idea: every invoice fraud that makes you pay must send money to an account you have never paid,
or one different from the supplier's usual account. The payment-history check catches that by
construction, however normal the email looks. The email AI is a supporting signal.

## Measured results (see `eval/`)

| What | Test | Result |
|---|---|---|
| Fraud-email AI, frozen before test collection | 114 fresh real emails from never-used sources (62 fraud, 52 legit) | Red: 31/62 caught, 0/52 false alarms. Red or amber: 53/62 (85%) caught, 2/52 (3.8%) false alarms. AUC 0.97 |
| Fraud-email AI, development | 348 real emails, leave-one-source-out | AUC 0.93; 76% caught at 9.6% false alarms |
| Invoice reading, final blind set | 120 synthetic invoices incl. 2 layouts written after the reader was frozen | PDF: every field 100% (all 120 fully correct). Photo: 80% fully correct; supplier 99%, invoice no. 96%, IBAN 95%, TRN 95%, amounts 96-98%. Zero wrong IBANs accepted silently (misreads fail the checksum and go to the user) |
| Payment-history rule | 46 real fraud emails, hand-checked (a rule, not a model test) | All 34 invoice/wire-payment frauds need a new or changed account, so the history check flags them before payment |
| Arabic email AI (multilingual model, trained on English only; thresholds fixed beforehand) | 82 real Arabic messages, mostly SMS/WhatsApp scams vs. formal payment notices (`data/bec_arabic.json`) | Amber or red: 23/41 caught, 4/41 false alarms. Red: 19/41, 1/41. AUC 0.78. The English model it replaces for Arabic gave 28/41 false alarms. Weak spot: 3/5 genuine Arabic invoice templates flagged; almost no real Arabic BEC emails are published |
| Arabic + English invoices | 60 synthetic bilingual invoices, 1 in 3 with Eastern Arabic digits (٠١٢٣) | PDF: all fields 100%. Photo with Latin digits: 36/37 fully read. Photo with Eastern digits: amounts not read, always sent to the user to type in (never silently wrong) |

Honest limits: test invoices are synthetic, and the blind set was used once as the final check after each of three reader fixes, so it is no longer untouched; photos are weaker than PDFs;
the email AI flags invoice-style frauds only at amber; government registry lookups (FTA TRN, NER, DET) are not
live because they have no public API (the FTA TRN check uses a captcha).

## Run it

```bash
sudo apt-get install tesseract-ocr tesseract-ocr-ara   # OCR for photos
pip install -r requirements.txt
uvicorn yahmi.app:app --port 8000                     # open http://localhost:8000
python3 -m pytest -q tests                              # 13 tests incl. a simulated WhatsApp conversation
python3 tests/fixtures/make_fixtures.py                 # rebuild the test invoices
```

The first run downloads the small embedding model (BAAI/bge-small-en-v1.5, about 130 MB).

## Official TRN check (FTA, needs API access)

Yahmi compares the supplier name on an invoice with the name the Federal Tax Authority has registered for its TRN, using the
FTA `validateTRNDetails_FTAX` service on the UAE API Marketplace. It needs an approved Marketplace application. Set
`YAHMI_FTA_API_KEY` (the `GW-APIKey`), `YAHMI_FTA_CLIENT_ID` and `YAHMI_FTA_CLIENT_SECRET` in the environment; never commit them.
Without them the verdict shows "not connected yet" and nothing is guessed. Results are cached for 24 hours and calls are capped at
450 a day (the service allows 500). `YAHMI_FTA_TRN_IN=body` sends the TRN as a JSON body instead of a query parameter.
Name match: 85 or more is green, 60 to 84 is amber, below 60 is red. Code: `yahmi/registry.py`; tests use a fake gateway.

### Demo without API access (simulated gateway)

Until the FTA approves access, `python3 tools/run_simulated_demo.py` starts a **simulated** FTA gateway (`tools/fake_fta_gateway.py`, four invented
companies) and Yahmi together. Yahmi's real client code talks to it, so the whole path runs: login, request, parsing, name comparison.
Try `tests/fixtures/wrong_trn.pdf` (the supplier's name with a TRN the simulated register holds for a different company: red) and
`tests/fixtures/genuine_new.pdf` (green). Any gateway other than `api.gsb.government.ae` is treated as simulated: results are prefixed
"SIMULATION:" and cite "SIMULATED registry (... NOT the Federal Tax Authority)". Never present them as FTA data. For the real service set
`YAHMI_FTA_API_KEY`, `YAHMI_FTA_CLIENT_ID` and `YAHMI_FTA_CLIENT_SECRET` and leave `YAHMI_FTA_BASE_URL` / `YAHMI_FTA_TOKEN_URL` unset.

## Sanctions screening

Yahmi screens the supplier name against the UN Security Council Consolidated List and the UAE Local Terrorist List (name check only, not proof).
Download the lists with `python3 tools/update_sanctions.py` (needs `xlrd`); without them the check stays silent. Sources, matching rules, measured
results and limits: `docs/SANCTIONS.md`.

## WhatsApp setup (Meta WhatsApp Cloud API)

1. Create a Meta developer app with the WhatsApp product and get a test phone number.
2. Set `WA_TOKEN` (access token), `WA_PHONE_ID` (phone number ID) and `WA_VERIFY_TOKEN` (any secret).
3. Expose the app publicly (for testing: `cloudflared tunnel --url http://localhost:8000` or ngrok).
4. In Meta's webhook settings, set the callback URL to `https://<your-url>/whatsapp/webhook`, enter the same
   verify token, and subscribe to `messages`.
5. On WhatsApp: forward the supplier's email text, then send the invoice. Send invoices you already paid with
   the caption `paid` to build your history.

## Layout

```
yahmi/   app.py (web + core), whatsapp.py, rules.py, extract.py, memory.py, email_checks.py, cues.py
web/       index.html                      upload page
models/    bec_final.joblib, FROZEN.txt    email AI and its frozen fingerprints
data/      uae_banks.json, real email sets (not for redistribution: third-party text, research use only)
eval/      invoice generator, evaluation scripts, result_*.json
tests/     pytest suite and fixtures (sample invoices and emails)
```

## Data and models

The real-email datasets (`data/bec_*.json`) and the trained email models (`models/*.joblib`) are not in this repository, because the emails are third-party text. They are kept privately and are available on request for research. The training and evaluation scripts are in `eval/`. `eval/synthetic_bec_train.json` contains generated example emails, not real ones.

## Privacy

Supplier IDs and IBANs are stored only as HMAC-SHA256 fingerprints with a server-side secret key
(`YAHMI_KEY`), so account numbers cannot be read or guessed back from the database. Invoices are deleted
right after reading. Flags are worded as "verify", never "this is fraud".
