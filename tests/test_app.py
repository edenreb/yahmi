import os

from fastapi.testclient import TestClient

from conftest import FIXTURES
from yahmi import whatsapp
from yahmi.app import app
from yahmi.email_checks import lookalike
from yahmi.memory import h

client = TestClient(app)
BIZ = "Test Interiors LLC"


def fixture(name):
    return open(os.path.join(FIXTURES, name), "rb")


def seed():
    files = [("files", fixture(f"past/past_{i}.pdf")) for i in (1, 2, 3)]
    r = client.post("/api/history", files=files, data={"access_code": "c-biz", "email_domain": "falconbm.ae"})
    assert len(r.json()["added"]) == 3


def test_genuine_passes_and_fraud_stops():
    seed()
    ok = client.post("/api/check", files={"invoice": fixture("genuine_new.pdf")},
                     data={"email_text": open(os.path.join(FIXTURES, "email_genuine.txt")).read(), "access_code": "c-biz"}).json()
    assert ok["verdict"] == "ok"
    bad = client.post("/api/check", files={"invoice": fixture("fraud_new.pdf")},
                      data={"email_text": open(os.path.join(FIXTURES, "email_fraud.txt")).read(), "access_code": "c-biz"}).json()
    assert bad["verdict"] == "stop"
    checks = {f["check"] for f in bad["findings"] if f["level"] == "red"}
    assert {"history", "reply_to", "lookalike"} <= checks


def test_new_account_is_amber_for_new_business():
    r = client.post("/api/check", files={"invoice": fixture("genuine_new.pdf")}, data={"access_code": "c-new"}).json()
    assert any(f["check"] == "history" and f["level"] == "amber" for f in r["findings"])


def test_lookalike_domains():
    assert lookalike("falconbrn.ae", {"falconbm.ae"}) == "falconbm.ae"
    assert lookalike("falconbm.ae", {"falconbm.ae"}) is None
    assert lookalike("otherco.ae", {"falconbm.ae"}) is None


def test_keyed_hash_hides_values():
    assert h("AE070331234567890123456") != h("AE070331234567890123457")
    assert "0331234567890123456" not in h("AE070331234567890123456")


class FakeGraph:
    def __init__(self):
        self.sent = []

    def download(self, media_id):
        return open(os.path.join(FIXTURES, media_id), "rb").read()

    def send(self, to, body):
        self.sent.append((to, body))


def wa(msg):
    return {"entry": [{"changes": [{"value": {"messages": [msg]}}]}]}


def test_whatsapp_flow(monkeypatch):
    fake = FakeGraph()
    monkeypatch.setattr(whatsapp, "GRAPH_CLIENT", fake)
    phone = "971500000001"
    for i in (1, 2, 3):
        client.post("/whatsapp/webhook", json=wa({"from": phone, "type": "document", "document": {"id": f"past/past_{i}.pdf", "mime_type": "application/pdf", "caption": "paid"}}))
    assert all("Added" in b for _, b in fake.sent[-3:])
    client.post("/whatsapp/webhook", json=wa({"from": phone, "type": "text", "text": {"body": open(os.path.join(FIXTURES, "email_fraud.txt")).read()}}))
    client.post("/whatsapp/webhook", json=wa({"from": phone, "type": "document", "document": {"id": "fraud_new.pdf", "mime_type": "application/pdf"}}))
    assert fake.sent[-1][1].startswith("🛑 STOP")
    client.post("/whatsapp/webhook", json=wa({"from": phone, "type": "document", "document": {"id": "genuine_new.pdf", "mime_type": "application/pdf"}}))
    assert fake.sent[-1][1].startswith("✅")


def test_whatsapp_verify(monkeypatch):
    monkeypatch.setenv("WA_VERIFY_TOKEN", "abc")
    r = client.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "abc", "hub.challenge": "42"})
    assert r.text == "42"
    assert client.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "no"}).status_code == 403
