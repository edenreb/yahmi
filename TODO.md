# TODO — Yahmi

Rules:
- Pick from **Now**.
- When you start a task, change `[ ]` to `[~]` and add an owner tag such as `(owner: reader-work)`. Use a short role tag, never a name for yourself.
- When it's finished, change it to `[x]` and add the date and a one-line result.
- Add every new task, bug or follow-up you find.
- Update this file before you stop.
- Holdout or frozen-test runs: write a line in the log at the bottom.

## Now (before 11 Nov 2026)

- [ ] **Generalise the invoice reader to real invoices** (`yahmi/extract.py`). Tune on dev splits only:
  - [ ] Accept any country's IBAN that passes mod-97 with the right length. Keep the AE OCR repair. No guessing for non-AE IBANs.
  - [ ] Supplier name without a UAE suffix: use position, seller labels and broader legal suffixes (Ltd, Inc, Sdn Bhd, Pty Ltd, GmbH, PT, Pvt Ltd…).
  - [ ] Dates: month names, 2-digit years, ISO. In `eval_extract.py`, compare parsed dates, day-first by default.
  - [ ] Amounts: comma decimals, space and apostrophe thousands, no-decimal currencies, currency symbols, negatives.
  - [ ] Totals: prefer Total, Amount due or Balance due; handle discounts and shipping.
  - [ ] Arithmetic check: any plausible VAT rate. Keep the UAE 5% check in `rules.py` as its own finding.
  - [ ] Non-UAE tax IDs are not TRNs: return `None`, never a wrong value.
  - [ ] Afterwards, keep synthetic sets at current scores, keep all tests passing and keep `iban_wrong_and_silent` at 0. Run the holdouts once and log them.
- [x] 2026-10-20 Fair before/after on the 158 new emails (`eval/result_more2_before_after.json`). The candidate `bec_v5` is better on every count: amber caught 48 → 54 of 81 and false alarms 9 → 7 of 77; red caught 24 → 34 and false alarms 4 → 2; AUC 0.874 → 0.908. Caveat: some sources (Abnormal, UTHSCSA, Stanford) also appear in training, so absolute numbers are optimistic; the comparison between models is fair.
- [ ] **Decide whether to make `bec_v5` the live model.** It needs an untouched test from NEW sources first (next task). The frozen-test numbers (85% caught, 2/52 false alarms) belong to the current live model. If v5 goes live, re-measure before quoting any numbers.
- [ ] **Build an untouched email holdout from NEW sources** (not Abnormal, UTHSCSA, Stanford or Enron, which are already in training).
  - Use text only: strip links and attachments, and never handle raw phishing kits or live samples.
  - Candidate sources found but not yet built: UChicago security posts, UMN phishing blog, Ironscales quotes, bank-change letter templates (NAB, Beyond Bank, template sites), Bonsai/Zoom invoice templates, CEAS-08/TREC-06 invoice and bank emails.
- [ ] **Real UAE/GCC invoices** into `data/real_invoices_uae/`. Collection paused at a usage limit; the folder is currently empty.
  - Hand-label every field, use null where a field isn't printed, and split dev/holdout.
- [ ] **Waiting on the team:** pilot partner's redacted invoices and emails; pilot letter; Meta WhatsApp developer account.

## Next (after real data arrives)

- [ ] Run the pilot partner's invoices through the reader. Measure per-field accuracy, the first-payment amber rate, and false alarms per 100 invoices.
- [ ] Measure photo OCR on real phone photos. Consider better Tesseract models (tessdata_best is an LFS file and not reachable from the workspace) or another OCR engine.
- [ ] Arabic email AI: find real Arabic invoice and bank-change emails, including hard genuine ones. Retrain the multilingual model on mixed data and evaluate with source-grouped CV.
- [ ] Invoice-type fraud emails reach only amber: add hard positives and hard negatives, then re-check the red rate on a fresh test.

## Later (pilot and product)

- [ ] Official API access: FTA TRN check, National Economic Register (licence status, official phone for call-backs), CBUAE bank codes.
- [ ] Production hardening: Postgres, authentication, rate limits, key management (partner-held HMAC key), audit log, data-retention job.
- [ ] Supplier self-confirmation flow for genuine bank changes.
- [ ] Network poisoning guard: require more than one business before a network flag, and review repeated reporters.
- [ ] PDPL review with a lawyer. Note that DIFC and ADGM have their own data laws.

## Done

- [x] 2026-10-19 Email AI rebuilt and frozen. Frozen test: 85% caught, 2/52 false alarms at amber; 0/52 false alarms at red.
- [x] 2026-10-20 Arabic: bilingual invoices (PDF 100%), Eastern-digit normalisation, Arabic OCR fallback, multilingual email model, Arabic WhatsApp replies.
- [x] 2026-10-20 Supplier-name extraction: synthetic blind set PDF 55% → 100%, photo 54% → 99%.
- [x] 2026-10-20 Invoice-number extraction: synthetic blind set PDF 78% → 100%, photo 72% → 96%.
- [x] 2026-10-20 Collected public invoice sets (`eval/ext_*`, about 1,800 docs, CC BY / MIT) and 160 new real emails (`data/bec_more2.json`).
- [x] 2026-10-20 Renamed the project to Yahmi; added AGENTS.md and TODO.md.

## Holdout / frozen-test log

- 2026-10-19 `data/bec_frozen_test.json`: email model scored once after freezing.
- 2026-10-20 `eval/inv_blind2`: used as the final check after the Arabic, supplier-name and invoice-number fixes (3 runs). No longer untouched.
- 2026-10-20 `eval/inv_ar`: built and scored (not a holdout).
