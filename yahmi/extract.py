"""Extract invoice fields from a PDF (text layer) or a photo/scan (OCR).

The parser uses generic label vocabularies, not per-template rules, and checks its own work:
an IBAN is only accepted if it passes the mod-97 checksum, and amounts are reconciled so that
subtotal + VAT = total. Anything it cannot confirm is returned as uncertain for the user to check.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from .rules import IBAN_LENGTHS, Invoice, iban_valid

SUFFIX = (r"(?:L\.?L\.?C\.?|FZ-?LLC|FZE|FZCO|Est\.?|Establishment|Co\.?\s*LLC|PJSC|Trading|Company"
          r"|Pty\.?\s*Ltd\.?|Sdn\.?\s*Bhd\.?|Pvt\.?\s*Ltd\.?|Ltd\.?|Limited|Inc\.?|Incorporated|Corp\.?|Corporation|LLP|GmbH|PLC|S\.A\.|B\.V\.|S\.?R\.?L\.?|SARL)")
SUB_KEYS = ["sub total", "subtotal", "net total", "taxable", "net amount", "excl", "before vat", "amount before"]
VAT_KEYS = ["vat", "value added tax", "gst", "sales tax", "tax"]
TOT_KEYS = ["grand total", "total due", "amount due", "amount payable", "balance due", "gross", "incl", "total"]
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


# An amount with two decimals, in any common layout: 1,234.56  1.234,56  1 234.56  1'234.56  1234,56  (12.00)  -12.00
_AMT = re.compile(r"(?<![\w.,'])(\(?-?)\s?((?:\d{1,3}(?:[ \u00a0',.]\d{3})+|\d+)[.,]\d{2})(?![\d]|[.,]\d)\)?")


def _amounts(text: str) -> list[Decimal]:
    """Every two-decimal amount in the text, in order, as Decimals. Handles comma decimals, space/apostrophe/dot
    thousands, and negatives written with a minus or brackets."""
    out = []
    for m in _AMT.finditer(text):
        body = m.group(2)
        v = Decimal(re.sub(r"\D", "", body[:-3]) + "." + body[-2:])
        out.append(-v if m.group(1) else v)
    return out


def _last_amount(line: str, doc_cents: bool = True) -> Decimal | None:
    a = _amounts(line)
    if not a:
        a = _int_money(line, bare=not doc_cents)
    return a[-1] if a else None


# Amounts written without decimal places (fils dropped, or a currency printed in whole units).
# Thousand-grouped integers ("1,234", "1 234 567", "1.234") count anywhere; an ungrouped "1250"
# counts when a currency code or symbol is attached ("AED 1250", "$ 1250", "1250 AED"), or when
# the whole document has no decimal amounts at all and the line carries a money label.
# Percent signs, dates ("26/10"), phone-number chains and TRN digits never match.
_CUE = r"(?:(?:AED|USD|EUR|GBP|SAR|QAR|OMR|KWD|BHD|EGP|Dhs?|Dirhams?)(?![A-Za-z])|[$£€¥])"
_AMT_NO_DEC = re.compile(r"(?<![\w.,'])(\(?\s?-)?\s?(\d{1,3}(?:[ \u00a0',.]\d{3})+)(?!\d|[.,]\d|\s?\d)")
_AMT_CUED_BEFORE = re.compile(r"(?<![\w.,'])(\(?\s?-)?\s?(?:" + _CUE + r")\s{0,2}(\d+)(?!\d|[.,]\d|\s?\d)", re.I)
_AMT_CUED_AFTER = re.compile(r"(?<![\w.,'])(\(?\s?-)?\s?(\d+)(?!\d|[.,]\d|\s?\d)\W{0,3}(?:" + _CUE + r")(?![-A-Za-z])", re.I)
_AMT_INT_BARE = re.compile(
    r"(?<![\w.,'])(\(?\s?-)?\s?(\d+)(?!\d|[.,]\d|\s?\d)"
    r"(?!\s{0,2}%)(?!\s{0,2}(?:days?|nights?|hrs?|hours?|minutes?|items?|pieces?|pcs|units?|kg|tons?|months?|years?|weeks?|n[o0]s?\.?)\b)",
    re.I)


def _int_money(text: str, bare: bool = False) -> list[Decimal]:
    """Money with no decimal places, in document order (grouped thousands; cued plain integers;
    bare integers only when the caller says the document has no decimal amounts anywhere)."""
    out, seen = [], set()
    pairs = [(_AMT_NO_DEC, 2), (_AMT_CUED_BEFORE, 2), (_AMT_CUED_AFTER, 2)]
    if bare:
        pairs.append((_AMT_INT_BARE, 2))
    for rx, ng in pairs:
        for m in rx.finditer(text):
            s = m.start(ng)
            if s in seen:
                continue
            seen.add(s)
            v = Decimal(re.sub(r"\D", "", m.group(ng)))
            out.append((s, -v if m.group(1) else v))
    return [v for _, v in sorted(out)]


# A printed discount/shipping line between the subtotal and the total means
# total = subtotal - discount + shipping + VAT, so plain s + v = t no longer holds.
# "Less VAT 27.50" is a VAT exclusion, not a discount.
_DISC_LINE = re.compile(r"^\s*(?:less|discount|rebate|deduction|trade\s+discount)\b(?!\W*?(?:vat|tax|gst)\b)", re.I)
_SHIP_LINE = re.compile(r"^\s*(?:shipping|freight|carriage|handling|delivery\s+charges?|courier|postage|freight\s+out)\b", re.I)


_IBAN_ANY = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2}\d{2}(?:[ \-]?[A-Za-z0-9]){11,34}")


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
        if compact[:2].upper() != "AE" and compact[:2].upper() in IBAN_LENGTHS:
            continue  # the OCR repair is for UAE IBANs only: never rewrite a real country code (GB, DE...); a garbled "AE" is fine
        body = compact[2:].translate(str.maketrans("OoIl|SBZ", "00111582"))
        c = "AE" + body
        if iban_valid(c):
            return c, True
        cands.append(c)
    # any other country: accepted only if the length for that country and the checksum both hold (no OCR repair)
    for m in _IBAN_ANY.finditer(text):
        compact = re.sub(r"[\s\-]", "", m.group(0)).upper()
        n = IBAN_LENGTHS.get(compact[:2])
        if n and len(compact) >= n and iban_valid(compact[:n]):
            return compact[:n], True
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


def find_amounts_arith(text: str, uae_only: bool = False):
    """Label-free: find subtotal, VAT and total by the arithmetic that must hold on a tax invoice
    (total = subtotal + VAT). UAE 5% is tried first; otherwise any rate from 1% to 30% is accepted
    when the total is the largest amount on the page. A printed discount or shipping line between the
    subtotal row and the total row is folded into the equation (total = subtotal - discount + shipping
    + VAT; VAT is then expected to be 5% of the net when the page reads as UAE). A match that needed a
    discount/shipping line outranks an unadjusted one, because item rows can also add up to the subtotal
    by luck (and, with a discount, the true total is not the largest amount on the page). Works on any
    layout; amounts with no decimals are used when the page has no decimal amounts at all."""
    lines = text.splitlines()
    disc_rows = {n for n, l in enumerate(lines) if _DISC_LINE.match(l)}
    ship_rows = {n for n, l in enumerate(lines) if _SHIP_LINE.match(l)}
    raw = [(n, a) for n, l in enumerate(lines) for a in _amounts(l)]
    if not raw:
        raw = [(n, a) for n, l in enumerate(lines) for a in _int_money(l)]
    positions = [i for i, (n, a) in enumerate(raw) if a > 0]
    amts = [raw[i][1] for i in positions]
    if not amts:
        return None

    def between(i: int, k: int):
        d = sh = Decimal("0")
        for ri in range(i + 1, k):
            n, a = raw[ri]
            if n in disc_rows:
                d += abs(a)
            elif n in ship_rows:
                sh += abs(a)
        return d, sh

    q2 = lambda x: x.quantize(Decimal("0.01"))
    best = None  # (subtotal, vat, total, row): an unadjusted s + vat = total match
    adj = None   # (subtotal, vat, total, row): a match saved by a printed discount/shipping line
    for u, i in enumerate(positions):
        s = raw[i][1]
        v_exp = (s * Decimal("0.05")).quantize(Decimal("0.01"))
        for w in range(u + 1, min(u + 6, len(amts))):
            j = positions[w]
            v = raw[j][1]
            for x in range(w + 1, min(w + 6, len(amts))):
                k = positions[x]
                t = raw[k][1]
                if abs(s + v - t) <= Decimal("0.01"):
                    if abs(v - v_exp) <= Decimal("0.01") and (best is None or (t, k) > (best[2], best[3])):
                        best = (s, v, t, k)
                else:
                    D, Sh = between(i, k)
                    if (D or Sh) and abs(s - D + Sh + v - t) <= Decimal("0.01") \
                            and (abs(v - v_exp) <= Decimal("0.01") or (s - D > 0 and abs(v - ((s - D) * Decimal("0.05")).quantize(Decimal("0.01"))) <= Decimal("0.01"))) \
                            and (adj is None or (t, k) > (adj[2], adj[3])):
                        adj = (s, v, t, k)
    if best or uae_only or not amts:
        return (best[0], best[1], best[2]) if best else None
    top = max(amts)
    for u, i in enumerate(positions):
        s = raw[i][1]
        for w in range(u + 1, min(u + 6, len(amts))):
            j = positions[w]
            v = raw[j][1]
            if not Decimal("0.01") <= v / s <= Decimal("0.30"):
                continue
            for x in range(w + 1, min(w + 6, len(amts))):
                k = positions[x]
                t = raw[k][1]
                if abs(s + v - t) <= Decimal("0.01"):
                    if t == top and (best is None or (t, k) > (best[2], best[3])):
                        best = (s, v, t, k)
                else:
                    d, sh = between(i, k)
                    if (d or sh) and abs(s - d + sh + v - t) <= Decimal("0.01") \
                            and (adj is None or (t, k) > (adj[2], adj[3])):
                        adj = (s, v, t, k)
    winner = adj if adj else best
    return (winner[0], winner[1], winner[2]) if winner else None


def find_amounts(text: str):
    arith = find_amounts_arith(text)
    if arith:
        return arith
    doc_cents = bool(_amounts(text))  # the document prints two-decimal amounts somewhere
    sub = None
    vat = None  # (priority, line no, amount): a "VAT" line beats GST / sales tax / plain "tax"; the first line wins a tie
    tot = None  # (priority, line no, amount): the most specific total label wins, the lowest line on a tie
    for n, line in enumerate(text.splitlines()):
        lo = line.lower().replace("_", " ")
        amt = _last_amount(line, doc_cents)
        if amt is None:
            continue
        if any(k in lo for k in SUB_KEYS):
            sub = sub if sub is not None else amt
        elif any(k in lo for k in VAT_KEYS) and not any(k in lo for k in NOT_VAT):
            pri = next(i for i, k in enumerate(VAT_KEYS) if k in lo)
            if vat is None or pri < vat[0]:
                vat = (pri, n, amt)
        else:
            pri = next((i for i, k in enumerate(TOT_KEYS) if k in lo), None)
            if pri is not None and (tot is None or (pri, -n) < (tot[0], -tot[1])):
                tot = (pri, n, amt)
    tot = tot[2] if tot else None
    vat = vat[2] if vat else None
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


_MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
_DATE_RES = [
    ("num", re.compile(r"(?<![\d/.\-])(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4}|\d{2})(?![\d])")),
    ("iso", re.compile(r"(?<![\d/.\-])(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})(?![\d])")),
    ("dmy", re.compile(r"(?<![\d])(\d{1,2})(?:st|nd|rd|th)?[\s\-./,]*(" + _MON + r")[a-z]*\.?,?[\s\-./]*(\d{4}|\d{2})(?![\d])", re.I)),
    ("mdy", re.compile(r"\b(" + _MON + r")[a-z]*\.?\s*(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4}|\d{2})(?![\d])", re.I)),
]


def _mk_date(y: int, m: int, d: int):
    import datetime
    if y < 100:
        y += 2000 if y < 70 else 1900
    try:
        return datetime.date(y, m, d)
    except ValueError:
        return None


def parse_date(s: str, mdy: bool = False):
    """First date in `s` as a datetime.date. An ambiguous numeric date (both numbers 12 or less) is day-first,
    or month-first when `mdy` is set; a number above 12 always decides."""
    best = None
    for kind, rx in _DATE_RES:
        m = rx.search(s)
        if not m or (best is not None and m.start() >= best[0]):
            continue
        a, b, c = m.groups()
        if kind == "num":
            a, b = int(a), int(b)
            month_first = b > 12 or (mdy and a <= 12)
            d = _mk_date(int(c), a if month_first else b, b if month_first else a)
        elif kind == "iso":
            d = _mk_date(int(a), int(b), int(c))
        elif kind == "dmy":
            d = _mk_date(int(c), _MONTHS[b[:3].lower()], int(a))
        else:
            d = _mk_date(int(c), _MONTHS[a[:3].lower()], int(b))
        if d:
            best = (m.start(), d)
    return best[1] if best else None


_UAE_SIGNS = re.compile(r"\bAED\b|dirham|\bUAE\b|United Arab Emirates|\bTRN\b|Dubai|Abu\s*Dhabi|Sharjah|Ajman|Fujairah|Ras\s*Al|Umm\s*Al|\bAE\d{2}\b|(?<!\d)(?:\+|00)971", re.I)
_US_SIGNS = re.compile(r"\$|,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\b|\bUSD\b")


def _mdy(text: str) -> bool:
    """Is this document's numeric date order month-first? The dates themselves decide when any is unambiguous
    (09/18/2015 is month-first, 18/09/2015 day-first); otherwise a US look (dollar amounts, a US state and ZIP code)
    with no UAE sign (AED, TRN, an emirate, +971) means month-first. Day-first is the default."""
    mf = df = 0
    for m in _DATE_RES[0][1].finditer(text):
        a, b = int(m.group(1)), int(m.group(2))
        mf += b > 12 and a <= 12
        df += a > 12 and b <= 12
    if mf != df:
        return mf > df
    return bool(_US_SIGNS.search(text)) and not _UAE_SIGNS.search(text)


def find_date(text: str) -> str | None:
    """Invoice date as dd/mm/yyyy: the date after an 'invoice date / date / issued' label (not a due date),
    else the first date on the page. Month names, ISO and 2-digit years are understood."""
    mdy = _mdy(text)
    for m in re.finditer(r"(?:invoice\s*date|date\s*of\s*issue|issue\s*date|issued|dated?)\b", text, re.I):
        if re.search(r"due|delivery|ship|expiry|valid", text[max(0, m.start() - 10):m.start()], re.I):
            continue
        d = parse_date(text[m.end():].split("\n", 1)[0][:40], mdy)
        if d:
            return d.strftime("%d/%m/%Y")
    d = parse_date(text, mdy)
    return d.strftime("%d/%m/%Y") if d else None


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
        chunks = [_clean_name(ch) for ch in re.split(r"\s{3,}", l)]
        ok = []
        for c in chunks:
            if _CUST.search(c):
                break
            if _is_company(c):
                ok.append(c)
        if ok:
            out.append(max(ok, key=len))
        if _CUST.search(l):
            break
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
            plain = bool(c) and not re.search(r"\d", c) and not _CUST.search(c) and not _NOT_NAME.search(c) and len(c.split()) <= 6
            if _is_company(c) or (plain and (len(c.split()) >= 2 or "-" in c)):
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


def _name_above_address(lines: list[str]) -> str | None:
    """Layouts with no label and no company suffix: the issuer's name is the line just above its 'Address:' line."""
    for i, l in enumerate(lines):
        if i and re.match(r"address\s*:", l, re.I):
            c = _clean_name(lines[i - 1])
            if (c and re.search(r"[A-Za-z]{2}", c) and not re.search(r"\d|invoice|bill|date", c, re.I)
                    and not _CUST.search(c) and not _NOT_NAME.search(c) and not _PLAIN_BAD.search(c)
                    and len(c.split()) <= 6):
                return c
            return None
    return None


_DOC_TITLE = re.compile(r"^\s*(?:tax\s+invoice|invoice|bill|statement|receipt|quotation)\s*[:\-]?\s*$", re.I)
_PLAIN_BAD = re.compile(
    r"\b(?:date|invoice|inv|bill|statement|receipt|quotation|proforma|delivery|original|copy|page|"
    r"number|no|ref|terms|due|payment|payable|note|contact|email|phone|tel|address|vat|trn|"
    r"total|amount|subtotal|tax|thank|thanks|welcome)\b", re.I)


def _plain_candidate(l: str) -> str | None:
    c = _clean_name(l)
    if not c or not re.search(r"[A-Za-z]{2}", c) or re.match(r"^(?:mr|mrs|ms|miss)\.?\s", c, re.I):
        return None
    if re.search(r"\d|@|https?://|www\.", c, re.I) or _PLAIN_BAD.search(c) or _NOT_NAME.search(c):
        return None
    if len(c.split()) > 6:
        return None
    if len(c.split()) >= 2 or "-" in c:
        return c
    return None


def _plain_header_name(lines: list[str]) -> str | None:
    """No suffix, no label, no Address line: the issuer name is usually the first plain line under the document title."""
    start = None
    for i, l in enumerate(lines):
        if _CUST.search(l):
            break
        if _DOC_TITLE.match(l):
            start = i + 1
            break
    if start is None:
        return None
    for l in lines[start:start + 6]:
        if _CUST.search(l):
            break
        c = _plain_candidate(l)
        if c:
            return c
    return None


def _plain_header_above_title(lines: list[str]) -> str | None:
    for i, l in enumerate(lines):
        if _CUST.search(l):
            break
        if _DOC_TITLE.match(l):
            for prev in lines[:i]:
                c = _plain_candidate(prev)
                if c:
                    return c
            break
    return None


def _plain_issuer_name(lines: list[str]) -> str | None:
    for l in lines:
        for part in re.split(r"\s{3,}", l):
            if _CUST.search(part):
                return None
            c = _plain_candidate(part)
            if c:
                return c
    return None


def find_supplier(text: str) -> str | None:
    return find_supplier_detail(text)[0]


def find_supplier_detail(text: str) -> tuple[str | None, bool]:
    """(name, confident). Confident means the name came from a label, a company-suffixed header, or the payment account name. The position-based
    fallbacks (the line above 'Address:', the first plain line under the document title, ...) can pick the wrong text, so their answer is
    returned as not confident and the checks that act on the name (the FTA name check) must not raise a red flag from it.
    Supplier (issuer) name. Evidence, strongest first: an explicit 'Supplier:'/'From:' label; a company-suffixed
    name in the header (above the Bill To block) that agrees with the payment 'Account name:'; the account name
    itself when the header is unreadable or disagrees; otherwise the first company-suffixed header name."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    acc = _account_name(lines)
    lab = _labelled_supplier(lines)
    heads = _header_candidates(lines)
    if lab and acc and _key(lab) != _key(acc) and _close(lab, acc):
        return _merge_reads(lab, acc), True
    if lab and (not acc or _key(lab) == _key(acc) or not _is_company(acc) or _is_company(lab)):
        return lab, True
    if acc and _is_company(acc):
        for h in heads:
            if _key(h) == _key(acc):
                return h, True
        # OCR: the header and the account line can each carry a few misread letters. A header name that
        # nearly matches the account name is the same company: merge the two reads word by word.
        close = [h for h in heads if _close(h, acc)]
        return (_merge_reads(close[0], acc) if close else acc), True
    if heads:
        return heads[0], True
    if lab or acc:
        return (lab or acc), True
    for guess in (_name_above_address, _plain_header_name, _plain_issuer_name, _plain_header_above_title):
        name = guess(lines)
        if name:
            return name, False
    return None, True


def _clean_name(l: str) -> str:
    l = re.sub(r"^\s*[A-Za-z]?[<>\[\]()'\"|@#%*+=~‘’“”]{1,2}\s+", "", l)
    l = re.split(r"\s{3,}|\s*(?:tax\s*invoice|invoice\s*\(tax\)|invoice|inv\.|bill\s*no|reference|document\s*no|date|issue\b|due\b|serial\b|our\s+ref\b|ref(?:\.|\b))", l, flags=re.I)[0]
    return l.strip(" :")


def parse(text: str) -> Invoice:
    iban, iban_ok = find_iban(text)
    s_trn, c_trn = find_trns(text)
    sub, vat, tot = find_amounts(text)
    amounts_by_arith = find_amounts_arith(text) is not None
    supplier, supplier_ok = find_supplier_detail(text)
    inv = Invoice(
        supplier_name=supplier, supplier_trn=s_trn, customer_trn=c_trn, iban=iban,
        invoice_number=find_invoice_number(text), invoice_date=find_date(text),
        subtotal=sub, vat=vat, total=tot,
        is_tax_invoice_titled=bool(re.search(r"tax\s*invoice|invoice\s*\(tax\)", text, re.I)), raw_text=text,
    )
    inv.extra["iban_confident"] = iban_ok
    inv.extra["amounts_confident"] = amounts_by_arith
    inv.extra["supplier_confident"] = supplier_ok
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
