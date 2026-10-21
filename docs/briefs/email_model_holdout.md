# Brief: untouched test for the email model (and the decision on `bec_v5`)

**Owner:** model work (second team member). **Target:** test set frozen by 30 Oct, one evaluation by 3 Nov, decision by 4 Nov. The pitch is 11 Nov.

## Why
- Live model: `models/bec_final.joblib`, frozen 19 Oct. Frozen test (114 real emails): 85% of fraud caught at amber or red, 2 of 52 genuine flagged.
- Candidate: `models/candidates/bec_v5.joblib`, trained on the original 348 plus the 114 frozen-test emails plus 160 new ones. On a fair comparison across 158 new emails (`eval/result_more2_before_after.json`) it was better on every count (AUC 0.874 to 0.908; fraud caught at amber 48 to 54 of 81 with genuine flagged 9 to 7 of 77; at red 24 to 34 caught, 4 to 2 flagged).
- Problem: v5 was trained on the old frozen test, and some sources also sit in its training data, so those numbers are optimistic and we cannot quote them as test results. We need a test neither model has seen.

## Definition of done
1. A new file `data/bec_holdout_v2.json` (git-ignored; it is third-party text) with at least 60 fraud and 60 genuine emails from **new sources**, same schema as `data/bec_frozen_test.json`: `label` (`fraud`/`legit`), `lang`, `subject`, `body`, `source_title`, `source_url`, `notes`, `attack_type`, `same_site_as_training` (false).
2. Its SHA-256 recorded in `models/FROZEN.txt` **before any model is run on it**.
3. One evaluation script, `eval/eval_holdout_v2.py`, that scores `bec_final` and `bec_v5` on it at the fixed thresholds (amber 0.62, red 0.80): AUC, fraud caught and genuine flagged at amber and at red, broken down by `attack_type`, with Wilson 95% intervals. Run once, result saved to `eval/result_holdout_v2.json`.
4. The decision applied exactly as written below, logged in `TODO.md`, and (only if v5 wins) a new freeze entry and a refreshed results table in the README.
5. A PR with the script, the result file and the doc updates. The data and models are never committed.

## Decision rule (written now, before the data exists)
Promote `bec_v5` only if, on the holdout at the fixed thresholds, it catches at least as many fraud emails at amber **and** flags no more genuine emails at amber **and** flags no more genuine emails at red than `bec_final`. Anything else keeps `bec_final` live. Do not change this rule, the thresholds or the models after seeing the result. If the sets are small and the two models are within each other's intervals, say so and keep the live one.

## Rules (from AGENTS.md; non-negotiable)
- Never tune, pick thresholds or choose features on the holdout. It is used once, then it is spent: afterwards it may be added to training for a later model, but it is no longer a test.
- New sources only: not Abnormal, UTHSCSA, Stanford, Enron or anything already in `data/bec_*.json`. Check `source_url` against those files, and check for near-duplicates (same campaign quoted on two sites) before freezing.
- Text only. Strip links and attachments, never keep raw phishing kits or live samples. Quote, do not store HTML. Replace personal data with `[Recipient name]`-style placeholders as the existing files do.
- Record `source_url` and the licence or terms for every item. Public pages only; be gentle on servers. Never invent an email and call it real; synthetic ones are labelled `synthetic` and are not allowed in the holdout.
- Pilot businesses' emails are not part of this set (different consent, different purpose).

## What to collect (balance matters more than volume)
- **Fraud:** invoice and bank-detail-change emails first (this is where both models are weakest, mostly stuck at amber), then CEO/wire, payroll, gift card, vendor impersonation. A few Arabic ones if you can find real ones.
- **Genuine:** invoice emails, remittance advices, bank-change notices from real suppliers (these are the hard negatives), ordinary business mail. Aim for equal numbers of each label.
- Candidate sources noted so far (unbuilt): UChicago security posts, the UMN phishing blog, Ironscales quotes, bank-change letter templates (NAB, Beyond Bank, template sites), Bonsai and Zoom invoice templates, CEAS-08 and TREC-06 invoice and bank emails. Check each one's terms before using it.

## Setup
Python 3.12 (3.15 has no `onnxruntime` wheel), `pip install -r requirements.txt`, `brew install tesseract tesseract-lang`, then `python3 -m pytest -q tests`. Get the private data and model files (`data/bec_*.json`, `models/*.joblib`, `models/candidates/`) from the other team member over a private channel, never the public repo. Never share `data/.yahmi_key`; make your own.

## How we work
- Branch per task, PR to `main`, nothing pushed straight to `main`. Put your name tag on the item in `TODO.md` when you start it and tick it when done; add every follow-up you find.
- Read `AGENTS.md` and `TODO.md` first. Report numbers as measured, with their caveats; never write "100%" from synthetic data.
- Questions about what counts as a source or a duplicate: ask before freezing, not after. Once the file is frozen it cannot be edited.
