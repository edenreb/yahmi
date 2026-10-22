"""Supplier payment history (per business) and the shared network memory (across businesses).

Privacy: IBANs and supplier IDs are never stored in plain text. They are stored as HMAC-SHA256
with a server-side secret key. A plain hash of an IBAN can be brute-forced (UAE IBANs are
low-entropy), but a keyed hash cannot be reversed without the key, which never leaves the server.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import sqlite3

from .rules import Finding


def _key() -> bytes:
    k = os.environ.get("YAHMI_KEY")
    if not k:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", ".yahmi_key")
        if not os.path.exists(p):
            with open(p, "wb") as f:
                f.write(os.urandom(32))
        k = open(p, "rb").read()
    return k if isinstance(k, bytes) else k.encode()


def h(value: str) -> str:
    return hmac.new(_key(), value.encode(), hashlib.sha256).hexdigest()


def supplier_id(trn: str | None, name: str | None) -> str | None:
    if trn and len(re.sub(r"\D", "", trn)) == 15:
        return "trn:" + re.sub(r"\D", "", trn)
    if name:
        return "name:" + re.sub(r"[^a-z0-9]", "", name.lower())
    return None


class Memory:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(
            """
            create table if not exists history(business text, supplier text, iban text, domain text, n integer,
                                               primary key(business, supplier, iban));
            create table if not exists network(supplier text, iban text, business text,
                                               primary key(supplier, iban, business));
            """
        )

    def record(self, business: str, supplier: str, iban: str, domain: str | None = None):
        s, i, b = h(supplier), h(iban), h(business)
        self.db.execute(
            "insert into history values(?,?,?,?,1) on conflict(business,supplier,iban) do update set n=n+1, domain=coalesce(excluded.domain, domain)",
            (b, s, i, domain),
        )
        self.db.execute("insert or ignore into network values(?,?,?)", (s, i, b))
        self.db.commit()

    def known_domains(self, business: str) -> set[str]:
        """Sender domains of this business's own suppliers only. Domains are kept in plain text (lookalike detection compares spellings),
        so they are scoped to the business and never shared with another one."""
        rows = self.db.execute("select domain from history where business=? and domain is not null", (h(business),)).fetchall()
        return {r[0] for r in rows}

    def check(self, business: str, supplier: str | None, iban: str | None, domain: str | None = None) -> list[Finding]:
        if not supplier or not iban:
            return []
        s, i, b = h(supplier), h(iban), h(business)
        out: list[Finding] = []
        rows = self.db.execute("select iban, n, domain from history where business=? and supplier=?", (b, s)).fetchall()
        if rows:
            if any(r[0] == i for r in rows):
                n = sum(r[1] for r in rows if r[0] == i)
                out.append(Finding("history", "green", f"You have paid this supplier into this same account {n} time(s) before.", "Your payment history"))
            else:
                n = sum(r[1] for r in rows)
                out.append(Finding("history", "red", f"Bank details changed. You paid this supplier {n} time(s) before, always into the same account. This invoice asks for a different one. Call the supplier on a number you already trust before paying.", "Your payment history"))
            known_domains = {r[2] for r in rows if r[2]}
            if domain and known_domains and domain not in known_domains:
                out.append(Finding("history_domain", "amber", f"This supplier usually emails you from {', '.join(sorted(known_domains))}, not {domain}.", "Your payment history"))
        else:
            paid_before = self.db.execute("select 1 from history where business=? and iban=?", (b, i)).fetchone()
            if not paid_before:
                out.append(Finding("history", "amber", "First payment to this account. Every invoice-fraud ends with money going to an account you have never paid, so confirm it with the supplier on a phone number you already trust.", "Your payment history"))
            else:
                out.append(Finding("history", "info", "First invoice from this supplier name, but you have paid this account before.", "Your payment history"))

        others = self.db.execute("select iban, count(*) from network where supplier=? and business<>? group by iban", (s, b)).fetchall()
        total = sum(c for _, c in others)
        if total:
            same = sum(c for ib, c in others if ib == i)
            if same:
                out.append(Finding("network", "green", f"{same} other business(es) on Yahmi pay this supplier into this same account.", "Yahmi network (keyed-hash, no account numbers stored)"))
            else:
                out.append(Finding("network", "red", f"{total} other business(es) on Yahmi pay this supplier into a different account. None use this one.", "Yahmi network (keyed-hash, no account numbers stored)"))
        return out
