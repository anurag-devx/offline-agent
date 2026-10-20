# Contributing

Thanks for helping make offline agents simple and accessible.

## Setup

```bash
git clone https://github.com/crazzzyann/offline-agent.git
cd offline-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
python -m pytest -q          # no Ollama needed: tests use a fake model
```

## Easy first contributions

**Add a template** (no Python needed): copy a file in `templates/`, change the name, prompt and
permissions, and check it loads in the Studio. Give it the smallest permissions that work.

**Add a tool** (about 10 lines) in `engine/toolkits/`:

```python
@tool("files.read")          # the capability that must be on; @tool() = always available
def word_count(path: str):
    """Count the words in a text file.

    Args:
        path: Full path of the file
    """
    return f"OK {len(read_file(path).split())} words"
```

Rules for tools:
- The docstring and type hints are what the model sees: make them clear.
- Return a short, telegram-style string (`OK ...` / `Error: ...`). Never raise for expected problems.
- Go through `files.resolve()` for any path; record changes with `_count_change()`.
- New capabilities go in `engine/permissions.py`.

**Report your hardware**: open an issue with model, machine and how a template performed.
We use it for the "tested on" table.

## Pull requests

- One change per PR, with a test in `tests/` when you change behaviour.
- Old agent YAML files must keep loading (see `Policy.from_dict` for how legacy formats are handled).
- Safety first: anything that touches files, internet or email must respect the permission policy.
