from decimal import Decimal as D

from yahmi.rules import Invoice, check_iban, check_trn, check_vat, iban_valid


def levels(fs):
    return [f.level for f in fs]


def test_iban_checksum():
    assert iban_valid("AE070331234567890123456")
    assert not iban_valid("AE070331234567890123457")


def test_iban_bank_and_typos():
    assert levels(check_iban("AE07 0331 2345 6789 0123 456")) == ["green", "green"]
    assert levels(check_iban("AE070331234567890123457")) == ["red"]
    assert levels(check_iban("GB82WEST12345698765432")) == ["amber"]
    assert levels(check_iban(None)) == ["amber"]


def test_legacy_bank_code_is_amber():
    # 027 = First Gulf Bank, merged into FAB; build a valid IBAN on that code
    bban = "027" + "0" * 16
    chk = 98 - int(bban + "101400") % 97
    fs = check_iban(f"AE{chk:02d}{bban}")
    assert fs[0].level == "green" and fs[1].level == "amber"


def test_trn_and_vat():
    assert levels(check_trn("100123456789012")) == ["green"]
    assert levels(check_trn("12345")) == ["red"]
    assert levels(check_vat(Invoice(subtotal=D("100"), vat=D("5"), total=D("105")))) == ["green"]
    assert "red" in levels(check_vat(Invoice(subtotal=D("100"), vat=D("5"), total=D("150"))))
