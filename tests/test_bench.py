import re
import time

from offline_agent.engine import bench
from offline_agent.engine.config import load_agent
from offline_agent.engine.runs import RunManager


def rule_from_task(messages):
    task = messages[-1]["content"]
    folder = re.search(r"in (/\S+?) to", task).group(1)
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
