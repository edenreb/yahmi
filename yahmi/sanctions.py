"""Name screening of the supplier against two public lists: the UN Security Council Consolidated List and the UAE Local Terrorist List.

Names only: this is a screening aid, not proof and not a compliance programme. A match says "this name is on a list, check who the supplier
really is", never "this supplier is a terrorist". The lists are refreshed by tools/update_sanctions.py into data/sanctions/entries.json; without
that file the check stays silent (it makes no claim). Sources and terms: docs/SANCTIONS.md.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from rapidfuzz import fuzz, process

from .rules import Finding

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "sanctions", "entries.json")
SIMILAR = 92            # entity-name similarity (token sort ratio) for an "amber" hit; fixed in advance, not tuned on data
STALE_DAYS = 7
LABEL = {"UN": "UN Security Council Consolidated List", "UAE_LTL": "UAE Local Terrorist List (EOCN)"}
_LEGAL = {"llc", "fze", "fzco", "fz", "pjsc", "est", "establishment", "co", "company", "ltd", "limited", "inc", "the", "and", "of"}
_AR_STRIP = re.compile(r"[ً-ٰٟـ]")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _AR_STRIP.sub("", s).replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي").replace("ة", "ه")
    s = re.sub(r"\bl\.?\s?l\.?\s?c\b\.?", "llc", s.lower())
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(w for w in s.split() if w not in _LEGAL)


@dataclass
class Hit:
    kind: str            # exact | similar
    entry: dict
    matched: str
    score: int


class Sanctions:
    def __init__(self, data: dict):
        self.meta = data.get("meta", {})
        self.exact: dict[str, list[dict]] = {}
        self.entity_names: list[tuple[str, dict, str]] = []
        for e in data["entries"]:
            for name in e["names"]:
                n = _norm(name)
                if not n:
                    continue
                self.exact.setdefault(n, []).append(e)
                if e["kind"] == "entity":
                    self.entity_names.append((n, e, name))
        self._choices = [n for n, _, _ in self.entity_names]

    @classmethod
    def load(cls, path: str = PATH) -> "Sanctions | None":
        try:
            with open(path, encoding="utf-8") as f:
                return cls(json.load(f))
        except (OSError, ValueError, KeyError):
            return None

    def screen(self, name: str) -> list[Hit]:
        n = _norm(name)
        toks = n.split()
        if len(toks) < 2 and len(n) < 8:
            return []        # one short word: far too generic to match on
        hits, seen = [], set()
        for e in self.exact.get(n, []):
            # an exact entity name is a strong signal; an exact individual name needs 3+ words (two-word personal names collide constantly)
            if e["kind"] == "entity" or len(toks) >= 3:
                hits.append(Hit("exact", e, name, 100))
                seen.add(id(e))
        if len(toks) >= 2:
            for cand, score, idx in process.extract(n, self._choices, scorer=fuzz.token_sort_ratio, limit=5, score_cutoff=SIMILAR):
                _, e, orig = self.entity_names[idx]
                if id(e) not in seen and len(set(toks) & set(cand.split())) >= 2:
                    hits.append(Hit("similar", e, orig, int(score)))
                    seen.add(id(e))
        return hits

    def dates(self) -> str:
        un, uae = self.meta.get("un", {}), self.meta.get("uae_ltl", {})
        return f"UN list generated {(un.get('generated') or un.get('fetched_at') or '?')[:10]}, UAE list fetched {(uae.get('fetched_at') or '?')[:10]}"

    def stale(self, now: datetime | None = None) -> str | None:
        now = now or datetime.now(timezone.utc)
        for m in self.meta.values():
            try:
                if now - datetime.fromisoformat(m["fetched_at"]) > timedelta(days=STALE_DAYS):
                    return m["fetched_at"][:10]
            except (KeyError, ValueError):
                return "an unknown date"
        return None


def _source(entry: dict, S: Sanctions) -> str:
    return LABEL[entry["list"]] + f" ({S.dates()})"


def check_sanctions(supplier_name: str | None, S: "Sanctions | None") -> list[Finding]:
    if not supplier_name or S is None:
        return []
    out: list[Finding] = []
    hits = S.screen(supplier_name)
    for h in hits[:3]:
        e = h.entry
        who = "an entity" if e["kind"] == "entity" else "an individual"
        if h.kind == "exact" and e["kind"] == "entity":
            level, lead = "red", "The supplier's name is the same as"
        elif h.kind == "exact":
            level, lead = "amber", "The supplier's name is the same as"
        else:
            level, lead = "amber", f"The supplier's name is very similar ({h.score}%) to"
        out.append(Finding("sanctions", level,
                           f"{lead} {who} on the {LABEL[e['list']]} (ref {e['ref'] or 'n/a'}: {h.matched}). This is a name match only, not proof. "
                           "Check who the supplier really is before paying, and ask your compliance officer or the EOCN if unsure.", _source(e, S)))
    if not hits:
        out.append(Finding("sanctions", "green", f"No name match on the UN Security Council Consolidated List or the UAE Local Terrorist List ({S.dates()}). A name check only.",
                           "UN Security Council Consolidated List; UAE Local Terrorist List (EOCN)"))
    old = S.stale()
    if old:
        out.append(Finding("sanctions_stale", "info", f"The sanctions lists were last refreshed on {old}. Refresh them (tools/update_sanctions.py) before relying on this check.", "Yahmi"))
    return out
