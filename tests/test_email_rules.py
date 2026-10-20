import imaplib
import re

import pytest

from engine.rules import EmailRuleAgent, make_agent
from tests.conftest import config

MAILS = {"INBOX": [("101", "Amazon <ship@amazon.in>", "Your order shipped", False),
                   ("102", "Swiggy <no-reply@swiggy.in>", "Invoice for order 55", True),
                   ("103", "Mom <mom@example.com>", "Dinner?", False)]}


class FakeIMAP:
    def __init__(self, host, timeout=None):
        self.selected = None

    def login(self, user, password):
        pass

    def list(self):
        return "OK", [f'(\\HasNoChildren) "/" "{f}"'.encode() for f in MAILS]

    def create(self, name):
        MAILS.setdefault(name.strip('"'), [])
        return "OK", []

    def select(self, name, readonly=True):
        self.selected = name.strip('"')
        return ("OK", [b"1"]) if self.selected in MAILS else ("NO", [])

    def uid(self, cmd, *args):
        box = MAILS[self.selected]
        if cmd == "search":
            crit = " ".join(a for a in args if a)
            hits = box
            for field, idx in (("FROM", 1), ("SUBJECT", 2)):
                m = re.search(field + r' "([^"]*)"', crit)
                if m:
                    hits = [x for x in hits if m.group(1).lower() in x[idx].lower()]
            if "UNSEEN" in crit:
                hits = [x for x in hits if not x[3]]
            return "OK", [" ".join(x[0] for x in hits).encode()]
        if cmd == "fetch":
            ids = args[0].split(",")
            out = []
            for x in box:
                if x[0] in ids:
                    out += [(f"1 (UID {x[0]} BODY[HEADER] {{50}}".encode(),
                             f"From: {x[1]}\r\nSubject: {x[2]}\r\n\r\n".encode()), b")"]
            return "OK", out
        if cmd == "MOVE":
            ids, dest = args[0].split(","), args[1].strip('"')
            moving = [x for x in box if x[0] in ids]
            MAILS[self.selected] = [x for x in box if x[0] not in ids]
            MAILS.setdefault(dest, []).extend(moving)
            return "OK", []

    def logout(self):
        pass


@pytest.fixture
def mailbox(monkeypatch):
    import engine.toolkits.mail as mail
    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setattr(mail, "load_credentials", lambda: {"email": {"address": "me@x.com", "password": "p"}})
    MAILS.clear()
    MAILS["INBOX"] = [("101", "Amazon <ship@amazon.in>", "Your order shipped", False),
                      ("102", "Swiggy <no-reply@swiggy.in>", "Invoice for order 55", True),
                      ("103", "Mom <mom@example.com>", "Dinner?", False)]
    return MAILS


def sorter(**kw):
    return config(mode="rules", permissions={"email": {"read": "allow", "organize": "allow"}}, **kw)


def test_make_agent_picks_email_rules():
    assert isinstance(make_agent(sorter()), EmailRuleAgent)


def test_email_rules_move_and_check(fake, mailbox):
    fake.format_replies = {"unread_only": {"folder": "INBOX", "unread_only": False, "question": "", "rules": [
        {"from_contains": "amazon", "subject_contains": "", "destination": "Receipts"},
        {"from_contains": "", "subject_contains": "invoice", "destination": "Receipts"}]}}
    events = list(EmailRuleAgent(sorter()).run("move amazon and invoices to Receipts"))
    assert sum(e["type"] == "model_call" for e in events) == 1
    assert sorted(x[0] for x in mailbox["Receipts"]) == ["101", "102"]
    assert [x[0] for x in mailbox["INBOX"]] == ["103"]
    assert next(e for e in events if e["type"] == "verification")["complete"]
    assert sum(e["type"] == "email_op" for e in events) == 2


def test_email_rules_need_approval_when_ask(fake, mailbox):
    fake.format_replies = {"unread_only": {"folder": "INBOX", "unread_only": True, "question": "", "rules": [
        {"from_contains": "amazon", "subject_contains": "", "destination": "Receipts"}]}}
    cfg = config(mode="rules", permissions={"email": {"read": "allow", "organize": "ask"}})
    seen = {}
    events = list(EmailRuleAgent(cfg, approver=lambda n, a: seen.update(a) or "no").run("x"))
    assert "1 emails → Receipts" in seen["will_do"] and "Your order shipped" in seen["will_do"]
    assert events[-1]["content"].startswith("NOT APPLIED") and len(mailbox["INBOX"]) == 3
