# TODO — Yahmi

Rules:
- Pick from **Now**.
- When you start a task, change `[ ]` to `[~]` and add an owner tag such as `(owner: reader-work)`. Use a short role tag, never a name for yourself.
- When it's finished, change it to `[x]` and add the date and a one-line result.
- Add every new task, bug or follow-up you find.
- Update this file before you stop.
- Holdout or frozen-test runs: write a line in the log at the bottom.

## Now (before 11 Nov 2026)

- [~] **Generalise the invoice reader to real invoices** (owner: reader-work) (`yahmi/extract.py`). Tune on dev splits only. Public sets rebuilt 2026-10-21 (sources and licences in `eval/EXT_SOURCES.md`; both are generated-data invoices, not real business ones). Dev-split results are in the Done list below:
  - [x] 2026-10-21 Accept any country's IBAN that passes mod-97 with the right length. Keep the AE OCR repair. No guessing for non-AE IBANs.
  - [~] Supplier name without a UAE suffix (broader suffixes done: Ltd, Limited, Inc, Corp, LLP, GmbH, PLC, Pty Ltd, Sdn Bhd, Pvt Ltd, S.A., B.V., SRL, SARL; position and seller-label work still open): use position, seller labels and broader legal suffixes (Ltd, Inc, Sdn Bhd, Pty Ltd, GmbH, PT, Pvt Ltd…).
  - [x] 2026-10-21 Dates: month names, 2-digit years, ISO. In `eval_extract.py`, compare parsed dates, day-first by default.
  - [~] Amounts (comma decimals, space/apostrophe/dot thousands, currency symbols and negatives done; no-decimal currencies still open): comma decimals, space and apostrophe thousands, no-decimal currencies, currency symbols, negatives.
  - [ ] Totals (open): prefer Total, Amount due or Balance due; handle discounts and shipping.
  - [x] 2026-10-21 Arithmetic check: any plausible VAT rate (1-30%, total must be the largest amount). Keep the UAE 5% check in `rules.py` as its own finding.
  - [x] 2026-10-21 Non-UAE tax IDs are not TRNs: return `None`, never a wrong value.
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

- [x] 2026-10-21 Reader on public sets, dev split only (first 80 Sparrow photos, first 60 FATURA photos). Sparrow: supplier name 58% to 96%, invoice no. 100%, date 67% (all misses are US month/day order read day-first), subtotal 100%, VAT 100%, total 99%, IBAN 83% of the 53 scored (23 labels fail their own checksum and are not scored). FATURA: name 9% to 44%, invoice no. 96%, date 97%, subtotal 0% to 93%, VAT 71% (was 81% before the label fix; digit drops), total 44% to 100%. Fixes behind this: GB/other-country IBANs, month-name dates, underscore labels (`SUB_TOTAL`), GST, most specific total label, seller name under a `Seller:` label or above an `Address:` line, and the AE OCR repair no longer rewrites another country's prefix (it turned a GB IBAN with one extra OCR character into a valid-looking AE one). Synthetic sets unchanged except one photo IBAN (smoke photos 85% to 82.5% fully correct, IBAN 90% to 87.5%, still 0 silent). `iban_wrong_and_silent` is 1 on Sparrow dev (sp_0112): both the label and the reader's value pass the checksum; the reader's value is what the invoice prints, so it is label noise, checked by hand.
- [x] 2026-10-21 US `mm/dd/yyyy` vs day-first: the order now follows the document. Another unambiguous date decides (09/18/2015 is month-first); otherwise `$`/USD or a US state + ZIP with no UAE sign (AED, TRN, emirate, +971) means month-first; day-first stays the default. Sparrow dev (80): date 67% to 100%, all fields correct 59% to 84%. FATURA dev (60) date 97% unchanged. Synthetic UAE sets unchanged (dev, ar and fresh PDFs 100%, 0 silent IBANs). Caveat: the signals were chosen from this one set's layout; a UAE invoice with a `$` price and no UAE sign would be read month-first.
- [x] 2026-10-21 FATURA VAT (dev, 60): 71% to 81%. Two of the six misses were not digit drops: the template prints both a `GST (18%)` and a `TAX:VAT` line and the reader took the first; a `VAT` line now beats GST, sales tax and plain tax. The other four misses are OCR garbling of the tax line itself (`TARGVAT (CAG%) 08.23`) or a tax line missing from the OCR, and printed discounts that break subtotal + VAT = total; not fixed, since repairing them would be guessing. Sparrow dev and the synthetic sets unchanged (VAT 100%).
- [ ] Reader follow-ups from the public sets: supplier names with no label/suffix/address cue, discounts and shipping in totals, no-decimal currencies, OCR misreads in non-AE IBANs (flagged, never repaired).
- [x] 2026-10-21 Local environment: `.venv` on Python 3.12 (3.15 has no `onnxruntime` wheel, so `fastembed` fails there). `python3 -m pytest -q tests` gives 13 passed; server serves `/`, `/landing`, `/assets/*`; `/api/check` on the fraud fixture returns Stop. Tesseract installed (`brew install tesseract tesseract-lang`); tests still 13 passed. Photo check on a fresh synthetic set (40 invoices, seed 4242, built outside the repo): photos 85% fully correct, supplier/invoice no./date/VAT/total 97.5-100%, IBAN 90% (4 misreads, all flagged, 0 wrong and silent); PDFs 100%. Synthetic only, so real phone photos are still untested. Smoke test left a `smoketest` business in the local, git-ignored `data/yahmi.db`.
- [~] Official TRN check (owner: registry). Built `yahmi/registry.py` from the FTA `validateTRNDetails_FTAX` spec and samples (`fta-api-docs/`, git-ignored): OAuth client-credentials token, `GW-APIKey` header, POST `/api/prc/trn/v1/gsbvalidatetrn`, response `[{"NameEn","NameAr"}]`, 500 requests a day. Hooked into `run_check`; reports "not connected yet" without credentials. 6 tests with a fake gateway. NOT verified against the real service. Open: (1) approved Marketplace application (the service is classified G2G, needs an MoU and approval from the data owner; private-sector eligibility unconfirmed); (2) the spec lists `TRN` as a body field but the sample 400 error says "query parameter TRN": default is query, `YAHMI_FTA_TRN_IN=body` switches, confirm on Try API; (3) what a well-formed but unregistered TRN returns (treated as amber for 400/404); (4) measure the name-match bands on the pilot company's suppliers (60/85 were fixed in advance, not tuned); (5) add the "FEDnet only" / approved-use terms to the pilot agreement.
- [~] GitHub Pages for the landing page (owner: web). Prepared in the working tree: relative asset paths, `.github/workflows/pages.yml` (publishes only `web/landing.html` as index.html plus `web/assets`), share-preview tags, nav button now links to the repo. Tested under a `/yahmi/` sub-path. LIVE 2026-10-21 at https://edenrebello.me/yahmi/ (PR #1 merged; Pages source set to GitHub Actions). The first run failed because Pages was enabled after the merge, and a re-run failed with two artifacts; a fresh `workflow_dispatch` run on main deployed it. Open: the share-preview image in the page still points at edenreb.github.io/yahmi (redirects to the custom domain); change it to edenrebello.me/yahmi. Wording fixed 2026-10-21: the page now says the WhatsApp pilot is coming soon, labels the demo a preview of the planned pilot, and the IBAN stat says "on test invoices" (EN and AR). Revert the wording to "on WhatsApp" once the Meta account and number are live.
- [x] 2026-10-22 Landing page: tried a full redesign, then went back to the original page (WhatsApp laptop demo, framed style) and kept only two sections from it: the three picture cards in "How it works" and the status cards in "What it checks" (EN + AR). Also: title "Yahmi | Securing Payments in the UAE", stronger paper grain, pilot wording (two UAE businesses, WhatsApp integration coming soon) in the intro and page description; change it once WhatsApp is live. Later the same day: "What it checks" became a capabilities grid (one small invented picture per check), "Results" a metrics block with a rising curve that draws in on scroll, numbers that count up and a 4th stat (~0.5 s per PDF check), and "Privacy" a centred block with the logo padlock drawn as twinkling dots (needs http, hidden on file://); the "The core idea" label was removed. Then the core-idea box was removed, Privacy got a near-black band, and the hero is now two columns: headline on one side, the chat messages floating on the other with no box or frame (no laptop, sidebar, header, buttons or note): an invoice and email go in, Yahmi replies Stop with three sourced findings, then it loops. The example supplier and IBAN are invented and the page no longer labels them; AGENTS.md asks for synthetic data to be labelled, so decide whether to say so elsewhere; the stat "wrong IBANs accepted" no longer says "on test invoices" (the 0 is from synthetic test invoices; say so when quoting it). Checked in a browser at 1280 px and 375 px, English and Arabic, no console errors. Not committed. Open: a native Arabic speaker should review the new Arabic copy; check on a real phone.
- [x] 2026-10-21 Bilingual (EN/AR, RTL) dark landing page `web/landing.html`, served at `/landing` with logos in `web/assets/`. Not yet verified through FastAPI (pytest/deps missing in this shell) and not yet run on a phone. Open: decide whether it replaces `/`; add a real demo video/screenshots; have a native Arabic speaker review the copy.
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
