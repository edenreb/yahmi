"""Yahmi's real FTA client run end to end against the simulated gateway (tools/fake_fta_gateway.py), without sockets."""
import os
import sys

from fastapi.testclient import TestClient

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))
import fake_fta_gateway as sim  # noqa: E402

from yahmi import app as yapp  # noqa: E402
from yahmi.registry import FtaTrnClient, check_trn_registry  # noqa: E402

GW = "http://sim.local"
ENV = {
    "YAHMI_FTA_BASE_URL": f"{GW}/gateway/validateTRNDetails_FTAX/1.0",
    "YAHMI_FTA_TOKEN_URL": f"{GW}/invoke/pub.apigateway.oauth2/getAccessToken",
    "YAHMI_FTA_API_KEY": sim.DEMO_API_KEY,
    "YAHMI_FTA_CLIENT_ID": sim.DEMO_CLIENT[0],
    "YAHMI_FTA_CLIENT_SECRET": sim.DEMO_CLIENT[1],
}
FX = os.path.join(ROOT, "tests", "fixtures")


def client(env=ENV):
    return FtaTrnClient(env=dict(env), http=TestClient(sim.app, base_url=GW))


def test_simulated_results_are_labelled_and_never_cite_the_fta():
    c = client()
    assert c.simulated
    for trn, name in [("100384920571003", "Falcon Building Materials LLC"), ("100555512340003", "Falcon Building Materials LLC"),
                      ("100999999999999", "Anyone LLC")]:
        for f in check_trn_registry(name, trn, c):
            assert f.message.startswith("SIMULATION:") and "NOT the Federal Tax Authority" in f.source


def test_name_checks_through_the_simulator():
    c = client()
    assert check_trn_registry("Falcon Building Materials LLC", "100384920571003", c)[0].level == "green"
    red = check_trn_registry("Falcon Building Materials LLC", "100555512340003", c)[0]
    assert red.level == "red" and "Blue Creek Logistics LLC" in red.message
    assert check_trn_registry("Falcon Building Materials LLC", "100999999999999", c)[0].level == "amber"   # not in the simulated register
    assert check_trn_registry("Al Noor Trading & Contracting LLC", "100222233340003", c)[0].level in ("amber", "red")


def test_bad_credentials_are_no_answer_not_a_verdict():
    bad = dict(ENV, YAHMI_FTA_CLIENT_SECRET="wrong")
    assert check_trn_registry("Falcon Building Materials LLC", "100384920571003", client(bad))[0].level == "info"


def test_body_mode_also_works():
    assert check_trn_registry("Falcon Building Materials LLC", "100384920571003", client(dict(ENV, YAHMI_FTA_TRN_IN="body")))[0].level == "green"


def test_default_gateway_is_the_official_host_and_not_simulated():
    assert not FtaTrnClient(env={}).simulated


def test_whole_app_flags_a_trn_that_belongs_to_someone_else(monkeypatch):
    monkeypatch.setattr(yapp, "FTA", client())
    api = TestClient(yapp.app)
    with open(os.path.join(FX, "wrong_trn.pdf"), "rb") as f:
        out = api.post("/api/check", files={"invoice": ("wrong_trn.pdf", f)}, data={"access_code": "c-sim-wrong"}).json()
    reg = [x for x in out["findings"] if x["check"] == "trn_registry"]
    assert out["verdict"] == "stop" and reg and reg[0]["level"] == "red" and reg[0]["message"].startswith("SIMULATION:")
    with open(os.path.join(FX, "genuine_new.pdf"), "rb") as f:
        ok = api.post("/api/check", files={"invoice": ("genuine_new.pdf", f)}, data={"access_code": "c-sim-ok"}).json()
    assert [x["level"] for x in ok["findings"] if x["check"] == "trn_registry"] == ["green"]
