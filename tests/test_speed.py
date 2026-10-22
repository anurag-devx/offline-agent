import time

from offline_agent.engine.agent import Agent
from offline_agent.engine.runs import RunManager
from offline_agent.engine.speed import summarize
from tests.conftest import config


def test_model_calls_carry_timing(fake):
    fake.script = ["hi"]
    call = next(e for e in Agent(config(plan_steps=False)).run("hi") if e["type"] == "model_call")
    assert (call["load_s"], call["read_s"], call["write_s"]) == (0.5, 1.0, 0.5)
    assert call["read_tps"] == 10.0 and call["write_tps"] == 10.0


def test_run_summary_parts_and_tips(fake):
    fake.durations = {"load_duration": 9_000_000_000, "prompt_eval_duration": 3_000_000_000,
                      "eval_duration": 1_000_000_000}
    fake.script = [[("calculator", {"expression": "1+1"})]] * 5 + ["done"]
    run = RunManager().start(config(plan_steps=False), "add")
    while run.active:
        time.sleep(0.02)
    sp = summarize(run)
    assert sp["calls"] == 6 and sp["parts"]["Model: loading"] == 54.0
    assert any("Loading the model" in t for t in sp["tips"]) and any("6 model calls" in t for t in sp["tips"])
    assert sp["per_call"][0]["read tok/s"] > 0
