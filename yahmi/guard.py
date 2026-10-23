"""Who is calling and how much they may ask: access codes, the public demo, rate limits, a cap on simultaneous checks, upload checks.

Pilot mode: each pilot business has a secret access code (YAHMI_ACCESS_CODES="code=label,code2=label2"). The server decides the business from the
code. A business name sent by the browser is never trusted, because the history of a business is looked up by that name.
Demo mode: no code needed (YAHMI_DEMO=0 turns it off). Everyone shares one throwaway business with no history, and nothing can be saved.
Limits are per process: with two server workers the real limit is about double.
"""
from __future__ import annotations

import hmac
import os
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from typing import NamedTuple

from fastapi import HTTPException, Request, UploadFile

MAX_UPLOAD = 8 * 1024 * 1024          # bytes per file
MAX_EMAIL_CHARS = 200_000
MAX_HISTORY_FILES = 30
MAGIC = {".pdf": (b"%PDF",), ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",), ".png": (b"\x89PNG",)}


class Caller(NamedTuple):
    business: str
    mode: str          # "pilot" or "demo"


def access_codes(env=None) -> dict[str, str]:
    env = os.environ if env is None else env
    out = {}
    for part in (env.get("YAHMI_ACCESS_CODES") or "").split(","):
        code, _, label = part.partition("=")
        if code.strip() and label.strip():
            out[code.strip()] = label.strip()
    return out


def identify(code: str | None, env=None) -> Caller:
    env = os.environ if env is None else env
    code = (code or "").strip()
    if code:
        found = None
        for c, label in access_codes(env).items():       # compare against every code, so timing does not reveal a near match
            if hmac.compare_digest(c.encode(), code.encode()):
                found = label
        if found is None:
            raise HTTPException(401, "That access code is not valid.")
        return Caller(found, "pilot")
    if env.get("YAHMI_DEMO", "1") != "0":
        return Caller("demo", "demo")
    raise HTTPException(401, "An access code is required.")


class RateLimiter:
    def __init__(self, limit: int, window: float = 3600.0, clock=time.time):
        self.limit, self.window, self.clock = limit, window, clock
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        now = self.clock()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True


DEMO_LIMIT = RateLimiter(int(os.environ.get("YAHMI_DEMO_PER_HOUR", "10")))
PILOT_LIMIT = RateLimiter(int(os.environ.get("YAHMI_PILOT_PER_HOUR", "120")))


def client_ip(request: Request) -> str:
    """Behind the HTTPS tunnel the real address is in CF-Connecting-IP. The app only listens on localhost, so only the tunnel can set it."""
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")


def enforce(request: Request, who: Caller) -> None:
    ok = DEMO_LIMIT.hit(client_ip(request)) if who.mode == "demo" else PILOT_LIMIT.hit(who.business)
    if not ok:
        raise HTTPException(429, "Too many checks for now. Please try again later.", headers={"Retry-After": "600"})


def read_upload(upload: UploadFile) -> tuple[bytes, str]:
    """The file's bytes and extension, after checking size, type by extension, and the file's first bytes."""
    ext = os.path.splitext(upload.filename or "")[1].lower()
    if ext not in MAGIC:
        raise HTTPException(415, "Please upload a PDF, JPG or PNG file.")
    data = upload.file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"That file is larger than {MAX_UPLOAD // (1024 * 1024)} MB.")
    if not any(data.startswith(m) for m in MAGIC[ext]):
        raise HTTPException(415, "That file does not look like a real " + ext.lstrip(".").upper() + ".")
    return data, ext


_SLOTS = threading.BoundedSemaphore(int(os.environ.get("YAHMI_CHECK_SLOTS", "2")))


@contextmanager
def check_slot(timeout: float = 45.0, slots: threading.BoundedSemaphore | None = None):
    """At most a few checks run at once; the others wait, and give up politely if it takes too long."""
    sem = slots or _SLOTS
    if not sem.acquire(timeout=timeout):
        raise HTTPException(503, "Busy: other checks are running. Please try again in a minute.", headers={"Retry-After": "60"})
    try:
        yield
    finally:
        sem.release()
