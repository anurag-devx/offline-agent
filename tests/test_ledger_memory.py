from offline_agent.engine.ledger import Ledger


def test_notes_remember_files_made_even_after_history_is_trimmed():
    led = Ledger(job="j", task="build site")
    led.add("Write index.html")
    led.attach("write_file", "OK created ~/work/site/index.html (5530 chars)")
    led.attach("create_folder", "OK created ~/work/site/images/")
    led.attach("write_file", "Error: ~/work/site/style.css already exists")
    notes = led.for_model()
    assert "ALREADY MADE" in notes and "site/index.html" in notes and "site/images/" in notes
    assert "style.css" not in notes.split("ALREADY MADE")[1]
    assert Ledger.from_dict(led.to_dict()).made == led.made


def test_duplicate_open_step_is_not_added_twice():
    led = Ledger(job="j", task="t")
    first = led.add("Write  site/index.html")
    again = led.add("write site/index.html")
    assert again is first and len(led.steps) == 1
