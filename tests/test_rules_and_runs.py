import time

from engine.rules import RuleAgent
from engine.runs import RunManager
from tests.conftest import config


def sorter(downloads, **kw):
    return config(mode="rules", permissions={"files": {"folders": [str(downloads)], "read": "allow",
                                                       "create": "allow", "move": "allow"}}, **kw)


def test_rule_mode_uses_one_model_call_and_checks_result(fake, downloads):
    fake.format_replies = {"rules": {"source_folder": str(downloads), "question": "", "rules": [
        {"extensions": [".pdf"], "kinds": [], "name_contains": "", "destination": "all_pdf"}]}}
    events = list(RuleAgent(sorter(downloads)).run("move pdfs to all_pdf"))
    assert sum(e["type"] == "model_call" for e in events) == 1
    check = next(e for e in events if e["type"] == "verification")
    assert check["complete"] and sorted(p.name for p in (downloads / "all_pdf").iterdir()) == ["a.pdf", "b.pdf"]
    assert (downloads / "sub" / "deep.pdf").exists()


def wait(run, seconds=10):
    end = time.time() + seconds
    while run.active and time.time() < end:
        time.sleep(0.02)


def test_verifier_sends_agent_back_until_done(fake, downloads):
    cfg = config(plan_steps=False, permissions={"files": {"folders": [str(downloads)], "read": "allow",
                                                          "create": "allow", "move": "allow"}})
    cfg.verify.enabled, cfg.verify.max_attempts = True, 3
    left = lambda: {"complete": not list(downloads.glob("*.pdf")), "reason": "pdfs left", "missing": "pdfs"}  # noqa
    fake.format_replies = {"complete": left}
    fake.script = ["done!",                      # worker lies
                   "checked",                    # verifier round 1
                   [("move_files", {"folder": str(downloads), "destination_folder": str(downloads / "all_pdf"),
                                    "extensions": ".pdf"})], "done",
                   "checked"]                    # verifier round 2
    mgr = RunManager()
    run = mgr.start(cfg, "move pdfs to all_pdf")
    wait(run)
    assert run.status == "completed" and run.verified and run.attempts == 2


def test_undo_moves_files_back(fake, downloads):
    fake.format_replies = {"rules": {"source_folder": str(downloads), "question": "", "rules": [
        {"extensions": [".pdf"], "kinds": [], "name_contains": "", "destination": "all_pdf"}]}}
    mgr = RunManager()
    run = mgr.start(sorter(downloads), "move pdfs")
    wait(run)
    assert run.file_changes == 3  # folder + 2 moves
    mgr.undo_file_changes(run.id)
    assert (downloads / "a.pdf").exists() and not (downloads / "all_pdf").exists()
