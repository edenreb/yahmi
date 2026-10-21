"""Official TRN check: does this Tax Registration Number belong to the supplier named on the invoice?

Uses the Federal Tax Authority's validateTRNDetails_FTAX service on the UAE API Marketplace (Government Service Bus).
Request and response shapes come from the service specification and sample document published with the API
(fta-api-docs/, not committed). Access needs an approved application: set YAHMI_FTA_API_KEY (GW-APIKey),
YAHMI_FTA_CLIENT_ID and YAHMI_FTA_CLIENT_SECRET in the environment. Without them the check reports that it is not connected
and never guesses. The service allows 500 requests a day, so results are cached and calls are capped.

Use of the returned data is limited to the purpose the data owner approved: it is compared with the invoice and shown to the
user who sent that invoice, nothing else.
"""
from __future__ import annotations

import os
import re
import time
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
from rapidfuzz import fuzz

from .rules import Finding

SOURCE = "Federal Tax Authority TRN register (UAE API Marketplace: validateTRNDetails_FTAX)"
SIM_SOURCE = "SIMULATED registry (demo data on a local test gateway; NOT the Federal Tax Authority)"
OFFICIAL_HOST = "api.gsb.government.ae"
BASE = "https://api.gsb.government.ae/gateway/validateTRNDetails_FTAX/1.0"
PATH = "/api/prc/trn/v1/gsbvalidatetrn"
TOKEN_URL = "https://api.gsb.government.ae/invoke/pub.apigateway.oauth2/getAccessToken"
DAILY_LIMIT = 450       # the service allows 500 requests a day; keep a margin
CACHE_SECONDS = 24 * 3600
MATCH_GREEN, MATCH_AMBER = 85, 60   # name similarity bands, fixed in advance (do not re-pick on test data)

_LEGAL = {"llc", "fze", "fzco", "fz", "pjsc", "est", "establishment", "co", "company", "ltd", "limited", "inc", "the"}
_AR_STRIP = re.compile(r"[ً-ٰٟـ]")  # diacritics and tatweel


@dataclass
class TrnResult:
    status: str                      # found | not_found | unavailable
    name_en: str | None = None
    name_ar: str | None = None
    detail: str = ""


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = _AR_STRIP.sub("", s).replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي").replace("ة", "ه")
    s = re.sub(r"\bl\.?\s?l\.?\s?c\b\.?", "llc", s.lower())
    s = re.sub(r"[^\w\s]", " ", s.replace("&", " and "))
    words = [w for w in s.split() if w not in _LEGAL]
    return " ".join(words)


def _has_arabic(s: str) -> bool:
    return len(re.findall(r"[؀-ۿ]", s or "")) >= 3


def name_similarity(invoice_name: str, result: TrnResult) -> int:
    """0-100 similarity between the supplier name on the invoice and the registered name (English or Arabic)."""
    best = 0
    for reg in (result.name_en, result.name_ar):
        if reg and _has_arabic(reg) == _has_arabic(invoice_name):
            a, b = _norm(invoice_name), _norm(reg)
            if a and b:
                best = max(best, int(fuzz.token_sort_ratio(a, b)), int(fuzz.ratio(a.replace(" ", ""), b.replace(" ", ""))))  # not token_set: an extra word must lower the score
    return best


class FtaTrnClient:
    def __init__(self, env=None, http=requests, clock=time.time):
        self.env, self.http, self.clock = env if env is not None else os.environ, http, clock
        self._token: tuple[str, float] | None = None
        self._cache: dict[str, tuple[float, TrnResult]] = {}
        self._day: tuple[int, int] = (0, 0)  # (day number, calls today)

    @property
    def base_url(self) -> str:
        return (self.env.get("YAHMI_FTA_BASE_URL") or BASE).rstrip("/")

    @property
    def token_url(self) -> str:
        return self.env.get("YAHMI_FTA_TOKEN_URL") or TOKEN_URL

    @property
    def simulated(self) -> bool:
        """True when the gateway is anything other than the official government host (the demo simulator, a test double)."""
        return urlparse(self.base_url).hostname != OFFICIAL_HOST

    @property
    def configured(self) -> bool:
        return all(self.env.get(k) for k in ("YAHMI_FTA_API_KEY", "YAHMI_FTA_CLIENT_ID", "YAHMI_FTA_CLIENT_SECRET"))

    def _bearer(self) -> str | None:
        if self._token and self._token[1] > self.clock() + 30:
            return self._token[0]
        data = {"grant_type": "client_credentials"}
        if self.env.get("YAHMI_FTA_SCOPE"):
            data["scope"] = self.env["YAHMI_FTA_SCOPE"]
        r = self.http.post(self.token_url, data=data, auth=(self.env["YAHMI_FTA_CLIENT_ID"], self.env["YAHMI_FTA_CLIENT_SECRET"]), timeout=10)
        if r.status_code != 200:
            return None
        j = r.json()
        self._token = (j["access_token"], self.clock() + float(j.get("expires_in", 300)))
        return self._token[0]

    def _count_call(self) -> bool:
        day = int(self.clock() // 86400)
        n = self._day[1] if self._day[0] == day else 0
        if n >= DAILY_LIMIT:
            return False
        self._day = (day, n + 1)
        return True

    def lookup(self, trn: str) -> TrnResult:
        trn = re.sub(r"\D", "", trn or "")
        if not self.configured:
            return TrnResult("unavailable", detail="not connected")
        hit = self._cache.get(trn)
        if hit and hit[0] > self.clock():
            return hit[1]
        if not self._count_call():
            return TrnResult("unavailable", detail="daily limit reached")
        try:
            bearer = self._bearer()
            if not bearer:
                return TrnResult("unavailable", detail="could not get an access token")
            # The sample error text says "query parameter TRN" while the spec table lists a body field; the query form
            # is the default and YAHMI_FTA_TRN_IN=body switches it. Confirm with the Try API page once credentials exist.
            kw = {"json": {"TRN": trn}} if self.env.get("YAHMI_FTA_TRN_IN") == "body" else {"params": {"TRN": trn}}
            r = self.http.post(self.base_url + PATH, headers={"content-type": "application/json", "accept": "application/json",
                                                     "GW-APIKey": self.env["YAHMI_FTA_API_KEY"], "Authorization": f"Bearer {bearer}"},
                               timeout=10, **kw)
        except requests.RequestException as e:
            return TrnResult("unavailable", detail=type(e).__name__)
        if r.status_code == 200:
            res = self._parse(r)
        elif r.status_code in (400, 404):
            res = TrnResult("not_found", detail=f"HTTP {r.status_code}")  # a 15-digit TRN was sent, so the register has no match
        else:
            return TrnResult("unavailable", detail=f"HTTP {r.status_code}")  # 401, 408, 5xx: not an answer about this TRN
        self._cache[trn] = (self.clock() + CACHE_SECONDS, res)
        return res

    @staticmethod
    def _parse(r) -> TrnResult:
        try:
            j = r.json()
        except ValueError:
            return TrnResult("unavailable", detail="unreadable response")
        item = (j[0] if isinstance(j, list) and j else j) if j else None
        if not isinstance(item, dict):
            return TrnResult("not_found", detail="empty response")
        low = {k.lower(): v for k, v in item.items()}
        en, ar = (low.get("nameen") or "").strip() or None, (low.get("namear") or "").strip() or None
        return TrnResult("found", en, ar) if (en or ar) else TrnResult("not_found", detail="no name returned")


def check_trn_registry(supplier_name: str | None, trn: str | None, client: FtaTrnClient) -> list[Finding]:
    """Findings from comparing the invoice's supplier name with the name the FTA has registered for the TRN."""
    digits = re.sub(r"\D", "", trn or "")
    if len(digits) != 15:
        return []  # no usable TRN: check_trn already says so
    if not client.configured:
        return [Finding("trn_registry", "info", "The official FTA name check for this TRN is not connected yet in this build.", SOURCE)]
    return [_labelled(f, client.simulated) for f in _compare(supplier_name, digits, client)]


def _labelled(f: Finding, simulated: bool) -> Finding:
    """A result from the demo simulator must never read like an FTA result."""
    if not simulated:
        return f
    return Finding(f.check, f.level, "SIMULATION: " + f.message, SIM_SOURCE)


def _compare(supplier_name: str | None, digits: str, client: FtaTrnClient) -> list[Finding]:
    res = client.lookup(digits)
    if res.status == "unavailable":
        return [Finding("trn_registry", "info", "The FTA TRN service did not answer, so the supplier name was not checked against it.", SOURCE)]
    if res.status == "not_found":
        return [Finding("trn_registry", "amber", "The FTA TRN service returned no registration for this TRN. Ask the supplier for their TRN certificate before paying.", SOURCE)]
    reg = res.name_en or res.name_ar
    if not supplier_name:
        return [Finding("trn_registry", "amber", f"This TRN is registered to {reg}. We could not read the supplier name on the invoice to compare.", SOURCE)]
    score = name_similarity(supplier_name, res)
    if score >= MATCH_GREEN:
        return [Finding("trn_registry", "green", f"The TRN is registered to {reg}, which matches the supplier name on the invoice.", SOURCE)]
    if score >= MATCH_AMBER:
        return [Finding("trn_registry", "amber", f"The TRN is registered to {reg}; the invoice says {supplier_name}. The names are similar but not the same, so confirm with the supplier.", SOURCE)]
    return [Finding("trn_registry", "red", f"The TRN on this invoice is registered to {reg}, not {supplier_name}. Verify with the supplier on a number you already trust.", SOURCE)]
