# Holdout data source review for v4b/v6

**Date:** 2026-10-25 (final access checks 2026-10-26)
**Scope:** verify the supplied data leads and look for a real, source-disjoint English invoice/BEC plus genuine supplier/accounts-payable holdout. This is a data-source review, not a model score. No holdout was built, frozen or scored.

## Bottom line

No public or gated-known dataset meets the brief. There is no accessible set with at least 200 real invoice/wire/bank-account-change fraud emails and 200 verified genuine supplier/accounts-payable emails, with a licence that permits this use and enough metadata to prove source-disjointness.

The practical routes are:

1. Pilot-partner data (preferred).
2. Case-derived old/new account facts for the payment-history rule (v4b-lite), kept separate from email-model accuracy.
3. Formal access requests to BEC-Guard, COEP and APWG, with the caveat that the first two are private and APWG has not confirmed invoice/BEC coverage.

`bec_holdout_v2`-`v5` are spent and must not be reused. Synthetic and machine-translated data must not be counted as real-email accuracy.

## Criteria

- Real emails with a raw body and a label.
- Fraud side: invoice, wire, remittance, payroll or bank-account-change BEC; enough cases carrying an IBAN/account to test the payment-history complement.
- Genuine side: real supplier invoices, remittances or accounts-payable correspondence.
- Source-disjoint from training, v2-v5 and each other; no Enron; no synthetic or machine-translated items; no near-duplicates under the strict BGE gate.
- Minimum 200 fraud + 200 genuine; preferred 300+300.
- Licence permits research/evaluation, and commercial use if the pilot requires it.

## Verified leads

### BEC-Guard: private, not accessible

- Paper: "High Precision Detection of Business Email Compromise", USENIX Security 2019, Cidon, Gavish, Bleier, Korshun, Schweighauser, Tsitkin. https://www.usenix.org/system/files/sec19-cidon.pdf
- Initial training data: a year of historical email from 1,500 paying customer organizations, 2 million mailboxes and 2.5 billion emails; over 7,000 labelled BEC attacks.
- Evaluation data: 200 million emails from several hundred organizations and more than 4,000 attacks; 98.2% precision; combined false-positive rate one in 5.3 million emails.
- The sensitive commercial dataset was exposed only to the five researchers who developed BEC-Guard under strict access controls. Customers gave legal consent through Office 365 APIs and could revoke access.
- No public download or request form was found. The data belongs to Barracuda Networks; the corresponding academic contact is Asaf Cidon (`ac4665@columbia.edu`, public Columbia page).
- Verdict: private/commercial. It proves real BEC data exists, but it is not an obtainable holdout.

### COEP lateral spear phishing: private

- Paper: Bhadane & Mane, "Detecting lateral spear phishing attacks in organisations", IET Information Security 13(2):133-140, 2019. https://doi.org/10.1049/iet-ifs.2018.5090
- Reported real data: emails from 40 COEP volunteers, 113,726 messages total, 19,087 unique, 12,064 intra-domain; 27 attack instances corresponding to 323 lateral spear-phishing emails.
- The article is free to read, but no dataset landing page, attachment or download was found; the licence for the email data is not stated. A request would go to the corresponding author/COEP (Sunil B. Mane's public ORCID lists `sunilbmane.comp@coeptech.ac.in`).
- Verdict: private; lateral internal spear phishing, not invoice/BEC, and no supplier invoices or accounts-payable genuine side. Even with access it would not cover the v4b hard cases.

### Phishing Pot: public but unsuitable

- Repository: https://github.com/rf-peixoto/phishing_pot, commit `2933c0341b1248678c1e246b36d352add2edf0f1` (pushed 2026-10-10; updated 2026-10-24).
- 12,271 `.eml` files; 1,545,995,708 bytes of `.eml` content (1.47 GiB). Real phishing captured through the maintainer's own long-exposed or controlled addresses; the card says it is not third-party mailbox access.
- Unlabelled and no genuine class.
- Licence: the dataset card and top-level `LICENSE` are CC BY-NC 4.0. Commercial use, including commercial AI/ML training or evaluation, is prohibited without separate permission. The GitHub API reports `NOASSERTION`, but the licence text and card agree on CC BY-NC 4.0.
- A random 300-email sample (seed 42) contained 8 invoice-keyword, 53 payment-keyword, 14 bank-change-keyword (mostly false positives), 1 wire-keyword and 15 credential-keyword matches after a broad keyword pass. Manual review found no confirmed supplier-invoice or bank-account-change BEC; the sample was mostly consumer, brand, credential and subscription phishing. Exact prevalence is unknown because the corpus is unlabelled and the sample is small.
- Verdict: possible fraud examples or a synthetic-free stress test only with permission; not a holdout because it has no genuine side, no labels and a non-commercial licence.

### Sting9: no data currently exposed

- Site: https://sting9.org/dataset. It claims a CC0 licence, a full PostgreSQL dump and an API.
- GitHub `sting9-research/dataset` (commit `22f0f0f6d84ceefc2fa6d42510591f0f916d18e8`) contains only `LICENSE.md`, has no releases, and the API endpoints tried (`/v1/submissions?limit=1`, `/v1/statistics`, `/v1/docs`, `/docs`, `/openapi.json`, root) return 404. `https://github.com/sting9/dataset` also returns 404.
- The repository licence is ODC-BY-NC and forbids commercial AI training, which conflicts with the site's CC0 claim. Contact listed on the site: `research@sting9.org`.
- Verdict: unusable as of 2026-10-26.

### SpaPhish: public, wrong language and task

- Mendeley: https://data.mendeley.com/datasets/hz2d6gz7pc/5, DOI `10.17632/hz2d6gz7pc.5`, version 5 published 2026-05-12.
- 1,395 Spanish emails (664 legitimate, 731 phishing), 47 variables, subject/body/date; 1,371 parseable dates spanning July 2014 to October 2025; CC BY 4.0.
- Not English and not invoice/BEC; no genuine supplier/accounts-payable set.
- Verdict: separate Spanish track only. Do not machine-translate it into the English holdout.

### APWG eCX: gated

- https://apwg.org/cybercrime-researcher/ describes the Cybercrime Researcher Data Grant Program: accepted investigators get full read access to eCX. Requests go to `membership@apwg.org` with a research proposal.
- Gated phishing data; invoice/BEC and genuine accounts-payable coverage are not confirmed, and there is no public download.
- Verdict: possible additional fraud source if accepted, but not sufficient alone. No request has been sent.

## Additional sources checked and rejected

- BEC-1/BEC-2 (`r-dube/bec`, commit `b6cc4f0439694ce175fa688b7faf361eba30d359`, AGPL-3.0): LLM-generated synthetic data, 20 and 279 rows. The paper "Building a business email compromise research dataset with large language models" confirms the generation method; the repository also contains Enron material. Not real.
- Kaggle `yoadjei/adversarial-bec-email-dataset`: 4,211 synthetic Gemini 2.5 Flash emails. Not real.
- Zenodo 13474746: 2,000 phishing-validation emails, mixed real-world and artificially generated, about 2.0 GB; not invoice/BEC and mixed provenance. Not usable.
- Kaggle `llabhishekll/fraud-email-dataset`: generic fraudulent-email corpus, body-only and Nigerian-fraud style; no genuine accounts-payable class and not invoice/BEC. Not usable.
- Avocado LDC2015T03: real business email from 279 accounts of a defunct IT company; LDC membership/paid, unlabelled for fraud and not invoice-specific. Not usable.
- `invictus-ir/o365_dataset` (CC-BY-4.0): Office 365 Unified Audit Logs, no raw email bodies. Not usable for the text model.
- Email4S (18,650 general phishing emails), MeAJOR, FERB and aggregators: general phishing, no invoice/accounts-payable coverage and old or mixed provenance. Not usable.
- DataPhish/PhishingSpamDataSet (arXiv 2511.21448): project site returns 404; manually collected real emails plus LLM rephrasing, no accessible dataset or clear licence. Not usable.
- Procurement invoice tables (Kaggle and similar): structured tabular invoices, not email. Wrong task.
- Synthetic UAE invoice packs: invoice images, not email. Wrong task.

## What to do next

1. Ask the pilot partner for redacted genuine supplier invoices/remittances and, if permitted, confirmed fraud examples with old/new bank details; record written permission, source dates and redaction rules.
2. Build a provenance manifest for public court/regulator cases (Mobius/Inoteq, Terna/Revolut, Studco, Mississippi Silicon, Singapore Police) with the exact URL, paragraph, evidence type, old/new account visibility, duplicate appeals, licence/permission status and label confidence. Use this for the payment-history rule only; never call it email accuracy.
3. Send the APWG request and short access requests to the BEC-Guard and COEP authors, asking specifically whether any invoice/payment-change subset can be shared under a research agreement. Record volume, fields, permission and whether genuine accounts-payable messages are included.
4. Do not build v4b from Phishing Pot, SpaPhish or synthetic sources, and do not reuse v2-v5.
5. Freeze any future set through `eval/validate_holdout.py` with the strict BGE gate before scoring.

## Reproducibility notes

- Phishing Pot sample: 300 random `.eml` files from commit `2933c03`, seed 42. The sample JSON and script are outside the repo at `C:\Users\Gabriel\AppData\Local\Temp\opencode\phishing_pot_sample.json` and `phishing_pot_sample.py`. The keyword counts and manual review above describe this sample only.
- Phishing Pot size check: 12,271 `.eml` files, 1,545,995,708 total `.eml` bytes; median 23,714 bytes; minimum 0; maximum 7,717,733.
- Access checks used the public paper/DOI/Crossref pages, the public GitHub API, the Sting9 site, the Mendeley record and the APWG page. No private dataset was downloaded into the repository.
- No model was trained or scored for this review.
