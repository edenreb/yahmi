"""Email metadata checks: what the headers say about who really sent the email that delivered an invoice.

Rules, not a model (public fraud-email sets carry no headers, so there is nothing to train on). Each finding cites the header it came
from. These checks run only when the full email (with headers) is available; a plain forwarded text has none, and the verdict says so.

1. Authentication results (SPF / DKIM / DMARC) recorded by the receiving mail server.
2. Display-name spoofing: the name shown is the supplier's, the address is on a domain never seen from that supplier.
3. Mismatched envelope: Return-Path or Message-ID on a different domain than From, without a passing DMARC.
4. First email from a sender domain that asks to change bank details.
5. How recently the sender domain was registered (public RDAP record from the registry). On by default (YAHMI_DOMAIN_AGE=0 switches it off);
   it is the only check that contacts anything outside the machine, and only the domain name is sent.
"""
from __future__ import annotations

import os
import re
import time
from email.utils import parseaddr

from rapidfuzz import fuzz

from .rules import Finding

SRC_AUTH = "Email headers: Authentication-Results added by the receiving mail server"
SRC_HDR = "Email headers"
_SLD = {"co.ae", "com.ae", "net.ae", "org.ae", "gov.ae", "ac.ae", "sch.ae", "co.uk", "com.au", "co.in"}
_LEGAL = {"llc", "fze", "fzco", "fz", "pjsc", "est", "establishment", "co", "company", "ltd", "limited", "inc", "the", "and", "trading"}
RESULT = re.compile(r"\b(spf|dkim|dmarc)\s*=\s*(pass|fail|softfail|neutral|none|temperror|permerror|policy)", re.I)
NEW_DOMAIN_DAYS = 30


def org_domain(d: str | None) -> str | None:
    if not d:
        return None
    parts = d.lower().strip(".").split(".")
    last2 = ".".join(parts[-2:])
    return ".".join(parts[-3:]) if len(parts) >= 3 and last2 in _SLD else last2


def _domain(value: str | None) -> str | None:
    a = parseaddr(value or "")[1]
    if "@" in a:
        return a.rsplit("@", 1)[1].lower().strip(">")
    m = re.search(r"@([\w.\-]+)", value or "")
    return m.group(1).lower() if m else None


def auth_results(parsed: dict) -> dict[str, str]:
    """{'spf': 'pass', 'dkim': 'fail', 'dmarc': 'fail'} from the top-most Authentication-Results header (the one our own provider added),
    falling back to Received-SPF. Lower ones can be forged by the sender, so they are ignored."""
    res: dict[str, str] = {}
    h = parsed.get("headers") or {}
    ar = h.get("authentication_results") or []
    if ar:
        for k, v in RESULT.findall(ar[0]):
            res.setdefault(k.lower(), v.lower())
    spf = h.get("received_spf") or ""
    m = re.match(r"\s*(pass|fail|softfail|neutral|none|temperror|permerror)", spf, re.I)
    if m and "spf" not in res:
        res["spf"] = m.group(1).lower()
    return res


def _norm_name(s: str) -> str:
    return " ".join(w for w in re.sub(r"[^a-z0-9؀-ۿ ]", " ", (s or "").lower()).split() if w not in _LEGAL)


def check_headers(parsed: dict, known_domains: set[str] | None, supplier_name: str | None, bank_change_cue: bool,
                  domain_age=None) -> list[Finding]:
    out: list[Finding] = []
    h = parsed.get("headers")
    if not h:
        # plain text or a forward that lost its headers: say so once, never guess
        return [Finding("email_headers", "info", "No email headers were received, so the sender's authentication, return path and domain were not checked. "
                        "Forward the email as an attachment or upload the .eml file to include them.", SRC_HDR)]
    fd = _domain(parsed.get("from"))
    fo = org_domain(fd)
    known_org = {org_domain(d) for d in (known_domains or set())}

    # 1. authentication results
    res = auth_results(parsed)
    if not res:
        out.append(Finding("auth", "info", "The headers carry no SPF, DKIM or DMARC result, so the sender could not be authenticated.", SRC_HDR))
    else:
        shown = ", ".join(f"{k.upper()} {v}" for k, v in res.items())
        if res.get("dmarc") == "fail":
            out.append(Finding("auth", "red", f"The email failed DMARC ({shown}). The sender may not be who it claims to be.", SRC_AUTH))
        elif any(v in ("fail", "softfail", "permerror") for v in res.values()):
            out.append(Finding("auth", "amber", f"Sender authentication did not fully pass ({shown}).", SRC_AUTH))
        elif res.get("dmarc") == "pass" or (res.get("spf") == "pass" and res.get("dkim") == "pass"):
            out.append(Finding("auth", "green", f"The sending domain passed authentication ({shown}). This proves the domain, not the intent: a fraudster's own domain can pass too.", SRC_AUTH))
        else:
            out.append(Finding("auth", "info", f"Sender authentication was incomplete ({shown}).", SRC_AUTH))

    # 2. display-name spoofing
    display = parseaddr(parsed.get("from") or "")[0]
    if display and supplier_name and fo and fo not in known_org and fo not in {org_domain(d) for d in FREE_FALLBACK}:
        a, b = _norm_name(display), _norm_name(supplier_name)
        if a and b and (fuzz.token_set_ratio(a, b) >= 85 or b in a):
            out.append(Finding("display_name", "amber", f"The sender calls itself \"{display}\" (the supplier's name) but writes from {fd}, a domain you have not seen from this supplier.", SRC_HDR))

    # 3. envelope mismatches (weak on their own: mailing services do this legitimately, so only when DMARC did not pass)
    if res.get("dmarc") != "pass" and fo:
        odd = []
        rp = org_domain(_domain(h.get("return_path")))
        mid = org_domain(_domain(h.get("message_id")))
        if rp and rp != fo:
            odd.append(f"Return-Path {rp}")
        if mid and mid != fo:
            odd.append(f"Message-ID {mid}")
        if odd:
            out.append(Finding("envelope", "amber", f"The email says it is from {fd} but was sent via {' and '.join(odd)}. Check that this is really your supplier.", SRC_HDR))

    # 4. first email from this domain that asks to change bank details
    if fo and bank_change_cue and fo not in known_org and fo not in {org_domain(d) for d in FREE_FALLBACK}:
        out.append(Finding("new_sender", "amber", f"This is the first email you have had from {fd} and it asks to change bank details.", "Email headers vs your history"))

    # 5. optional domain age
    if domain_age and fd:
        days = domain_age(fo)
        if days is not None and days < NEW_DOMAIN_DAYS:
            out.append(Finding("domain_age", "amber", f"The sender's domain {fo} was registered only {days} day(s) ago.", "Public RDAP domain registration record"))
    return out


FREE_FALLBACK = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com", "icloud.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "mail.com", "yandex.com"}


class DomainAge:
    """Registration age of a domain in days from the public RDAP record, asked of the registry itself (found through the IANA bootstrap file),
    not through a third-party relay. On by default; YAHMI_DOMAIN_AGE=0 switches it off. Only the domain name is sent. Top-level domains
    without an RDAP service (notably .ae) have no answer and trigger no request. Any failure is 'no answer'."""

    BOOTSTRAP = "https://data.iana.org/rdap/dns.json"

    def __init__(self, env=None, http=None, clock=time.time):
        self.env = os.environ if env is None else env
        self.http, self.clock = http, clock
        self._cache: dict[str, tuple[float, int | None]] = {}
        self._servers: tuple[float, dict[str, str]] | None = None

    @property
    def enabled(self) -> bool:
        return self.env.get("YAHMI_DOMAIN_AGE", "1") != "0"

    def _get(self, url):
        http = self.http
        if http is None:
            import requests as http
        return http.get(url, timeout=8, headers={"accept": "application/rdap+json, application/json"})

    def _server(self, tld: str) -> str | None:
        if not self._servers or self._servers[0] < self.clock():
            try:
                r = self._get(self.BOOTSTRAP)
                table = {t: urls[0] for tlds, urls in r.json()["services"] for t in tlds} if r.status_code == 200 else {}
            except Exception:
                table = {}
            self._servers = (self.clock() + 86400, table)
        return self._servers[1].get(tld)

    def __call__(self, domain: str) -> int | None:
        if not self.enabled or not domain:
            return None
        hit = self._cache.get(domain)
        if hit and hit[0] > self.clock():
            return hit[1]
        days = self._lookup(domain)
        self._cache[domain] = (self.clock() + 7 * 86400, days)
        return days

    def _lookup(self, domain: str) -> int | None:
        import datetime
        base = self._server(domain.rsplit(".", 1)[-1])
        if not base:
            return None
        try:
            r = self._get(base.rstrip("/") + "/domain/" + domain)
            if r.status_code != 200:
                return None
            for ev in r.json().get("events", []):
                if ev.get("eventAction") == "registration":
                    d = datetime.datetime.fromisoformat(ev["eventDate"].replace("Z", "+00:00"))
                    return max(0, int((datetime.datetime.now(datetime.timezone.utc) - d).days))
        except Exception:
            return None
        return None
