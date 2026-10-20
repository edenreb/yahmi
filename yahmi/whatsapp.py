"""WhatsApp channel (Meta WhatsApp Cloud API).

Flow for a business owner on WhatsApp:
  1. Forward the supplier's email text (optional)            -> "Got the email. Now send the invoice."
  2. Send the invoice PDF or photo                           -> verdict: STOP / CHECK / OK with reasons
  3. Send a past, already-paid invoice with caption "paid"   -> added to this business's payment history

Environment variables:
  WA_TOKEN          permanent or temporary access token from Meta
  WA_PHONE_ID       the WhatsApp Business phone number ID
  WA_VERIFY_TOKEN   any secret string you also enter in the Meta webhook settings
"""
from __future__ import annotations

import os
import re
import tempfile
import time

import requests
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

GRAPH = "https://graph.facebook.com/v20.0"
router = APIRouter()
PENDING_EMAIL: dict[str, tuple[float, str]] = {}  # sender -> (time, email text)
EMAIL_TTL = 15 * 60
ICON = {"stop": "🛑 STOP. Don't pay yet.", "check": "⚠️ CHECK before paying.", "ok": "✅ Looks safe to pay."}
ICON_AR = {"stop": "🛑 توقف. لا تدفع الآن.", "check": "⚠️ تحقّق قبل الدفع.", "ok": "✅ يبدو الدفع آمناً."}
# Short Arabic summary per check and level (the English detail follows each line).
AR = {
    ("history", "red"): "تغيّرت بيانات الحساب البنكي لهذا المورّد.",
    ("history", "amber"): "أول دفعة إلى هذا الحساب.",
    ("network", "red"): "تم الإبلاغ عن هذا الحساب من شركات أخرى.",
    ("iban", "red"): "رقم الآيبان غير صحيح.",
    ("iban", "amber"): "تأكّد من رقم الآيبان.",
    ("bank", "amber"): "تحقّق من البنك.",
    ("bec", "red"): "البريد الإلكتروني يشبه رسائل الاحتيال.",
    ("bec", "amber"): "البريد الإلكتروني فيه علامات مشبوهة.",
    ("lookalike", "red"): "نطاق البريد يقلّد نطاق المورّد.",
    ("reply_to", "red"): "عنوان الرد يختلف عن المرسل.",
    ("freemail", "amber"): "أُرسل من بريد مجاني.",
    ("history_domain", "amber"): "نطاق بريد جديد لهذا المورّد.",
    ("total", "red"): "المجموع لا يطابق الحساب.",
    ("vat", "amber"): "ضريبة القيمة المضافة لا تساوي 5%.",
    ("fields", "amber"): "حقول ناقصة في الفاتورة الضريبية.",
}
CALL_AR = "اتصل بالمورّد على رقم لديك مسبقاً (وليس الرقم المذكور في الفاتورة) قبل الدفع."
ARABIC = re.compile(r"[\u0600-\u06FF]")
LANG: dict[str, str] = {}  # sender -> "ar" once they write in Arabic
DOT = {"red": "🔴", "amber": "🟠", "green": "🟢", "info": "▫️"}


class Graph:
    """Thin client so tests can swap in a fake."""

    def __init__(self):
        self.token = os.environ.get("WA_TOKEN", "")
        self.phone_id = os.environ.get("WA_PHONE_ID", "")

    def _h(self):
        return {"Authorization": f"Bearer {self.token}"}

    def download(self, media_id: str) -> bytes:
        meta = requests.get(f"{GRAPH}/{media_id}", headers=self._h(), timeout=20).json()
        return requests.get(meta["url"], headers=self._h(), timeout=60).content

    def send(self, to: str, body: str):
        requests.post(f"{GRAPH}/{self.phone_id}/messages", headers=self._h(), timeout=20,
                      json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": body[:4000]}})


GRAPH_CLIENT = Graph()


def format_verdict(result: dict, lang: str = "en") -> str:
    ar = lang == "ar"
    lines = [ICON_AR[result["verdict"]] if ar else ICON[result["verdict"]]]
    shown = [f for f in result["findings"] if f["level"] in ("red", "amber")] or result["findings"][:3]
    for f in shown[:6]:
        head = AR.get((f["check"], f["level"])) if ar else None
        lines.append(f"{DOT.get(f['level'], '•')} {head + ' ' if head else ''}{f['message']}")
    if result["verdict"] == "stop":
        lines.append("\n" + CALL_AR if ar else "\nCall the supplier on a number you already have (not the one on this invoice) before paying.")
    return "\n".join(lines)


@router.get("/whatsapp/webhook")
def verify(request: Request):
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == os.environ.get("WA_VERIFY_TOKEN", "yahmi-verify"):
        return PlainTextResponse(q.get("hub.challenge", ""))
    return PlainTextResponse("forbidden", status_code=403)


@router.post("/whatsapp/webhook")
async def receive(request: Request):
    from .app import run_check, add_history  # late import to avoid a cycle

    payload = await request.json()
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []) or []:
                sender = msg.get("from", "")
                handle_message(sender, msg, run_check, add_history)
    return {"ok": True}


def handle_message(sender: str, msg: dict, run_check, add_history):
    g = GRAPH_CLIENT
    kind = msg.get("type")
    if kind == "text":
        text = msg["text"]["body"].strip()
        if ARABIC.search(text):
            LANG[sender] = "ar"
        if text in ("مرحبا", "مساعدة", "ابدأ"):
            g.send(sender, "يتحقّق Yahmi من فاتورة المورّد قبل الدفع.\n1) أعد توجيه رسالة المورّد (اختياري).\n2) أرسل الفاتورة PDF أو صورة.\nلتعليم Yahmi مورّديك، أرسل فواتير دفعتها سابقاً مع التعليق: paid")
            return
        if text.lower() in ("hi", "hello", "help", "start"):
            g.send(sender, "Yahmi checks a supplier invoice before you pay it.\n1) Forward the supplier's email (optional).\n2) Send the invoice PDF or photo.\nTo teach Yahmi your suppliers, send invoices you have already paid with the caption: paid")
            return
        PENDING_EMAIL[sender] = (time.time(), text)
        g.send(sender, "Got the email. Now send the invoice (PDF or photo).")
        return
    if kind in ("document", "image"):
        media = msg[kind]
        caption = (media.get("caption") or "").strip().lower()
        suffix = ".pdf" if (media.get("mime_type") or "").endswith("pdf") else ".jpg"
        data = g.download(media["id"])
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        try:
            if caption.startswith("paid"):
                added = add_history(path, business=sender)
                g.send(sender, f"Added to your history: {added}." if added else "I couldn't read a supplier and IBAN on that invoice with certainty, so I didn't add it.")
                return
            t, email_text = PENDING_EMAIL.pop(sender, (0, ""))
            if time.time() - t > EMAIL_TTL:
                email_text = ""
            result = run_check(path, email_text=email_text, business=sender)
            g.send(sender, format_verdict(result, LANG.get(sender, "en")))
        finally:
            os.remove(path)
        return
    g.send(sender, "Please send the invoice as a PDF or a photo.")
