"""Explainable invoice-fraud cues. Each cue is a named, readable pattern drawn from how police and
banks describe business-email-compromise: a bank-detail change, an excuse for it, pressure, secrecy,
and cutting off the phone call that would expose it."""
import re

CUES = {
    "bank_change": (3.0, r"\b(new|updated?|changed?|different|alternate|alternative|another|correct(?:ed)?)\s+(bank(ing)?|account|iban|remittance|payment|wire)\s*(details|info(rmation)?|instructions|account|number|details)?\b|\bchang(e|ed|ing)\s+(of\s+)?(our|my|the)\s+(bank|banking|account|payment\s+details)|\b(bank|account)\s+(details|information)\s+(have|has)\s+(changed|been\s+updated)|\bupdate\s+(your\s+records|our\s+(bank|payment|account))|direct\s+deposit"),
    "excuse": (1.5, r"\b(audit|on\s+hold|frozen|freeze|restrict(ed|ion)|under\s+review|temporarily\s+unavailable|offshore|closed\s+(for|due)|can\s*no\s*longer\s+(receive|accept)|tax\s+reasons|bank\s+issue|problem\s+with\s+(our|the)\s+(bank|account))\b"),
    "pressure": (1.0, r"\b(urgent(ly)?|immediately|asap|as\s+soon\s+as\s+possible|today|right\s+away|end\s+of\s+(the\s+)?day|before\s+\d|late\s+(fee|payment)|avoid\s+(a\s+)?(penalt|late|suspension)|time[-\s]sensitive|quick(ly)?)\b"),
    "secrecy": (1.5, r"\b(confidential(ly)?|keep\s+(this|it)\s+(between|quiet|to\s+yourself)|discreet|do\s*n[o']?t\s+(tell|discuss|share|mention)|top\s+secret)\b"),
    "no_phone": (1.5, r"\b(in\s+(a\s+)?meetings?|travell?ing|can(no|')?t\s+(talk|take\s+calls|answer)|unable\s+to\s+(talk|take\s+calls)|do\s*n[o']?t\s+call|no\s+calls|reply\s+(to\s+this\s+email\s+)?only|only\s+(reply|respond)\s+(to\s+)?(this\s+)?email|email\s+only)\b"),
    "money_ask": (1.0, r"\b(wire|remit(tance)?|transfer|process\s+(a|the)\s+payment|send\s+(the\s+)?(payment|funds|money)|make\s+(the\s+)?payment|settle|direct\s+deposit|payroll|salary|gift\s*cards?)\b"),
}
REASSURANCE = r"\b(have\s+not\s+changed|has\s+not\s+changed|remain(s)?\s+(the\s+)?(same|unchanged)|unchanged|never\s+change\s+our\s+bank|will\s+never\s+(ask|email)|beware|be\s+aware\s+of\s+fraud|fraudulent\s+emails?)\b"
_C = {k: (w, re.compile(p, re.I)) for k, (w, p) in CUES.items()}
_R = re.compile(REASSURANCE, re.I)


def cue_hits(text: str) -> dict:
    return {k: bool(rx.search(text)) for k, (w, rx) in _C.items()}


def cue_score(text: str) -> float:
    """0..1 score from fixed, hand-set weights (not fitted to any test data)."""
    h = cue_hits(text)
    s = sum(_C[k][0] for k, v in h.items() if v)
    if _R.search(text):
        s -= 3.0  # warnings that bank details have NOT changed are the opposite of fraud
    return max(0.0, min(1.0, s / 5.0))
