"""Reader checks on invented text in layouts other than the UAE templates. No real invoices or accounts:
the IBANs are the public documentation examples from the IBAN registry."""
from datetime import date
from decimal import Decimal

from yahmi.extract import find_amounts, find_date, find_iban, find_invoice_number, find_supplier, find_trns, parse_date
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


def test_supplier_name_says_how_sure_it_is():
    from yahmi.extract import find_supplier_detail, parse
    assert find_supplier_detail("TAX INVOICE\nFalcon Building Materials LLC\nAl Quoz, Dubai\nBill To: Sample Customer LLC\n") == ("Falcon Building Materials LLC", True)
    assert find_supplier_detail("Seller:   Client:\nBradley-Andrade   Castro PLC\n9879 Elizabeth Common\n") == ("Bradley-Andrade", True)
    assert find_supplier_detail("Payment details\nAccount name: Falcon Building Materials LLC\nIBAN: x\n") == ("Falcon Building Materials LLC", True)
    # position-based guesses (no label, no company suffix) can pick the wrong text: reported as not confident
    assert find_supplier_detail("INVOICE\nBarnes, Garcia and Martin\nAddress:13868 Michael Wall\nBill to: Suzanne\n") == ("Barnes, Garcia and Martin", False)
    assert find_supplier_detail("TAX INVOICE\nNorthwind Traders\n12 High Street\nBill To: Acme\n") == ("Northwind Traders", False)
    assert parse("TAX INVOICE\nNorthwind Traders\n12 High Street\nBill To: Acme\n").extra["supplier_confident"] is False
    assert parse("TAX INVOICE\nFalcon Building Materials LLC\nAl Quoz, Dubai\nBill To: Acme\n").extra["supplier_confident"] is True


def test_invoice_number_below_a_header_row_not_a_date():
    # invented layout: "Invoice No." is one column of a header row; the next header word is not a value
    assert find_invoice_number("Invoice No.      Date        Ref\nINV-20481        05-Mar-24") == "INV-20481"
    # a month-name date under the label is not an invoice number
    assert find_invoice_number("Invoice No.      Date\n                 05-Mar-24") is None


def test_invoice_number_ti_no_label():
    # "TI No." (tax invoice no.) is a document label; a bare "No." or an order/DO number is not
    assert find_invoice_number("Customer A/c: Example Trading LLC        TI No.: AB/12/2025/00417\nDO No: 8841") == "AB/12/2025/00417"
    assert find_invoice_number("Customer A/c: Example Trading LLC\nDO No: 8841") is None


def test_invoice_number_in_flattened_date_header_row():
    # OCR flattens "Date | Inv. No. | Project | P.O. Ref." into one line and other lines may sit before the data row
    t = "Date   Inv. No.   Project Name   P.O. Ref. No.\nBill To:\nExample Project Name\n25-01-2024 AB-INV-2024-0001 XX-PO-000118"
    assert find_invoice_number(t) == "AB-INV-2024-0001"
    # without a date header the same row gives nothing
    assert find_invoice_number("Project   P.O. Ref.\n25-01-2024 AB-2024-0001 XX-PO-000118") is None


def test_invoice_number_bare_no_header_row_and_unlabelled_inv_token():
    # header row starting with a bare "No"; the data row starts with the number, then a TRN (invented numbers)
    t = "No   Cust VAT Reg.   Tax Invoice   VAT Reg.   Tax Date\n4721   100000000000001      100000000000002   27/01/2024"
    assert find_invoice_number(t) == "4721"
    # a bare "No" header without VAT Reg / Tax Date is an item table, not an invoice number
    assert find_invoice_number("No   Description   Qty\n12   100000000000001 widgets") is None
    # no label at all: an INV-prefixed token under the title, or after a dotted "Ref."
    assert find_invoice_number("TAX INVOICE\n#INV-0000123\nPO DATE : 25/08/2025") == "INV-0000123"
    assert find_invoice_number("Ref. ........ AB/CD/INV6\nTAX INVOICE") == "AB/CD/INV6"
    # "INVOICE :" with no "No"
    assert find_invoice_number("DATE :   January 22, 2024\nINVOICE :   3150088\nYOUR ORDER NO.   AB-PO-9912") == "3150088"


def test_invoice_number_bare_no_stray_char_and_joined_letters():
    # bare "No" beside a Date line, no colon (invented values); a DO / LPO / TRN number does not count
    assert find_invoice_number("Customer Code   AB12   No   731905\nName and Address   Example LLC   Date   30/06/2025") == "731905"
    assert find_invoice_number("Customer Code   AB12   DO No   731905\nName and Address   Example LLC   Date   30/06/2025") is None
    # a misread colon between label and value: "Invoice No. 9 ABC004738"
    assert find_invoice_number("Customer :   Invoice No. 9 ABC004738\nDate : 29-January-2024") == "ABC004738"
    # letters + space + digits ("ABC 0204") in a cell next to a date, with "Invoice" in the header above
    assert find_invoice_number("Date   Invoice   LPO No\nAddress PO Box 1   25-01-2024 ABC 0204   XX-PO-0086") == "ABC0204"
    # a stray one-letter "Invoice No. A 123" is not joined into a number by the new rule
    assert find_invoice_number("Invoice No: AB") is None


def test_total_with_glued_currency_beats_line_items_that_add_up_to_the_subtotal():
    # item rows 1,400.00 + 260.00 = 1,660.00 (the subtotal) must not be read as subtotal + VAT = total
    t = ("1   Item one   10.00   140.00   1,400.00\n2   Item two   1.00   260.00   260.00\n\n"
         "Sub Total   1,660.00\nVAT 5% (5%)   83.00\nGrand Total   AED1,743.00")
    assert find_amounts(t) == (Decimal("1660.00"), Decimal("83.00"), Decimal("1743.00"))

