"""Email metadata checks on invented emails (no real people, domains or addresses beyond example-style names)."""
import datetime
import os

from fastapi.testclient import TestClient

from conftest import FIXTURES
from yahmi.app import app
from yahmi.email_checks import check_email, parse
from yahmi.email_meta import DomainAge, org_domain

SUP = "Falcon Building Materials LLC"
KNOWN = {"falconbm.ae"}
BODY = "Dear team,\n\nPlease find the invoice attached.\n\nKind regards,\nRashid\n"


def raw(frm="Rashid <accounts@falconbm.ae>", extra="", body=BODY):
    return f"From: {frm}\n{extra}Subject: Invoice\n\n{body}"


def checks(text, known=KNOWN, supplier=SUP, age=None):
    return {f.check: f for f in check_email(parse(text), set(known), 0.1, supplier, age)}


def test_dmarc_fail_is_red_and_cites_the_header():
    f = checks(raw(extra="Authentication-Results: mx.example.net; spf=pass; dkim=none; dmarc=fail (p=reject)\n"))["auth"]
    assert f.level == "red" and "DMARC" in f.message and "Authentication-Results" in f.source


def test_pass_is_green_but_says_it_proves_the_domain_only():
    f = checks(raw(extra="Authentication-Results: mx.example.net; spf=pass; dkim=pass; dmarc=pass\n"))["auth"]
    assert f.level == "green" and "not the intent" in f.message


def test_softfail_is_amber_and_missing_results_are_info():
    assert checks(raw(extra="Authentication-Results: mx.example.net; spf=softfail; dkim=pass\n"))["auth"].level == "amber"
    assert checks(raw())["auth"].level == "info"
    assert checks(raw(extra="Received-SPF: fail (domain does not designate this sender)\n"))["auth"].level == "amber"


def test_only_the_top_authentication_header_counts():
    top_fail = "Authentication-Results: mx.example.net; dmarc=fail\nAuthentication-Results: forged.example.org; dmarc=pass\n"
    top_pass = "Authentication-Results: mx.example.net; dmarc=pass\nAuthentication-Results: forged.example.org; dmarc=fail\n"
    assert checks(raw(extra=top_fail))["auth"].level == "red"
    assert checks(raw(extra=top_pass))["auth"].level == "green"


def test_plain_text_says_headers_were_not_checked():
    f = checks("Hello, please pay the attached invoice.")["email_headers"]
    assert f.level == "info" and "upload the .eml" in f.message
    assert "auth" not in checks("Hello, please pay the attached invoice.")


def test_display_name_spoofing_needs_an_unknown_domain():
    spoof = checks(raw(frm=f"{SUP} <billing@falcon-bm-pay.com>"))
    assert spoof["display_name"].level == "amber" and "falcon-bm-pay.com" in spoof["display_name"].message
    assert "display_name" not in checks(raw(frm=f"{SUP} <billing@mail.falconbm.ae>"))      # the supplier's own domain
    assert "display_name" not in checks(raw(frm="Rashid <billing@falcon-bm-pay.com>"))     # a different display name


def test_envelope_mismatch_only_matters_without_a_dmarc_pass():
    odd = "Return-Path: <bounce@bulk-mailer.net>\nMessage-ID: <1@other-host.org>\n"
    f = checks(raw(extra=odd))["envelope"]
    assert f.level == "amber" and "bulk-mailer.net" in f.message
    assert "envelope" not in checks(raw(extra=odd + "Authentication-Results: mx.example.net; dmarc=pass\n"))
    assert "envelope" not in checks(raw(extra="Return-Path: <x@falconbm.ae>\nMessage-ID: <1@mail.falconbm.ae>\n"))


def test_first_email_from_a_domain_that_asks_for_new_bank_details():
    ask = "Our bank details have changed. Please pay the invoice into our new account today.\n"
    f = checks(raw(frm="Rashid <accounts@newdomain-co.com>", body=ask))
    assert f["new_sender"].level == "amber"
    assert "new_sender" not in checks(raw(frm="Rashid <accounts@falconbm.ae>", body=ask))
    assert "new_sender" not in checks(raw(frm="Rashid <accounts@newdomain-co.com>"))        # no bank-change wording
    assert "new_sender" not in checks(raw(frm="Rashid <rashid@gmail.com>", body=ask))       # free mail has its own warning


class Rdap:
    """Fake of the IANA bootstrap file plus a registry RDAP server."""

    def __init__(self, days, status=200, tlds=("com",)):
        self.calls, self.days, self.status, self.tlds = [], days, status, tlds

    def get(self, url, **kw):
        self.calls.append(url)
        r = type("R", (), {})()
        if url.endswith("dns.json"):
            r.status_code, r.json = 200, (lambda: {"services": [[list(self.tlds), ["https://rdap.registry.test/v1/"]]]})
            return r
        d = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=self.days)).isoformat()
        r.status_code, r.json = self.status, (lambda: {"events": [{"eventAction": "registration", "eventDate": d}]})
        return r

    def registry_calls(self):
        return [u for u in self.calls if "rdap.registry.test" in u]


def test_domain_age_can_be_switched_off_and_then_never_calls_out():
    http = Rdap(3)
    assert DomainAge(env={"YAHMI_DOMAIN_AGE": "0"}, http=http)("newdomain-co.com") is None and not http.calls


def test_tlds_without_rdap_get_no_registry_request():
    http = Rdap(3, tlds=("com",))
    assert DomainAge(env={}, http=http)("falconbm.ae") is None and not http.registry_calls()


def test_new_domain_is_amber_asked_of_the_registry_cached_and_failures_are_silent():
    http = Rdap(5)
    age = DomainAge(env={}, http=http)
    f = checks(raw(frm="Rashid <a@newdomain-co.com>"), age=age)["domain_age"]
    assert f.level == "amber" and "5 day" in f.message and "RDAP" in f.source
    assert http.registry_calls() == ["https://rdap.registry.test/v1/domain/newdomain-co.com"]    # the registry, not a relay
    checks(raw(frm="Rashid <a@newdomain-co.com>"), age=age)
    assert len(http.registry_calls()) == 1                                                       # second answer from the cache
    assert "domain_age" not in checks(raw(frm="Rashid <a@olddomain.com>"), age=DomainAge(env={}, http=Rdap(900)))
    assert "domain_age" not in checks(raw(frm="Rashid <a@x-co.com>"), age=DomainAge(env={}, http=Rdap(5, status=404)))


def test_org_domain():
    assert org_domain("mail.falconbm.co.ae") == "falconbm.co.ae" and org_domain("a.b.example.com") == "example.com" and org_domain(None) is None


def test_whole_app_stops_on_a_dmarc_fail():
    client = TestClient(app)
    text = raw(extra="Authentication-Results: mx.example.net; spf=fail; dkim=fail; dmarc=fail\n")
    with open(os.path.join(FIXTURES, "genuine_new.pdf"), "rb") as f:
        out = client.post("/api/check", files={"invoice": ("g.pdf", f)}, data={"email_text": text, "access_code": "c-meta"}).json()
    assert out["verdict"] == "stop" and any(x["check"] == "auth" and x["level"] == "red" for x in out["findings"])


def test_html_only_multipart_email_keeps_its_text():
    from yahmi.email_checks import parse
    raw = ("From: Accounts <a@supplier.example>\nSubject: New bank details\nMIME-Version: 1.0\n"
           "Content-Type: multipart/mixed; boundary=B\n\n"
           "--B\nContent-Type: text/html; charset=utf-8\n\n<p>Please pay to our <b>new</b> account.<script>x()</script></p>\n"
           "--B\nContent-Type: text/plain; name=note.txt\nContent-Disposition: attachment; filename=note.txt\n\nattached text\n--B--\n")
    body = parse(raw)["body"]
    assert "new account" in body and "x()" not in body and "attached text" not in body
