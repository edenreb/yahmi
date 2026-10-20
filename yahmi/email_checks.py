"""Checks on the email that delivered an invoice: sender spoofing, lookalike domains, and the BEC classifier."""
from __future__ import annotations

import email
import re
from email.utils import parseaddr

from rapidfuzz.distance import Levenshtein

from .rules import Finding

RED_THRESHOLD = 0.80  # leave-one-source-out on 348 real emails: 118/212 frauds, 2/136 legit flagged
FREE_MAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com", "icloud.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "mail.com", "yandex.com"}
HOMOGLYPHS = [("rn", "m"), ("vv", "w"), ("0", "o"), ("1", "l"), ("i", "l"), ("|", "l")]


def parse(raw: str) -> dict:
    """Accepts a raw RFC 822 email or plain pasted text. Returns from/reply_to/subject/body."""
    if re.search(r"^(from|subject|reply-to):", raw, re.I | re.M):
        msg = email.message_from_string(raw)
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body += part.get_payload(decode=True).decode(errors="ignore")
        else:
            p = msg.get_payload(decode=True)
            body = p.decode(errors="ignore") if p else str(msg.get_payload())
        return {"from": msg.get("From", ""), "reply_to": msg.get("Reply-To", ""), "subject": msg.get("Subject", ""), "body": body}
    return {"from": "", "reply_to": "", "subject": "", "body": raw}


def domain_of(addr: str) -> str | None:
    a = parseaddr(addr)[1]
    return a.split("@")[-1].lower() if "@" in a else None


def skeleton(d: str) -> str:
    d = d.lower()
    for a, b in HOMOGLYPHS:
        d = d.replace(a, b)
    return re.sub(r"[-_.]", "", d.rsplit(".", 1)[0] if "." in d else d)


def lookalike(d: str, known: set[str]) -> str | None:
    for k in known:
        if d == k:
            return None
    for k in known:
        if skeleton(d) == skeleton(k) or Levenshtein.distance(d.split(".")[0], k.split(".")[0]) <= 2:
            return k
    return None


def check_email(parsed: dict, known_domains: set[str] | None = None, bec_score: float | None = None) -> list[Finding]:
    out: list[Finding] = []
    known_domains = known_domains or set()
    fd, rd = domain_of(parsed.get("from", "")), domain_of(parsed.get("reply_to", ""))
    if fd and rd and fd != rd:
        out.append(Finding("reply_to", "red", f"Replies go to {rd}, not the sender's domain {fd}. Fraudsters do this to receive your reply.", "Email headers"))
    if fd:
        k = lookalike(fd, known_domains)
        if k:
            out.append(Finding("lookalike", "red", f"The sender domain {fd} imitates {k}, which this supplier normally uses.", "Email headers vs your history"))
        if fd in FREE_MAIL:
            out.append(Finding("freemail", "amber", f"The invoice came from a free personal address ({fd}), not a company domain.", "Email headers"))
    text = (parsed.get("subject") or "") + "\n" + (parsed.get("body") or "")
    from .cues import cue_hits, cue_score
    names = {"bank_change": "asks to pay a new or changed account", "excuse": "gives an excuse such as an audit or a frozen account",
             "pressure": "pushes you to pay quickly", "secrecy": "asks you to keep it confidential",
             "no_phone": "says they can't take calls or to reply by email only", "money_ask": "asks for a transfer"}
    hits = [names[k] for k, v in cue_hits(text).items() if v]
    why = (" It " + ", ".join(hits) + ".") if hits else ""
    src = "Yahmi AI fraud-email model, tested on 348 real emails"
    if bec_score is not None and bec_score >= RED_THRESHOLD:
        out.append(Finding("bec", "red", f"This email reads like known payment-fraud emails (score {bec_score:.2f}).{why}", src))
    elif bec_score is not None and bec_score >= 0.62:
        out.append(Finding("bec", "amber", f"Some wording resembles known fraud emails (score {bec_score:.2f}).{why} Check the other warnings before paying.", src))
    else:
        out.append(Finding("bec", "green", "The wording does not match known fraud patterns. Fraudsters can still write normal-looking emails, so the bank-detail checks matter most.", "Yahmi fraud-pattern rules and AI wording model"))
    return out
