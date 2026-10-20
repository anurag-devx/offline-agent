"""
engine/scheduler.py: run agents on a schedule.

    daily     every day (or chosen weekdays) at HH:MM
    interval  every N minutes (minimum 5)

A background thread checks every 20 seconds. Only ONE process runs schedules at a time
(a lock file with a heartbeat), so the app and the headless runner never double-run.
If the previous run of a schedule is still busy, the new one is skipped. Times missed
while nothing was running are logged as missed, not all run at once later.
"""
import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from . import audit
from .config import load_agent
from .paths import ROOT

SCHEDULES_DIR = ROOT / "schedules"
TICK = 20          # seconds between checks
LOCK_STALE = 90    # a lock older than this is considered dead
MIN_INTERVAL = 5   # minutes


@dataclass
class Schedule:
    id: str
    name: str
    agent: str                  # path to the agent YAML, relative to the project
    task: str
    kind: str = "daily"         # daily | interval
    time: str = "09:00"         # HH:MM, for daily
    weekdays: list = field(default_factory=list)  # 0=Mon..6=Sun; empty = every day
    every_minutes: int = 60     # for interval
    enabled: bool = True
    next_run: str = ""
    last_run: str = ""
    last_run_id: str = ""
    last_result: str = ""

    def describe(self):
        if self.kind == "interval":
            return f"every {self.every_minutes} min"
        days = "every day" if not self.weekdays else \
            ", ".join(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d] for d in sorted(self.weekdays))
        return f"{days} at {self.time}"


def next_after(s, after):
    """The next time this schedule should run, strictly after `after`."""
    if s.kind == "interval":
        return after + timedelta(minutes=max(MIN_INTERVAL, int(s.every_minutes)))
    hh, mm = (int(x) for x in s.time.split(":"))
    day = after.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if day <= after:
        day += timedelta(days=1)
    for _ in range(8):
        if not s.weekdays or day.weekday() in s.weekdays:
            return day
        day += timedelta(days=1)
    return day


# ---------------------------------------------------------------- storage

def _file():
    SCHEDULES_DIR.mkdir(exist_ok=True)
    return SCHEDULES_DIR / "schedules.json"


_io_lock = threading.Lock()


def load_schedules():
    with _io_lock:
        try:
            data = json.loads(_file().read_text(encoding="utf-8"))
        except Exception:
            return []
    known = Schedule.__dataclass_fields__
    return [Schedule(**{k: v for k, v in d.items() if k in known}) for d in data]


def save_schedules(items):
    with _io_lock:
        _file().write_text(json.dumps([asdict(s) for s in items], indent=2), encoding="utf-8")


def add_schedule(name, agent, task, kind="daily", time_="09:00", weekdays=(), every_minutes=60, enabled=True):
    s = Schedule(id=uuid.uuid4().hex[:6], name=name.strip() or "Schedule", agent=agent, task=task.strip(),
                 kind=kind, time=time_, weekdays=sorted(set(weekdays)),
                 every_minutes=max(MIN_INTERVAL, int(every_minutes)), enabled=enabled)
    s.next_run = next_after(s, datetime.now()).isoformat(timespec="seconds")
    items = load_schedules() + [s]
    save_schedules(items)
    audit.log("schedule_added", id=s.id, name=s.name, agent=agent, when=s.describe())
    return s


def update_schedule(sid, **changes):
    items = load_schedules()
    for s in items:
        if s.id == sid:
            for k, v in changes.items():
                setattr(s, k, v)
            if "enabled" in changes and changes["enabled"]:
                s.next_run = next_after(s, datetime.now()).isoformat(timespec="seconds")
    save_schedules(items)


def delete_schedule(sid):
    save_schedules([s for s in load_schedules() if s.id != sid])
    audit.log("schedule_deleted", id=sid)


# ---------------------------------------------------------------- the runner

class Scheduler:
    def __init__(self, manager, owner="app"):
        self.manager = manager
        self.owner = owner
        self._thread = None
        self._stop = threading.Event()
        self.lock_path = (SCHEDULES_DIR / "scheduler.lock")

    # -- lock: one process runs schedules
    def _lock_holder(self):
        try:
            data = json.loads(self.lock_path.read_text())
            if time.time() - data["beat"] < LOCK_STALE:
                return data
        except Exception:
            pass
        return None

    def _beat(self):
        SCHEDULES_DIR.mkdir(exist_ok=True)
        self.lock_path.write_text(json.dumps({"pid": os.getpid(), "owner": self.owner, "beat": time.time()}))

    def status(self):
        holder = self._lock_holder()
        if self._thread and self._thread.is_alive():
            return f"running here ({self.owner})"
        if holder:
            return f"running elsewhere ({holder['owner']}, pid {holder['pid']})"
        return "not running"

    def start(self):
        if self._thread and self._thread.is_alive():
            return True
        holder = self._lock_holder()
        if holder and holder["pid"] != os.getpid():
            return False  # someone else runs schedules
        self._beat()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        audit.log("scheduler_started", owner=self.owner, pid=os.getpid())
        return True

    def stop(self):
        self._stop.set()

    def _loop(self):
        self._catch_up()
        while not self._stop.is_set():
            try:
                self._beat()
                self.tick()
            except Exception as e:
                audit.log("scheduler_error", error=str(e))
            self._stop.wait(TICK)

    def _catch_up(self):
        """Times missed while nothing was running: log them, then schedule the next one."""
        now = datetime.now()
        items = load_schedules()
        for s in items:
            if s.enabled and s.next_run and datetime.fromisoformat(s.next_run) < now - timedelta(minutes=10):
                audit.log("schedule_missed", id=s.id, name=s.name, was_due=s.next_run)
                s.last_result = f"missed {s.next_run.replace('T', ' ')}"
                s.next_run = next_after(s, now).isoformat(timespec="seconds")
        save_schedules(items)

    def tick(self, now=None):
        """Start every schedule that is due. Returns the run ids started."""
        now = now or datetime.now()
        items, started = load_schedules(), []
        for s in items:
            if not s.enabled or not s.next_run or datetime.fromisoformat(s.next_run) > now:
                continue
            prev = self.manager.runs.get(s.last_run_id)
            if prev and prev.active:
                s.last_result = "skipped: previous run still busy"
                audit.log("schedule_skipped", id=s.id, name=s.name)
            else:
                try:
                    cfg = load_agent(ROOT / s.agent)
                    run = self.manager.start(cfg, s.task)
                    s.last_run_id, s.last_result = run.id, "started"
                    started.append(run.id)
                    audit.log("schedule_ran", id=s.id, name=s.name, run=run.id)
                except Exception as e:
                    s.last_result = f"error: {e}"
                    audit.log("schedule_error", id=s.id, error=str(e))
            s.last_run = now.isoformat(timespec="seconds")
            s.next_run = next_after(s, now).isoformat(timespec="seconds")
        save_schedules(items)
        return started


_scheduler = None


def get_scheduler(manager=None, owner="app"):
    global _scheduler
    if _scheduler is None:
        from .runs import get_manager
        _scheduler = Scheduler(manager or get_manager(), owner=owner)
    return _scheduler
