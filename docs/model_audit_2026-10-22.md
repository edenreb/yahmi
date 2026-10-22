# Model audit - v2 holdout and `bec_v5` promotion

**Date:** 2026-10-22
**Scope:** `data/bec_holdout_v2.json`, `eval/result_bec_holdout_v2.json`, the promotion of `models/candidates/bec_v5.joblib` to `models/bec_final.joblib`, and the candidate `Yahmi Arraf-1` (formerly `bec_v6`).

## Finding

The v2 holdout does not comply with `docs/briefs/email_model_holdout.md`.

- The brief says new sources only: **not Enron** and nothing already in `data/bec_*.json`.
- It also requires `same_site_as_training: false` on every item.
- `data/bec_holdout_v2.json` contains **46 Enron emails in the 60-item genuine half**, all marked `same_site_as_training: true`.
- The build script calls this an "approved exception", but no such exception is written in the brief or recorded with an approval. The written rule was therefore not met.

The 46 Enron rows have no exact body overlap with the training files, so this is not exact-memorisation leakage. It is source-level contamination: the same publisher and email style appear in the holdout and in training. A paired test on v2 cannot repair that.

## Consequence

- v2 is **not** an untouched, new-source holdout.
- The v2 result cannot justify promoting `bec_v5`.
- `bec_v5` is treated as a candidate, not as validly promoted live.
- `bec_final` was restored on 2026-10-22 from `models/archive/bec_final_v4_2.joblib` (SHA-256 `7a74bab2b4e5146fe43460c2143a693c99dfaf67998df06a79214fe916c75440`); the restored file hash verified.
- The previous `models/bec_final.joblib` was byte-identical to `bec_v5` (SHA-256 `e61a47d9347773427984ff14ea6404d0b79359981f5abc8729d26a4853434c67`); it was not a valid live result under the written holdout rules.

## Enron counts

- v2 genuine half: **46 / 60 Enron**.
- v4 genuine half: **0 / 60 Enron** (GnuCash).
- v3 genuine half: **0 / 60 Enron** (templates).
- `data/bec_more3.json` genuine half: **60 / 60 Enron** (training only).
- Real-email training pool for the old live model: **173 Enron** genuine emails across `bec_realworld_more.json` (61), `bec_frozen_test.json` (33) and `bec_more2.json` (79).
- Real-email training pool for `Yahmi Arraf-1`: **233 Enron** (the 173 above plus 60 in `bec_more3.json`).

Enron is training data, not an inference-time source.

## Audit trail gap

- There is no committed pre-promotion result file. The tracked `eval/result_bec_holdout_v2.json` shows identical scores for `bec_final` and `bec_v5` because `bec_final` had already been replaced with v5 before that result was written/committed.
- The old-live comparison (amber 31/76, red 6/76, 1/60 false alarms, AUC 0.938 versus v5 amber 43/76, red 13/76, 1/60 false alarms, AUC 0.971) survives only in prose, not in the result file.
- v2 has no stored duplicate report. The build code has an internal dedupe for selected mbox/CSV rows and an exact-body Enron overlap filter, but no saved cross-source/near-duplicate report. v3 and v4 have leakage/dedupe manifests; v2 does not.
- A reconstruction from the archived old live model and `bec_v5` gives: fraud amber discordant **13 v5-only vs 1 old-only** (exact McNemar p = 0.0018); fraud red **8 vs 1** (p = 0.0391); genuine false alarms **1 vs 1**, no discordant pairs (p = 1.0). This supports the observed difference on v2, not the validity of the promotion.

## Required correction

1. ~~Hold the v5 promotion and restore the old live model locally.~~ Done 2026-10-22; restored hash verified as `7a74...`.
2. Keep `bec_v5` and `Yahmi Arraf-1` as candidates.
3. Do not use v2, v3, v4 or the spent general-abuse v5 for model selection or promotion again.
4. Build a new, compliant holdout with new sources and no Enron; store a manifest with source URLs, licences, duplicate/leakage checks, and `same_site_as_training: false`; freeze its SHA before scoring. (General-abuse v5 done 2026-10-22; the invoice/bank-change hard-case set is still open.)
5. Score the three models on that one set, using a pre-registered paired decision rule. If both candidates beat the live model, run the pre-registered candidate-vs-candidate comparison before any promotion. (Done on v5; no promotion. Repeat only on the hard-case set.)
6. Keep model binaries, private email text and result files out of Git as required by `.gitignore`.

The reader/OCR changes are independent of this audit and must not be presented as model validation.

## Update: first compliant holdout run

`data/bec_holdout_v5.json` (SHA-256 `0ba2f4502e9cb7fa3085ab3cdeac0e519abe36ea3b922d816bff9619a6c58363`) was built from two new sources, checked for Enron/same-site/near-duplicate leakage (refs 19,437; exact 0; max cosine 0.6671; 0 at >=0.70; source keys disjoint) and frozen before scoring. It has 209 real `cw-l/email-corpus` spam/scam/phishing items and 209 real Apache OFBiz user-list genuine messages.

One-shot scoring with `eval/eval_holdout_v5.py` -> `eval/result_bec_holdout_v5.json`:

- live `bec_final`: amber 133/209, red 10/209, false alarms 7/209 amber and 0/209 red, AUC 0.923.
- `bec_v5`: amber 135/209, red 13/209, false alarms 17/209 amber and 1/209 red, AUC 0.907.
- `Yahmi Arraf-1`: amber 146/209, red 10/209, false alarms 20/209 amber and 1/209 red, AUC 0.902.

Neither candidate passes the pre-registered mechanical gate because both raise amber false alarms (McNemar p=0.0127 for `bec_v5`, p=0.0005 for Arraf). No promotion. This set is **general abuse vs technical business-support traffic**, not BEC or invoice email, so it does not close the hard-case requirement; v5 is spent and must not be reused.
