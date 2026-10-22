from offline_agent.engine.agent import Agent
from offline_agent.engine.rules import RuleAgent
from tests.conftest import config


def test_cut_off_answer_is_continued_and_joined(fake):
    fake.script = [{"content": "Part one of a long analysis, ", "done_reason": "length"},
                   {"content": "part two, ", "done_reason": "length"},
                   {"content": "and the end.", "done_reason": "stop"}]
    events = list(Agent(config(plan_steps=False)).run("analyse"))
    assert events[-1]["content"] == "Part one of a long analysis, part two, and the end."
    assert any(e["type"] == "continued" and e["parts"] == 3 for e in events)
    assert fake.calls[1]["messages"][-1]["content"].startswith("[continue]")


def test_full_voice_off_keeps_short_answers(fake):
    fake.script = [{"content": "Cut here", "done_reason": "length"}]
    events = list(Agent(config(plan_steps=False, full_voice=False)).run("x"))
    assert events[-1]["content"] == "Cut here" and not any(e["type"] == "continued" for e in events)
    system = fake.calls[0]["messages"][0]["content"]
    assert "at most 8 short lines" in system


def test_prompt_separates_work_and_final_answer(fake):
    fake.script = ["ok"]
    list(Agent(config(plan_steps=False)).run("x"))
    system = fake.calls[0]["messages"][0]["content"]
    assert "while working" in system and "FINAL answer" in system and "8 short lines" not in system


def test_clerk_writes_readable_summary(fake, downloads):
    fake.format_replies = {"rules": {"source_folder": str(downloads), "question": "", "rules": [
        {"extensions": [".pdf"], "kinds": [], "name_contains": "", "destination": "all_pdf"}]}}
    cfg = config(mode="rules", permissions={"files": {"folders": [str(downloads)], "read": "allow",
                                                      "create": "allow", "move": "allow"}})
    answer = list(RuleAgent(cfg).run("move pdfs"))[-1]["content"]
    assert answer.startswith("Done.") and "• Moved 2 files (.pdf)" in answer and "undo" in answer.lower()
    cfg.full_voice = False
    for p in (downloads / "all_pdf").iterdir():
        p.rename(downloads / p.name)
    assert list(RuleAgent(cfg).run("move pdfs"))[-1]["content"].startswith("DONE ✓")
