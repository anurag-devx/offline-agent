from engine.ledger import Ledger


def make():
    led = Ledger(job="j1", task="move pdfs")
    led.add("move")
    led.add("check")
    return led


def test_done_refused_when_all_tool_calls_failed():
    led = make()
    led.attach("move_file", "Error: not a file")
    assert led.update(1, "done", "moved").startswith("REFUSED")
    assert led.steps[0].status == "todo"


def test_mismatch_is_flagged():
    led = make()
    led.attach("move_files", "OK moved 3/5 · NOT MOVED 2: a.pdf")
    assert "⚠" in led.update(1, "done", "moved all")


def test_notes_point_at_current_step():
    led = make()
    led.attach("move_files", "OK moved 2/2")
    led.update(1, "done", "moved 2")
    text = led.for_model()
    assert "2 ▢ check  ← NOW" in text and "agent: moved 2" in text


def test_skip_needs_reason():
    assert make().update(1, "skipped", "").startswith("ERR")
