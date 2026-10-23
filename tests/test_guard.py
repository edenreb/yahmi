"""Access codes, demo mode, rate limits, upload checks and the WhatsApp switch (invented data only)."""
import os
import subprocess
import sys
import threading

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from conftest import FIXTURES, ROOT
from yahmi import guard
from yahmi.app import app
from yahmi.guard import RateLimiter, check_slot, identify

client = TestClient(app)


def pdf():
    return open(os.path.join(FIXTURES, "genuine_new.pdf"), "rb")


def check(code=None, **extra):
    data = {"access_code": code} if code is not None else {}
    data.update(extra)
    return client.post("/api/check", files={"invoice": ("g.pdf", pdf())}, data=data)


def test_no_code_is_demo_mode_and_a_wrong_code_is_refused():
    r = check()
    assert r.status_code == 200 and r.json()["mode"] == "demo"
    assert check("not-a-code").status_code == 401
    assert check("c-biz").json()["mode"] == "pilot"


def test_the_business_comes_from_the_code_never_from_the_request():
    # seed a pilot business's history, then claim its name without the code: the demo must not see that history
    files = [("files", (f"p{i}.pdf", open(os.path.join(FIXTURES, f"past/past_{i}.pdf"), "rb"))) for i in (1, 2, 3)]
    assert client.post("/api/history", files=files, data={"access_code": "c-biz", "email_domain": "falconbm.ae"}).status_code == 200
    mine = check("c-biz").json()
    spoof = check(business="Test Interiors LLC").json()            # an ignored extra field
    assert any(f["check"] == "history" and f["level"] == "green" for f in mine["findings"])
    assert any(f["check"] == "history" and f["level"] == "amber" for f in spoof["findings"])
    assert spoof["mode"] == "demo"


def test_history_needs_a_pilot_code():
    files = [("files", ("p.pdf", pdf()))]
    assert client.post("/api/history", files=files).status_code == 403
    assert client.post("/api/history", files=[("files", ("p.pdf", pdf()))], data={"access_code": "wrong"}).status_code == 401


def test_demo_can_be_switched_off():
    with pytest.raises(HTTPException) as e:
        identify(None, env={"YAHMI_DEMO": "0", "YAHMI_ACCESS_CODES": "k=biz"})
    assert e.value.status_code == 401
    assert identify("k", env={"YAHMI_DEMO": "0", "YAHMI_ACCESS_CODES": "k=biz"}).business == "biz"


def test_uploads_are_checked():
    big = b"%PDF" + b"0" * (guard.MAX_UPLOAD + 10)
    r = client.post("/api/check", files={"invoice": ("big.pdf", big)})
    assert r.status_code == 413
    assert client.post("/api/check", files={"invoice": ("run.exe", b"MZ....")}).status_code == 415
    assert client.post("/api/check", files={"invoice": ("fake.pdf", b"this is not a pdf")}).status_code == 415
    assert client.post("/api/check", files={"invoice": ("g.pdf", pdf())}, data={"email_text": "x" * (guard.MAX_EMAIL_CHARS + 1)}).status_code == 413


def test_rate_limiter_window_and_keys():
    now = [0.0]
    rl = RateLimiter(2, window=100, clock=lambda: now[0])
    assert rl.hit("a") and rl.hit("a") and not rl.hit("a")
    assert rl.hit("b")                                   # another caller has its own allowance
    now[0] = 101
    assert rl.hit("a")                                   # the window moved on


def test_demo_is_rate_limited_per_address(monkeypatch):
    monkeypatch.setattr(guard, "DEMO_LIMIT", RateLimiter(2))
    assert check().status_code == 200 and check().status_code == 200
    r = check()
    assert r.status_code == 429 and r.headers["retry-after"]


def test_busy_server_says_so_instead_of_hanging():
    sem = threading.BoundedSemaphore(1)
    with check_slot(timeout=0.1, slots=sem):
        with pytest.raises(HTTPException) as e:
            with check_slot(timeout=0.1, slots=sem):
                pass
        assert e.value.status_code == 503


def test_whatsapp_routes_are_off_unless_enabled():
    code = "from fastapi.testclient import TestClient; from yahmi.app import app; print(TestClient(app).get('/whatsapp/webhook').status_code)"
    env = {k: v for k, v in os.environ.items() if k != "YAHMI_ENABLE_WHATSAPP"}
    off = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
    on = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env={**env, "YAHMI_ENABLE_WHATSAPP": "1"}, capture_output=True, text=True)
    assert off.stdout.strip().endswith("404"), off.stderr[-300:]       # not mounted
    assert on.stdout.strip() and not on.stdout.strip().endswith("404"), on.stderr[-300:]   # mounted: the handler answers (403 without the verify token)


def test_whoami_tells_the_mode_and_refuses_a_wrong_code():
    assert client.get("/api/whoami").json() == {"mode": "demo"}
    assert client.get("/api/whoami", headers={"x-access-code": "c-biz"}).json() == {"mode": "pilot"}
    assert client.get("/api/whoami", headers={"x-access-code": "nope"}).status_code == 401
