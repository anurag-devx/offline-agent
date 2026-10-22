"""The two tools the model uses to keep its job notes. They touch nothing but the notes."""
from ..context import get_context
from ..tools import tool


def _ledger():
    ledger = getattr(get_context(), "ledger", None)
    if ledger is None:
        raise RuntimeError("Step notes are off for this agent.")
    return ledger


@tool("internal.ledger", safety="Touches only the job notes. A 'done' is refused if the step's tool calls all failed.", example='OK step 2 done · NOW step 3: Check nothing left')
def update_step(step: int, status: str = "done", note: str = ""):
    """Close a step in your job notes after doing it.

    Args:
        step: Step number from the notes
        status: done, skipped or blocked
        note: One short line: what you did (or why skipped/blocked)
    """
    return _ledger().update(step, status, note)


@tool("internal.ledger", safety='Touches only the job notes.', example='OK added step 4: Report totals')
def add_step(title: str):
    """Add a step to your job notes when you discover more work is needed.

    Args:
        title: Short step title, max 8 words
    """
    s = _ledger().add(title)
    return f"OK added step {s.n}: {s.title}"
