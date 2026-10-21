# Public invoice sets used for evaluation

The data itself is git-ignored (`eval/ext_*/`). Rebuild with the scripts below. Both sets are published datasets of
invoices filled with generated (fake) names, addresses and amounts, so they measure layout generalisation, not
performance on real business invoices.

## ext_sparrow

- **Source:** Hugging Face dataset `katanaml-org/invoices-donut-data-v1` (500 annotated invoice images), https://huggingface.co/datasets/katanaml-org/invoices-donut-data-v1
- **Licence:** MIT (dataset card).
- **Original data credited by that dataset:** Kozłowski, M., Weichbroth, P. (2021), "Samples of electronic invoices", Mendeley Data, V2, https://doi.org/10.17632/tnj49gpmtz.2 (CC BY 4.0; synthetic invoices).
- **Build:** put the three `data/*.parquet` files in `eval/ext_sparrow/raw/`, `pip install pyarrow`, run `python3 eval/build_ext_sparrow.py`.
- **Labels:** from the dataset's own annotation. `supplier_name` is the seller string cut before the street address (heuristic). `supplier_trn` is null (US tax IDs are not TRNs). US `mm/dd/yyyy` dates are converted to ISO, so day-first reading of an ambiguous date counts as a miss. Invoices whose label has no IBAN are marked `iban_unannotated`: the image does print one.
- **Known label noise:** some IBAN labels fail the ISO checksum (annotation typos); `eval_extract.py` does not score those and reports how many.
- **Split:** hash of the file name, about 70% dev (359) and 30% holdout (142).

## ext_fatura

- **Source:** FATURA, Zenodo record 10371464 (`FATURA2.zip`, 690.7 MB), https://zenodo.org/records/10371464. Paper: Limam, Dhiaf, Kessentini, "FATURA: A Multi-Layout Invoice Image Dataset for Document Analysis and Understanding", https://arxiv.org/abs/2311.11856
- **Licence:** CC BY 4.0 (Zenodo record).
- **Build:** unzip into `eval/ext_fatura/raw/`, `pip install python-dateutil`, run `python3 eval/build_ext_fatura.py`. It takes 12 images from each of the 50 layouts (600) and interleaves the layouts.
- **Labels:** from the printed-text annotation of each field (`SELLER_NAME`, `NUMBER`, `DATE`, `SUB_TOTAL`, `TAX`, `TOTAL`). Null when the field is missing or an all-numeric date has an ambiguous day/month order. FATURA has no IBAN or TRN labels. Some totals include a printed discount, so subtotal + VAT does not always equal total.
- **Split:** hash of the file name, about 70% dev (445) and 30% holdout (155).

## Not rebuilt

`ext_ipp`, `ext_sroie` and `ext_cord` from earlier work are not on this machine and the repo does not record where they came from. SROIE and CORD are shop receipts, not invoices. They were not re-downloaded; add them here with a source URL and licence if they are rebuilt.

## Running

```
cd eval
python3 -W ignore eval_extract.py ext_sparrow jpg 80      # dev split, first 80
python3 -W ignore eval_extract.py ext_fatura jpg 60       # dev split, first 60 (layouts interleaved)
python3 -W ignore eval_extract.py ext_sparrow jpg 142 holdout   # holdout: run once at the end and log it in TODO.md
```
