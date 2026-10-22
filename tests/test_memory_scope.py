"""Known sender domains are scoped to one business (they used to be read across all businesses)."""
from yahmi.memory import Memory


def test_known_domains_never_cross_businesses(tmp_path):
    m = Memory(str(tmp_path / "m.db"))
    m.record("business A", "trn:100000000000001", "AE070331234567890123456", "falconbm.ae")
    m.record("business B", "trn:100000000000002", "AE950330000019284756302", "bluecreek.ae")
    assert m.known_domains("business A") == {"falconbm.ae"}
    assert m.known_domains("business B") == {"bluecreek.ae"}
    assert m.known_domains("business C") == set()


def test_a_domain_known_to_one_business_is_still_new_to_another(tmp_path):
    from yahmi.email_checks import check_email, parse
    m = Memory(str(tmp_path / "m.db"))
    m.record("business A", "trn:100000000000001", "AE070331234567890123456", "newdomain-co.com")
    mail = "From: Rashid <a@newdomain-co.com>\nSubject: Invoice\n\nOur bank details have changed. Please pay into our new account today.\n"
    for biz, expect in (("business A", False), ("business B", True)):
        got = {f.check for f in check_email(parse(mail), m.known_domains(biz), 0.1, "Falcon Building Materials LLC")}
        assert ("new_sender" in got) is expect
