"""
engine/tools.py: the tool registry.

A tool is a plain Python function with @tool("group.capability") above it. The decorator
reads the function's name, docstring and type hints and builds the JSON
description ("schema") the model needs to know the tool exists and how to call it.

Built-in tools live in engine/toolkits/ and register themselves at the bottom of this file.
"""
import inspect

TOOLS = {}  # name -> {"function", "schema", "permission"}

_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}


def tool(permission=None, preview=None):
    """Decorator. permission is a capability like "files.move" (see permissions.py).
    None means the tool is always available (e.g. calculator).
    preview(**args) -> str, optional: describes what a call WOULD do, shown when you approve it."""
    def register(fn):
        summary, arg_docs = _parse_docstring(inspect.getdoc(fn) or "")
        properties, required = {}, []
        for name, param in inspect.signature(fn).parameters.items():
            properties[name] = {
                "type": _JSON_TYPES.get(param.annotation, "string"),
                "description": arg_docs.get(name, ""),
            }
            if param.default is inspect.Parameter.empty:
                required.append(name)
        TOOLS[fn.__name__] = {
            "function": fn,
            "permission": permission,
            "preview": preview,
            "schema": {
                "type": "function",
                "function": {
                    "name": fn.__name__,
                    "description": summary,
                    "parameters": {"type": "object", "properties": properties, "required": required},
                },
            },
        }
        return fn
    return register


def _parse_docstring(doc):
    """Split a docstring into (summary, {arg: description}) using the 'Args:' section."""
    summary_lines, args, in_args = [], {}, False
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped == "Args:":
            in_args = True
        elif in_args and ":" in stripped:
            name, desc = stripped.split(":", 1)
            args[name.strip()] = desc.strip()
        elif not in_args and stripped:
            summary_lines.append(stripped)
    return " ".join(summary_lines), args


def describe(name):
    return TOOLS[name]["schema"]["function"]["description"] if name in TOOLS else ""


def permission_of(name):
    return TOOLS[name]["permission"] if name in TOOLS else None


INTERNAL = "internal."


def is_internal(name):
    return str(TOOLS.get(name, {}).get("permission") or "").startswith(INTERNAL)


def internal_tools():
    """Framework tools (job notes) that agents get when the feature is on, not via permissions."""
    return [n for n in TOOLS if is_internal(n)]


def tools_for(config):
    """Names of the tools an agent gets: every tool whose capability isn't off."""
    return [n for n, t in TOOLS.items()
            if not is_internal(n) and config.permissions.mode(t["permission"]) != "off"]


def get_schemas(names):
    return [TOOLS[n]["schema"] for n in names if n in TOOLS]


def preview_tool(name, args):
    """What a call would do, for the approval card. None if the tool has no preview."""
    t = TOOLS.get(name)
    if not t or not t["preview"]:
        return None
    try:
        return str(t["preview"](**_coerce(t["function"], args or {})))
    except Exception as e:
        return f"(could not preview: {e})"


def run_tool(name, args, allowed=None):
    """Run a tool and always return a string. Errors are returned, not raised,
    so the model can read the error and try something else."""
    if name not in TOOLS:
        return f"Error: unknown tool '{name}'."
    if allowed is not None and name not in allowed:
        return f"Error: this agent has no permission to use '{name}'."
    fn = TOOLS[name]["function"]
    try:
        return str(fn(**_coerce(fn, args or {})))
    except Exception as e:  # Morse: short errors; the class name only when there's no message
        return f"Error: {e}" if str(e) else f"Error: {type(e).__name__}"


def _coerce(fn, args):
    """Small models sometimes send "5" instead of 5. Fix types using the type hints."""
    params = inspect.signature(fn).parameters
    fixed = {}
    for k, v in args.items():
        if k not in params:
            continue  # ignore made-up arguments
        hint = params[k].annotation
        if hint is bool and isinstance(v, str):
            v = v.strip().lower() in ("true", "1", "yes")
        elif hint in (int, float) and isinstance(v, str):
            v = hint(v)
        elif hint is str and not isinstance(v, str):
            v = str(v)
        fixed[k] = v
    return fixed


# Register the built-in tools (they import `tool` from this module).
from .toolkits import basic, feeds, files, interaction, ledger_tools, mail, memory_tools, web  # noqa: E402,F401
