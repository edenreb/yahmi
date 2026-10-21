"""The official TRN check, run against a fake of the FTA gateway built from the published samples. No network and no credentials."""
import json

from yahmi.registry import DAILY_LIMIT, FtaTrnClient, TrnResult, check_trn_registry, name_similarity

ENV = {"YAHMI_FTA_API_KEY": "k", "YAHMI_FTA_CLIENT_ID": "id", "YAHMI_FTA_CLIENT_SECRET": "secret"}
TRN = "100634286700003"


class Resp:
    def __init__(self, status, body=None):
        self.status_code, self._b = status, body

    def json(self):
        if self._b is None:
            raise ValueError
        return self._b


class FakeGateway:
    def __init__(self, status=200, body=None):
        self.calls, self.status, self.body = [], status, body if body is not None else [{"NameEn": "AlFuttaim Group", "NameAr": "مجموعة الفطيم"}]

    def post(self, url, **kw):
        self.calls.append((url, kw))
        if url.endswith("getAccessToken"):
            return Resp(200, {"access_token": "tok", "expires_in": 300})
        return Resp(self.status, self.body)


def client(gw, env=ENV, now=lambda: 1_000_000.0):
    return FtaTrnClient(env=dict(env), http=gw, clock=now)


def test_request_matches_the_spec():
    gw = FakeGateway()
    r = client(gw).lookup(TRN)
    assert r == TrnResult("found", "AlFuttaim Group", "مجموعة الفطيم")
    token_call, call = gw.calls
    assert token_call[1]["data"]["grant_type"] == "client_credentials" and token_call[1]["auth"] == ("id", "secret")
    assert call[0].endswith("/api/prc/trn/v1/gsbvalidatetrn")
    assert call[1]["headers"]["GW-APIKey"] == "k" and call[1]["headers"]["Authorization"] == "Bearer tok"
    assert call[1]["params"] == {"TRN": TRN}                     # default: query parameter
    gw2 = FakeGateway()
    client(gw2, dict(ENV, YAHMI_FTA_TRN_IN="body")).lookup(TRN)
    assert gw2.calls[1][1]["json"] == {"TRN": TRN}


def test_not_connected_never_guesses():
    gw = FakeGateway()
    f = check_trn_registry("Anyone LLC", TRN, client(gw, env={}))
    assert [x.level for x in f] == ["info"] and not gw.calls


def test_name_bands():
    c = client(FakeGateway())
    assert check_trn_registry("Al-Futtaim Group L.L.C", TRN, c)[0].level == "green"
    assert check_trn_registry("AlFuttaim Trading Group", TRN, c)[0].level == "amber"
    f = check_trn_registry("Blue Creek Logistics LLC", TRN, c)[0]
    assert f.level == "red" and "AlFuttaim Group" in f.message and "FTA" in f.source


def test_arabic_name_matches_arabic_register_name():
    r = TrnResult("found", "AlFuttaim Group", "مجموعة الفطيم")
    assert name_similarity("مجموعة الفطيم", r) >= 85
    assert name_similarity("شركة الندى للتجارة", r) < 60


def test_register_answers():
    assert check_trn_registry("X LLC", TRN, client(FakeGateway(200, [])))[0].level == "amber"          # no registration returned
    assert check_trn_registry("X LLC", TRN, client(FakeGateway(400, {"errorCode": "400"})))[0].level == "amber"
    for status in (401, 408, 500):
        f = check_trn_registry("X LLC", TRN, client(FakeGateway(status, {"Exception": "x"})))[0]
        assert f.level == "info", status                                                              # no answer is not a verdict
    assert check_trn_registry(None, TRN, client(FakeGateway()))[0].level == "amber"
    assert check_trn_registry("X LLC", "12345", client(FakeGateway())) == []


def test_cache_and_daily_limit():
    gw = FakeGateway()
    c = client(gw)
    c.lookup(TRN); c.lookup(TRN)
    assert sum(not u.endswith("getAccessToken") for u, _ in (g for g in gw.calls)) == 1   # second answer came from the cache
    gw2 = FakeGateway()
    c2 = client(gw2)
    for i in range(DAILY_LIMIT + 5):
        c2.lookup(f"1{i:014d}")
    api_calls = [u for u, _ in gw2.calls if not u.endswith("getAccessToken")]
    assert len(api_calls) == DAILY_LIMIT
    assert c2.lookup("199999999999999").status == "unavailable"
