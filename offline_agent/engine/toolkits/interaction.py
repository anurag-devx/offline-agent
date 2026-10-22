"""Talk to the user during a run."""
from ..context import get_context
from ..tools import tool


@tool("interaction.ask_user", safety='Pauses the run until you answer. In unattended runs it gets no answer.', example='~/Downloads')
def ask_user(question: str):
    """Ask the user a question and wait for their answer. Use it when you need information
    or a decision from them (e.g. which folder to use, or "Proceed?").

    Args:
        question: The question to ask, clear and short
    """
    return get_context().ask(question)
