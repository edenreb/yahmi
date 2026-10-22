"""Reader checks on invented text in layouts other than the UAE templates. No real invoices or accounts:
the IBANs are the public documentation examples from the IBAN registry."""
from datetime import date
from decimal import Decimal

from yahmi.extract import find_amounts, find_date, find_iban, find_supplier, find_trns, parse_date
from yahmi.rules import iban_valid


def test_iban_other_countries_need_exact_length_and_checksum():
    for iban in ["GB82WEST12345698765432", "DE89370400440532013000", "NL91ABNA0417164300", "SA0380000000608010167519"]:
        assert iban_valid(iban)
        spaced = " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))
        assert find_iban(f"Pay to IBAN: {spaced} SWIFT: WESTGB2L") == (iban, True)
    assert not iban_valid("GB82WEST1234569876543")     # one character short
    assert not iban_valid("GB82WEST12345698765433")    # bad checksum
    assert not iban_valid("ZZ82WEST12345698765432")    # unknown country
    assert find_iban("Order ref PO12 3456 7890 1234 5678 9012")[1] is False


def test_iban_uae_still_found_in_noise():
    assert find_iban("IBAN AE07 0331 2345 6789 0123 456 Bank") == ("AE070331234567890123456", True)


def test_dates():
    assert parse_date("12 March 2026") == date(2026, 3, 12)
    assert parse_date("March 12, 2026") == date(2026, 3, 12)
    assert parse_date("05-Mar-26") == date(2026, 3, 5)
    assert parse_date("2026-03-12") == date(2026, 3, 12)
    assert parse_date("03/25/2026") == date(2026, 3, 25)       # second number above 12 means month-first
    assert parse_date("03/04/2026") == date(2026, 4, 3)        # ambiguous: day-first
    assert parse_date("31/02/2026") is None
    assert find_date("Due date: 01/05/2026\nInvoice date: 12 March 2026") == "12/03/2026"
    assert find_date("Issued 5 Jan 2026   Ref 33") == "05/01/2026"


def test_amount_layouts():
    assert find_amounts("Subtotal 1.000,00\nVAT 19% 190,00\nTotal 1.190,00") == (Decimal("1000.00"), Decimal("190.00"), Decimal("1190.00"))
    assert find_amounts("Subtotal 2'000.00\nTax 8% 160.00\nTotal 2'160.00") == (Decimal("2000.00"), Decimal("160.00"), Decimal("2160.00"))
    assert find_amounts("Net 1 500.00\nVAT 5% 75.00\nGrand total 1 575.00") == (Decimal("1500.00"), Decimal("75.00"), Decimal("1575.00"))
    assert find_amounts("Subtotal $400.00\nVAT 5% $20.00\nTotal $420.00") == (Decimal("400.00"), Decimal("20.00"), Decimal("420.00"))


def test_amounts_without_decimals():
    # a document whose money is printed without fils: grouped thousands are amounts anywhere
    assert find_amounts("Subtotal (AED) 14,240,766\nVAT (AED) 712,038\nTotal (AED) 14,952,804") == (Decimal("14240766"), Decimal("712038"), Decimal("14952804"))
    # ungrouped integers count when a currency code is attached
    assert find_amounts("Subtotal AED 1250\nVAT AED 63\nTotal AED 1313") == (Decimal("1250.00"), Decimal("63.00"), Decimal("1313.00"))
    assert find_amounts("Net Total 1250\nVAT 63\nGross 1313") == (Decimal("1250.00"), Decimal("63.00"), Decimal("1313.00"))
    # one integer-only line in an otherwise two-decimal document: reconciliation, not guessing
    assert find_amounts("Subtotal 1,250\nVAT 62.50\nTotal 1,312.50") == (Decimal("1250.00"), Decimal("62.50"), Decimal("1312.50"))
    # percentages, dates and day counts are not amounts
    assert find_amounts("Tax rate: 5%\nInvoice date: 26/10/2026\nTotal due: 30 days") == (None, None, None)


def test_discount_and_shipping_reconcile_the_total():
    assert find_amounts("Sub Total 1,000.00\nDiscount (100.00)\nTax (5%) 45.00\nTotal 945.00") == (Decimal("1000.00"), Decimal("45.00"), Decimal("945.00"))
    assert find_amounts("Sub Total 5,624.80\nDiscount (843.72)\nTax (5%) 239.05\nShipping 222.00\nBalance Due 5,242.13\nItem 7x 740.56\nAmount 5,183.92") == (Decimal("5624.80"), Decimal("239.05"), Decimal("5242.13"))


def test_foreign_tax_ids_are_not_trns():
    assert find_trns("Tax ID: 12-3456789\nVAT No. DE123456789") == (None, None)
    assert find_trns("TRN 100234567800003")[0] == "100234567800003"


def test_supplier_without_uae_suffix():
    assert find_supplier("Northwind Traders Ltd\n12 High Street\nBill To: Acme Corp") == "Northwind Traders Ltd"
    assert find_supplier("Kuala Tech Sdn Bhd\nJalan 1\nBill To: Foo") == "Kuala Tech Sdn Bhd"


def test_supplier_plain_header_under_document_title():
    text = "INVOICE\nKirk, Murphy and Daniels\nDate: 03-Mar-2002\nINVOICE ID INV16291505\nBILL_TO:\nSarah Ross"
    assert find_supplier(text) == "Kirk, Murphy and Daniels"
    assert find_supplier("TAX INVOICE\nNorthwind Traders\nDate: 03-Mar-2002") == "Northwind Traders"
    assert find_supplier("INVOICE\nDate: 03-Mar-2002\nBILL TO:\nAcme Trading LLC") is None
    assert find_supplier("ORI,\nGraham, Carrillo and Stark   -_ 2)\nAddress:8110 Lee Haven\nBill To: Acme") == "Graham, Carrillo and Stark"
    assert find_supplier("White and Sons   (eZ SN\nwww.WhiteandSons.org\nTAX INVOICE\nBuyer: Kimberly Kent") == "White and Sons"
    assert find_supplier("E> Yoder LLC\nAddress: 1 Main St\nBill To: Acme") == "Yoder LLC"
    assert find_supplier("INVOICE\n@) Navarro, Ford and Bryan   INVOICE ID 7637-774\nBill to: James") == "Navarro, Ford and Bryan"
    assert find_supplier("INVOICE\nMrs. Yolanda Moses   Morton-Leach\nBill to: James") == "Morton-Leach"


def test_numeric_date_order_follows_the_document():
    us = "Seller: Acme\n12 Elm St, Austin, TX 73301\nDate of issue: 10/01/2014\nTotal $ 40.00"
    assert find_date(us) == "01/10/2014"                      # US look, ambiguous: month-first
    uae = "Al Noor Trading LLC\nTRN 100234567800003\nInvoice date: 10/01/2014\nTotal AED 40.00"
    assert find_date(uae) == "10/01/2014"                     # UAE sign: day-first
    assert find_date("Invoice Date: 10/01/2014\nTotal 40.00") == "10/01/2014"   # no signal: day-first
    assert find_date("Date: 03/04/2020\nDue: 25/04/2020") == "03/04/2020"       # another date shows day-first
    assert find_date("Date: 03/04/2020\nDue: 04/25/2020") == "04/03/2020"       # another date shows month-first
    assert find_date("Date of issue: 09/18/2015 $ 5.00") == "18/09/2015"
    assert find_date("Date of issue: 10/01/2014\nIBAN: GB08KXQT19711661357354\nTotal $ 5.00\nAustin, TX 73301") == "01/10/2014"  # '971' inside a number is not a UAE phone code


def test_vat_line_beats_gst_line_when_both_are_printed():
    text = "SUB_TOTAL : 240.85 $\nGST (18%) : 43.35\nTAX:VAT (5.99%): 14.42 $\nTOTAL : 248.94 $"
    assert find_amounts(text) == (Decimal("240.85"), Decimal("14.42"), Decimal("248.94"))
