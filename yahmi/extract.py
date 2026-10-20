"""Extract invoice fields from a PDF (text layer) or a photo/scan (OCR).

The parser uses generic label vocabularies, not per-template rules, and checks its own work:
an IBAN is only accepted if it passes the mod-97 checksum, and amounts are reconciled so that
subtotal + VAT = total. Anything it cannot confirm is returned as uncertain for the user to check.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from .rules import Invoice, iban_valid

SUFFIX = r"(?:L\.?L\.?C\.?|FZ-?LLC|FZE|FZCO|Est\.?|Establishment|Co\.?\s*LLC|PJSC|Trading|Company)"
SUB_KEYS = ["sub total", "subtotal", "taxable", "net amount", "excl", "before vat", "amount before"]
VAT_KEYS = ["vat", "value added tax", "tax"]
TOT_KEYS = ["grand total", "total due", "amount payable", "balance due", "incl", "total"]
NOT_VAT = ["tax invoice", "tax reg", "registration", "incl", "excl", "before", "taxable", "trn"]


# Eastern Arabic and Persian digits, Arabic decimal/thousands separators -> Latin
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬", "01234567890123456789.,")


def norm_digits(text: str) -> str:
    return text.translate(_DIGITS)


def get_text(path: str, lang: str = "eng") -> tuple[str, str]:
    """Returns (text, method). Digits are normalised to Latin."""
    text, method = _get_text(path, lang)
    return norm_digits(text), method


def _get_text(path: str, lang: str) -> tuple[str, str]:
    low = path.lower()
    if low.endswith(".pdf"):
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            text = "\n".join((p.extract_text(layout=True) or "") for p in pdf.pages)
        if len(text.strip()) > 40:
            # keep wide gaps (column breaks) as 3 spaces, collapse narrow ones to 1
            text = "\n".join(re.sub(r" {4,}", "   ", re.sub(r"(?<=\S) {2,3}(?=\S)", " ", l)).strip() for l in text.splitlines())
            return text, "pdf-text"
        import fitz
        from PIL import Image
        doc = fitz.open(path)
        pix = doc[0].get_pixmap(dpi=200)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        return ocr(img, lang), "ocr"
    from PIL import Image
    return ocr(Image.open(path), lang), "ocr"


def ocr(img, lang: str = "eng") -> str:
    import pytesseract
    img = img.convert("L")
    if img.width < 1600:
        img = img.resize((img.width * 2, img.height * 2))
    # rebuild lines from word boxes, marking big horizontal gaps as column breaks ("   ")
    d = pytesseract.image_to_data(img, lang=lang, config="--psm 6", output_type=pytesseract.Output.DICT)
    lines, last = {}, {}
    for i, w in enumerate(d["text"]):
        if not w.strip():
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        x0, x1, h = d["left"][i], d["left"][i] + d["width"][i], max(d["height"][i], 1)
        if key in lines:
            gap = x0 - last[key]
            lines[key] += ("   " if gap > 2.5 * h else " ") + w
        else:
            lines[key] = w
        last[key] = x1
    return "\n".join(lines[k] for k in sorted(lines))


def _num(s: str) -> Decimal | None:
    s = s.replace(",", "").replace(" ", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _last_amount(line: str) -> Decimal | None:
    m = re.findall(r"\d{1,3}(?:[,\s]\d{3})*\.\d{2}|\d+\.\d{2}", line)
    return _num(m[-1]) if m else None


def find_iban(text: str) -> tuple[str | None, bool]:
    """Returns (iban, confident). Tolerates spaces and common OCR confusions."""
    cands = []
    for m in re.finditer(r"A\s?E\s?[0-9OoIl|]{2}(?:[ \-]{0,3}[0-9OoIlSB|]){19}", text):
        raw = re.sub(r"[\s\-]", "", m.group(0))
        fixed = raw[:2] + raw[2:].translate(str.maketrans("OoIl|SB", "0011158"))
        cands.append(fixed)
    for c in cands:
        if iban_valid(c):
            return c, True
    # second pass: IBAN-labelled lines, with deterministic OCR fixes only (no guessing by edits)
    for line in text.splitlines():
        if "IBAN" not in line.upper():
            continue
        tail = re.split(r"IBAN\)?\s*:?", line, flags=re.I)[-1]
        compact = re.sub(r"[^A-Za-z0-9|]", "", tail)
        if len(compact) != 23:
            continue
        body = compact[2:].translate(str.maketrans("OoIl|SBZ", "00111582"))
        for prefix in ("AE",):
            c = prefix + body
            if iban_valid(c):
                return c, True
        cands.append("AE" + body)
    return (cands[0], False) if cands else (None, False)


def find_trns(text: str) -> tuple[str | None, str | None]:
    supplier = customer = None
    for line in text.splitlines():
        for m in re.finditer(r"(?<!\d)(\d[\d ]{13,18}\d)(?!\d)", line):
            d = re.sub(r"\D", "", m.group(1))
            if len(d) != 15:
                continue
            if re.search(r"customer|bill\s*to|buyer|client|recipient", line, re.I):
                customer = customer or d
            elif re.search(r"trn|tax|vat|reg", line, re.I):
                supplier = supplier or d
    return supplier, customer


def find_amounts_arith(text: str):
    """Label-free: find subtotal, VAT and total by the arithmetic that must hold on a UAE tax
    invoice (VAT = 5% of subtotal, total = subtotal + VAT). Works on any layout."""
    amts = [_num(m) for m in re.findall(r"\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2}", text)]
    amts = [a for a in amts if a is not None and a > 0]
    best = None
    for i, s in enumerate(amts):
        v_exp = (s * Decimal("0.05")).quantize(Decimal("0.01"))
        for j in range(i + 1, min(i + 6, len(amts))):
            v = amts[j]
            if abs(v - v_exp) > Decimal("0.01"):
                continue
            for k in range(j + 1, min(j + 6, len(amts))):
                if abs(s + v - amts[k]) <= Decimal("0.01"):
                    if best is None or amts[k] >= best[2]:
                        best = (s, v, amts[k])
    return best


def find_amounts(text: str):
    arith = find_amounts_arith(text)
    if arith:
        return arith
    sub = vat = tot = None
    for line in text.splitlines():
        lo = line.lower()
        amt = _last_amount(line)
        if amt is None:
            continue
        if any(k in lo for k in SUB_KEYS) and sub is None:
            sub = amt
        elif any(k in lo for k in VAT_KEYS) and not any(k in lo for k in NOT_VAT) and vat is None:
            vat = amt
        elif any(k in lo for k in TOT_KEYS) and tot is None:
            tot = amt
    # reconcile with arithmetic when one is missing
    if sub is not None and vat is not None and tot is None:
        tot = sub + vat
    if sub is not None and tot is not None and vat is None:
        vat = tot - sub
    if vat is not None and tot is not None and sub is None:
        sub = tot - vat
    return sub, vat, tot


# Invoice-number labels: a document word (invoice / inv / bill / document / receipt) plus a number
# word (no / number / # / ref / id / code / serial); bare "Reference" / "Our Ref" / "Serial" count too
# but rank below. Tolerates common OCR slips (0 for o, 1/l for i, "Ret" for "Ref", "1D" for "ID").
_NO = r"n[o0](?![A-Za-z])[.,]?"
_INV_LABEL = re.compile(r"""(?:
      (?P<doc>(?:tax\s*)?(?:[il1]nv[o0]?[il1]ce|[il1]n[vy]|bill|d[o0]c(?:ument)?|receipt|fatoorah)[.,]?\s*
          (?:NO|num(?:ber)?[.,]?|nbr|\#|serial(?:\s*NO|\s*number)?|re[ft](?:erence)?(?![A-Za-z])[.,]?(?:\s*NO)?|[il1(|]d(?![A-Za-z])|c[o0a]de))
    | (?P<gen>serial(?:\s*(?:NO|number|\#))?|(?:our\s+)?re[ft](?:erence)?(?![A-Za-z])[.,]?(?:\s*(?:NO|number|\#))?)
    | (?P<ar>رقم\s*الفاتورة)
    )""".replace("NO", _NO), re.I | re.X)
# words that make a "ref / no." label belong to someone else's document
_INV_FOREIGN = re.compile(r"(?:customer|client|buyer|your|order|purchase|p\.?\s*o|lpo|delivery|quotation|quote|contract|account|a/c|bank|iban|trn|tax\s*reg|registration|vat\s*reg|tel|phone|mobile|fax|cheque|payment|transaction)\.?\s*$", re.I)
_INV_TOKEN = re.compile(r"[A-Za-z0-9$§](?:[A-Za-z0-9/\-_.~$§!\]}|]*[A-Za-z0-9!\]}/\-~])?")
_TO_DIGIT = str.maketrans("OoIl|!SB", "00111158")
_TO_LETTER = str.maketrans("01!|]}$§", "OIIIIISS")


def _inv_fix(v: str) -> str:
    """Undo OCR confusions inside an invoice number, one separator-delimited segment at a time:
    a mostly-digit run loses stray look-alike letters (S093 -> 5093), a short letter prefix loses
    stray look-alike digits (S1 -> SI, 1NV -> INV)."""
    v = re.sub(r"([-/])[-/~]+", r"\1", re.sub(r"[~—–]", "-", v))
    out = []
    for seg in re.split(r"([-/])", v):
        odd = re.sub(r"[A-Za-z0-9]", "", seg)
        if sum(c.isdigit() for c in seg) >= 3 and len(re.findall(r"[^0-9]", seg)) == 1 and re.fullmatch(r"[0-9OoIl|!SB]+", seg):
            seg = seg.translate(_TO_DIGIT)
        elif 2 <= len(seg) <= 4 and re.search(r"[A-Za-z$§]", seg) and sum(c.isdigit() for c in seg) <= 1 and re.fullmatch(r"[A-Za-z01!|\]}$§]+", seg) or odd and re.fullmatch(r"[A-Za-z!|\]}$§]+", seg):
            seg = seg.translate(_TO_LETTER)
        if re.fullmatch(r"[A-Z]*l[A-Z]*", seg) and len(seg) >= 2:
            seg = seg.replace("l", "I")  # lower-case l inside an all-caps prefix
        out.append(seg)
    return "".join(out).strip("!|]-/.")


def _inv_value_ok(v: str) -> bool:
    """Shape of an invoice number: has a digit, and is not a date, TRN, IBAN, phone number or amount."""
    if not re.search(r"\d", v) or len(v) > 24 or len(re.sub(r"\D", "", v)) < 2:
        return False
    if re.fullmatch(r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2}", v):
        return False  # date
    if re.fullmatch(r"\d{15}", v) or re.fullmatch(r"AE\d{2}[\dA-Z]{5,}", v, re.I) and len(v) >= 15:
        return False  # TRN / IBAN
    if re.fullmatch(r"(?:\+?971|00971|0)\d{8,9}", v):
        return False  # phone
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+\.\d{2}", v):
        return False  # amount
    if re.fullmatch(r"\d{1,2}(?:\.\d+)?%?", v):
        return False  # tiny numbers ("5", "5%")
    return True


def _inv_from(rest: str) -> str | None:
    """First invoice-number-shaped value at the start of `rest` (the text after a label)."""
    rest = re.sub(r"^[\s:#.,\-–=|]*", "", rest)
    rest = re.sub(r"^n[o0][.,]?\s*[:#]?\s*(?=\w)", "", rest, flags=re.I)  # "Bill Number: No. 123"
    rest = re.sub(r"^[:#]\s*", "", rest)
    m = _INV_TOKEN.match(rest)
    if not m:
        return None
    v, pos = m.group(0), m.end()
    # OCR may split a number with single spaces ("INV/2026/ 9866", "TAX-31 29-C", "IN V/2026")
    for _ in range(3):
        m2 = re.match(r" ([A-Za-z0-9$][A-Za-z0-9/\-~]*)", rest[pos:])
        if not m2:
            break
        p = m2.group(1)
        if re.match(r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}", p) or re.fullmatch(r"\d{1,3}(?:,\d{3})*\.\d{2}", p):
            break
        joint = v[-1] in "-/~" or p[0] in "-/~" or (v[-1].isdigit() and p[0].isdigit()) \
            or (re.search(r"(?:^|[-/])[A-Za-z]{1,3}$", v) and re.search(r"[-/~]", p) and re.search(r"\d", p))
        if not joint or not _inv_value_ok(_inv_fix(v + p)):
            break
        v, pos = v + p, pos + m2.end()
    v = _inv_fix(v)
    return v if _inv_value_ok(v) else None


def _cells(line: str) -> list[tuple[int, str]]:
    return [(m.start(), m.group(0)) for m in re.finditer(r"\S+(?: \S+)*", line)]


def find_invoice_number(text: str) -> str | None:
    """Label vocabulary + value shape. The value may follow the label on the same line or sit
    in the same column on the next line; dates, TRNs, IBANs, phone numbers and amounts are rejected.
    Specific labels (invoice / bill / document no.) beat generic ones (ref, serial)."""
    lines = norm_digits(text).splitlines()
    best = None  # (tier, line index, value)
    for i, line in enumerate(lines):
        for m in _INV_LABEL.finditer(line):
            a = m.start()
            if a and line[a - 1].isalpha() and not (line[a - 1].isupper() and line[a].isupper() and line[a + 1:a + 2].islower()):
                continue  # inside a word ("Preferred"); but allow a glued "...LLCSerial"
            if _INV_FOREIGN.search(line[:a]):
                continue
            tier = 0 if (m.group("doc") or m.group("ar")) else 1
            v = _inv_from(line[m.end():])
            if v is None and not re.search(r"\w", re.split(r"\s{2,}", line[m.end():].strip(" :#.-"), maxsplit=1)[0] or ""):
                # label stands alone in its cell: look below it, same column first
                for nxt in lines[i + 1:i + 3]:
                    if not nxt.strip():
                        continue
                    cells = _cells(nxt)
                    col = sorted(cells, key=lambda c: abs(c[0] - m.start()))
                    for _, cell in col:
                        v = _inv_from(cell)
                        if v:
                            break
                        v = None
                    if v is None:  # value pushed right by a long neighbour, single-spaced
                        last = nxt.split()[-1]
                        v = _inv_from(last) if re.search(r"\d{3}", last) else None
                    break
            if v is None:
                continue
            if best is None or (tier, i) < best[:2]:
                best = (tier, i, v)
    return best[2] if best else None


def find_date(text: str) -> str | None:
    m = re.search(r"(?:date|dated)[^\n\d]{0,12}(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{4})", text, re.I) or re.search(r"(\d{1,2}/\d{1,2}/\d{4})", text)
    return m.group(1).replace("-", "/").replace(".", "/") if m else None


_SUP_LABEL = re.compile(r"^(?:supplier|seller|vendor|issued\s+by|from|company)(?:\s*name)?\s*(?::|-|\s{2,})\s*(.*)$", re.I)
_ACC_LABEL = re.compile(r"(?:account|a/c|beneficiary)\s*(?:holder\s*)?name\s*[:\-]?\s*(.+)$", re.I)
_CUST = re.compile(r"bill(?:ed)?\s*to|customer|buyer|sold\s*to|ship\s*to|client", re.I)
_NOT_NAME = re.compile(r"\b(?:trn|tax\s*reg|vat\s*reg|registration|iban|address|tel|phone|email|p\.?o\.?\s*box)\b", re.I)


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _is_company(c: str) -> bool:
    return len(c.split()) >= 2 and bool(re.search(SUFFIX + r"\s*$", c, re.I)) and not _CUST.search(c) and not _NOT_NAME.search(c)


def _header_candidates(lines: list[str]) -> list[str]:
    """Company-looking names in the issuer block: everything above the Bill To / customer block."""
    out = []
    for l in lines:
        if _CUST.search(l):
            break
        chunks = [_clean_name(ch) for ch in re.split(r"\s{3,}", l)] + [_clean_name(re.sub(r"\s+", " ", l))]
        ok = [c for c in chunks if _is_company(c)]
        if ok:
            out.append(max(ok, key=len))
    return out


def _labelled_supplier(lines: list[str]) -> str | None:
    """'Supplier: X' / 'From: X' / 'From:' on its own line with the name below (first company-looking line)."""
    for i, l in enumerate(lines):
        if _CUST.search(l.split(":")[0]):
            break
        m = _SUP_LABEL.match(l)
        if not m:
            continue
        v = _clean_name(re.sub(r"^\s*:\s*", "", m.group(1)))
        if len(v.split()) >= 2 and not _NOT_NAME.search(v):
            return v
        for nxt in lines[i + 1:i + 3]:
            c = _clean_name(re.sub(r"\s+", " ", nxt)) if not re.search(r"\s{3,}", nxt) else _clean_name(nxt)
            if _is_company(c) or (len(c.split()) >= 2 and not re.search(r"\d", c) and not _CUST.search(c) and not _NOT_NAME.search(c)):
                return c
    return None


def _account_name(lines: list[str]) -> str | None:
    for l in lines:
        m = _ACC_LABEL.search(l)
        if m:
            v = _clean_name(m.group(1))
            if len(v.split()) >= 2:
                return v
    return None


def _close(a: str, b: str) -> bool:
    return SequenceMatcher(None, _key(a), _key(b)).ratio() >= 0.85


_JUNK = re.compile(r"[^A-Za-z0-9.&'()-]")


def _word_score(w: str) -> tuple:
    # fewer stray OCR symbols is better; a recognised company suffix is better; 'Al' (Arabic article) over 'AI'
    return (-len(_JUNK.findall(w)), bool(re.fullmatch(SUFFIX, w, re.I)), w != "AI")


def _merge_reads(a: str, b: str) -> str:
    """Two OCR reads of the same name: keep, for each word, the cleaner reading (ties go to the first read)."""
    wa, wb = a.split(), b.split()
    if len(wa) != len(wb):
        return a if _is_company(a) else b
    return " ".join(x if _word_score(x) >= _word_score(y) else y for x, y in zip(wa, wb))


def find_supplier(text: str) -> str | None:
    """Supplier (issuer) name. Evidence, strongest first: an explicit 'Supplier:'/'From:' label; a company-suffixed
    name in the header (above the Bill To block) that agrees with the payment 'Account name:'; the account name
    itself when the header is unreadable or disagrees; otherwise the first company-suffixed header name."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    acc = _account_name(lines)
    lab = _labelled_supplier(lines)
    heads = _header_candidates(lines)
    if lab and acc and _key(lab) != _key(acc) and _close(lab, acc):
        return _merge_reads(lab, acc)
    if lab and (not acc or _key(lab) == _key(acc) or not _is_company(acc) or _is_company(lab)):
        return lab
    if acc and _is_company(acc):
        for h in heads:
            if _key(h) == _key(acc):
                return h
        # OCR: the header and the account line can each carry a few misread letters. A header name that
        # nearly matches the account name is the same company: merge the two reads word by word.
        close = [h for h in heads if _close(h, acc)]
        return _merge_reads(close[0], acc) if close else acc
    if heads:
        return heads[0]
    return lab or acc


def _clean_name(l: str) -> str:
    l = re.split(r"\s{3,}|\s*(?:tax\s*invoice|invoice\s*\(tax\)|invoice|inv\.|bill\s*no|reference|document\s*no|date|issue\b|due\b|serial\b|our\s+ref\b|ref(?:\.|\b))", l, flags=re.I)[0]
    return l.strip(" :")


def parse(text: str) -> Invoice:
    iban, iban_ok = find_iban(text)
    s_trn, c_trn = find_trns(text)
    sub, vat, tot = find_amounts(text)
    amounts_by_arith = find_amounts_arith(text) is not None
    inv = Invoice(
        supplier_name=find_supplier(text), supplier_trn=s_trn, customer_trn=c_trn, iban=iban,
        invoice_number=find_invoice_number(text), invoice_date=find_date(text),
        subtotal=sub, vat=vat, total=tot,
        is_tax_invoice_titled=bool(re.search(r"tax\s*invoice|invoice\s*\(tax\)", text, re.I)), raw_text=text,
    )
    inv.extra["iban_confident"] = iban_ok
    inv.extra["amounts_confident"] = amounts_by_arith
    return inv


def _score(inv: Invoice) -> int:
    return 2 * bool(inv.extra.get("amounts_confident")) + 2 * bool(inv.extra.get("iban_confident")) + bool(inv.supplier_trn)


def extract(path: str) -> Invoice:
    text, method = get_text(path)
    inv = parse(text)
    inv.extra["method"] = method
    # Bilingual invoice photo (e.g. Eastern Arabic digits) that English OCR couldn't reconcile:
    # retry with Arabic + English OCR and keep whichever read checks out better.
    if method == "ocr" and _score(inv) < 5:
        text2, _ = get_text(path, "ara+eng")
        inv2 = parse(text2)
        inv2.extra["method"] = "ocr-ara"
        if _score(inv2) > _score(inv):
            return inv2
    return inv
