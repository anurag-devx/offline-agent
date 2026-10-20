import time
from datetime import datetime

from engine import scheduler
from engine.config import save_agent
from engine.runs import RunManager
from engine.scheduler import Schedule, next_after
from tests.conftest import config


def test_next_after_daily_and_weekdays():
    s = Schedule(id="x", name="n", agent="a", task="t", kind="daily", time="09:00")
    assert next_after(s, datetime(2026, 10, 20, 8, 0)) == datetime(2026, 10, 20, 9, 0)
    assert next_after(s, datetime(2026, 10, 20, 9, 0)) == datetime(2026, 10, 21, 9, 0)
    s.weekdays = [0]  # Mondays; 2026-10-20 is a Tuesday
    assert next_after(s, datetime(2026, 10, 20, 10, 0)) == datetime(2026, 10, 26, 9, 0)


def test_interval_has_minimum():
    s = Schedule(id="x", name="n", agent="a", task="t", kind="interval", every_minutes=1)
    assert next_after(s, datetime(2026, 1, 1, 0, 0)) == datetime(2026, 1, 1, 0, 5)


def test_due_schedule_runs_once_and_skips_while_busy(fake, tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "SCHEDULES_DIR", tmp_path / "schedules")
    monkeypatch.setattr(scheduler, "ROOT", tmp_path)
    save_agent(config(name="Hello", plan_steps=False), folder=tmp_path)
    s = scheduler.add_schedule("hi", "hello.yaml", "say hi", kind="interval", every_minutes=5)
    mgr = RunManager()
    sched = scheduler.Scheduler(mgr)
    later = datetime.fromisoformat(s.next_run)
    fake.script = ["hi!"]
    started = sched.tick(now=later)
    assert len(started) == 1
    run = mgr.runs[started[0]]
    while run.active:
        time.sleep(0.02)
    assert run.status == "completed"
    assert sched.tick(now=later) == []  # not due again until the next interval


def test_unattended_denies_approvals(fake, downloads):
    cfg = config(plan_steps=False, permissions={"files": {"folders": [str(downloads)], "read": "allow",
                                                          "create": "allow", "move": "ask"}})
    fake.script = [[("move_files", {"folder": str(downloads), "destination_folder": str(downloads / "p"),
                                    "extensions": ".pdf"})], "ok"]
    mgr = RunManager(unattended=True)
    run = mgr.start(cfg, "move pdfs")
    while run.active:
        time.sleep(0.02)
    assert run.status == "completed" and (downloads / "a.pdf").exists()
    assert any(e["type"] == "warning" and "Unattended" in e["content"] for e in run.events)


def test_only_one_scheduler(fake, tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "SCHEDULES_DIR", tmp_path / "s")
    a, b = scheduler.Scheduler(RunManager()), scheduler.Scheduler(RunManager())
    a.lock_path = b.lock_path = tmp_path / "s" / "scheduler.lock"
    monkeypatch.setattr(scheduler.os, "getpid", lambda: 111)
    assert a.start()
    monkeypatch.setattr(scheduler.os, "getpid", lambda: 222)
    assert not b.start()  # another live process holds the lock
    a.stop()
