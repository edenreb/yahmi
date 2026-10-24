"""The pilot measurement script on the invented fixture invoices (never real data)."""
import os
import shutil
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "eval"))
import pilot_report  # noqa: E402

FX = os.path.join(os.path.dirname(__file__), "fixtures")


def test_replay_counts_first_payment_once_and_catches_the_changed_account(tmp_path):
    biz = tmp_path / "biz_one"
    biz.mkdir()
    for i, f in enumerate(["past/past_1.pdf", "past/past_2.pdf", "past/past_3.pdf", "genuine_new.pdf", "fraud_new.pdf"]):
        shutil.copy(os.path.join(FX, f), biz / f"{i}_{os.path.basename(f)}")   # same dates for the last two: file order breaks the tie
    labels = tmp_path / "labels.csv"
    labels.write_text("file,supplier_name,supplier_trn,iban,invoice_number,invoice_date,subtotal,vat,total\n"
                      "3_genuine_new.pdf,Falcon Building Materials LLC,100384920571003,,INV-2391,14/10/2026,,,\n")
    rep = pilot_report.run(str(tmp_path), str(labels))
    assert rep["invoices"] == 5 and rep["businesses"] == {"biz_one": 5}
    assert rep["new_accounts"] == 2                                   # the first good account and the changed one
    per = rep["per_100"]
    assert per["first_payment_new_account:amber"] == 20.0            # 1 of 5: only the very first invoice
    assert per["bank_details_changed:red"] == 20.0                   # the fraud copy: known supplier, different account
    assert rep["verdicts"]["stop"] == 1
    assert rep["field_accuracy"]["supplier_trn"] == {"correct": 1, "labelled": 1, "rate": 1.0}
    assert rep["field_accuracy"]["invoice_date"]["rate"] == 1.0


def test_console_output_is_masked(tmp_path, capsys):
    biz = tmp_path / "b"
    biz.mkdir()
    shutil.copy(os.path.join(FX, "genuine_new.pdf"), biz / "g.pdf")
    pilot_report.main([str(tmp_path), "--out", str(tmp_path / "out" / "r.json")])
    out = capsys.readouterr().out
    assert "AE" not in out and "Falcon" not in out and "100384920571003" not in out
    assert (tmp_path / "out" / "r.json").exists()


def test_only_and_skip_filter_files(tmp_path):
    biz = tmp_path / "b"
    biz.mkdir()
    for n in ("a.pdf", "b.pdf", "c.pdf"):
        shutil.copy(os.path.join(FX, "genuine_new.pdf"), biz / n)
    split = {"b/a.pdf": "dev", "b/b.pdf": "holdout", "b/c.pdf": "dev"}
    assert pilot_report.run(str(tmp_path), split=split, only="dev")["invoices"] == 2
    assert pilot_report.run(str(tmp_path), split=split, only="dev", skip=("c.pdf",))["invoices"] == 1
    assert pilot_report.run(str(tmp_path))["invoices"] == 3

