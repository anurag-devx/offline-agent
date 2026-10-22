import re
import time

from offline_agent.engine import bench
from offline_agent.engine.config import load_agent
from offline_agent.engine.runs import RunManager


def rule_from_task(messages):
    task = messages[-1]["content"]
    folder = re.search(r"in (.+?) to a new folder", task).group(1)  # any OS: /Users/… or C:\Users\…
    return {"source_folder": folder, "question": "", "rules": [
        {"extensions": [".pdf"], "kinds": [], "name_contains": "", "destination": "all_pdf"}]}


def wait(job, seconds=20):
    end = time.time() + seconds
    while not job.done and time.time() < end:
        time.sleep(0.05)


def test_bench_runs_checks_and_compares(fake, tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "BENCH_DIR", tmp_path / "bench")
    monkeypatch.setattr(bench, "SANDBOX_DIR", tmp_path / "sandbox")
    fake.format_replies = {"rules": rule_from_task}
    fake.script = [[("calculator", {"expression": "1240*18/100"})], "18% of 1240 is 223.2",
                   [("calculator", {"expression": "1240*18/100"})], "It is 223.2"]
    job = bench.start_job(RunManager(), agents=["Math Helper", "File Sorter", "News Collector"],
                          models=["test-model"], variants=["Telegram on", "Telegram off"])
    wait(job)
    assert job.done and len(job.results) == 6
    ran = [r for r in job.results if r["passed"] is not None]
    assert len(ran) == 4 and all(r["passed"] for r in ran), [r.get("checks") for r in ran]
    assert {r["why"] for r in job.results if r["passed"] is None} == {"internet tests off"}
    summary = job.summary()
    assert {s["variant"] for s in summary} == {"Telegram on", "Telegram off"}
    assert all(s["passed"] == "2/2" for s in summary)
    assert (tmp_path / "bench" / f"{job.id}.md").read_text().startswith("# Test Bench")


def test_failing_check_is_reported(fake, tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "BENCH_DIR", tmp_path / "bench")
    monkeypatch.setattr(bench, "SANDBOX_DIR", tmp_path / "sandbox")
    fake.script = ["I think it's about 200"]  # wrong, and no calculator
    job = bench.start_job(RunManager(), agents=["Math Helper"], models=["test-model"], variants=["Telegram on"])
    wait(job)
    r = job.results[0]
    assert r["passed"] is False and any(not c["ok"] and "223.2" in c["check"] for c in r["checks"])


def test_sandbox_limits_the_agent(tmp_path):
    cfg = load_agent(bench.available_agents()["File Sorter"])
    case = bench.case_for("File Sorter", bench.available_agents()["File Sorter"])
    safe = bench.prepare(cfg, case, tmp_path / "box")
    assert safe.permissions.files.folders == [str(tmp_path / "box")]
    assert not safe.permissions.files.ask_for_other_folders and safe.permissions.memory.write == "off"
    assert (tmp_path / "box" / "a.pdf").exists() and (tmp_path / "box" / "sub" / "deep.pdf").exists()


def test_every_template_has_a_case():
    names = set(bench.load_cases())
    templates = {n for n in bench.available_agents() if "(yours)" not in n}
    assert templates <= names | {n for n in templates if bench.case_for(n, bench.available_agents()[n]).get("smoke")}
    assert {"Math Helper", "File Sorter", "Website Builder", "Gmail Sorter"} <= names


class _Run:
    answer, events, attempts = "", [], 1


def test_text_checks_name_what_is_missing(tmp_path):
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "index.html").write_text('<h1>Crumbs</h1> ₹120 ₹90 TODO', encoding="utf-8")
    out = bench.run_checks([
        {"file_contains": {"path": "site/index.html", "text": ["Crumbs", "mailto:"]}},
        {"file_not_contains": {"path": "site/index.html", "text": ["lorem ipsum", "TODO"]}},
        {"count_text": {"path": "site/index.html", "text": "₹", "at_least": 2}},
    ], _Run(), tmp_path)
    assert [ok for _, ok, _ in out] == [False, False, True]
    assert "mailto:" in out[0][2] and "TODO" in out[1][2]


def test_score_penalizes_inspector_send_backs():
    checks = [("a", True, ""), ("b", True, ""), ("c", False, ""), ("d", True, "")]
    assert bench.score(checks, attempts=1) == 75
    assert bench.score(checks, attempts=3) == 55
    assert bench.score([], attempts=1) == 0


def test_case_can_switch_the_inspector_on(tmp_path):
    cfg = load_agent(bench.available_agents()["Math Helper"])
    out = bench.prepare(cfg, {"verify": {"enabled": True, "criteria": "x", "max_attempts": 2}}, tmp_path / "s")
    assert out.verify.enabled and out.verify.max_attempts == 2


def test_checks_can_read_page_and_script_together(tmp_path):
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "index.html").write_text('<div id="menu-grid"></div>', encoding="utf-8")
    (tmp_path / "site" / "script.js").write_text('const items=[{name:"Sourdough"}]', encoding="utf-8")
    (ok_html,), (ok_both,) = ([ok for _, ok, _ in bench.run_checks(
        [{"file_contains": {"path": p, "text": ["sourdough"]}}], _Run(), tmp_path)]
        for p in ("site/index.html", ["site/index.html", "site/script.js"]))
    assert not ok_html and ok_both
