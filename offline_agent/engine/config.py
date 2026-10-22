"""
engine/config.py: an agent is just a config file.

AgentConfig holds every setting; its `permissions` is a Policy (engine/permissions.py).
load_agent / save_agent turn it into and out of YAML.
"""
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from .paths import AGENTS_DIR, PKG_DIR, ROOT, TEMPLATES_DIR, WORKSPACE  # noqa: F401 (re-exported)
from .permissions import Policy


@dataclass
class VerifyConfig:
    """A second, read-only checker that confirms the task is really done."""
    enabled: bool = False
    criteria: str = ""        # what "done" means; empty = judge from the task
    max_attempts: int = 3     # retries before giving up; 0 = keep going until you press Stop
    model: str = ""           # empty = same model as the agent

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        return cls(enabled=bool(d.get("enabled")), criteria=str(d.get("criteria") or ""),
                   max_attempts=max(0, int(d.get("max_attempts", 3) or 0)), model=str(d.get("model") or ""))


@dataclass
class AgentConfig:
    name: str = "New Agent"
    description: str = ""
    model: str = "qwen3.5:9b"
    system_prompt: str = "You are a helpful assistant."
    permissions: Policy = field(default_factory=Policy)
    max_steps: int = 8          # max model calls per task (stops endless loops)
    temperature: float = 0.2    # 0 = predictable, higher = more creative
    think: bool = False         # let reasoning models think first (slower)
    context_length: int = 16384 # tokens the model can see at once (instructions + conversation)
    verify: VerifyConfig = field(default_factory=VerifyConfig)
    mode: str = "agent"         # "agent": the model does the work | "rules": the model writes a rule, code does the work
    plan_steps: bool = True     # job notes: plan + checklist + evidence; old messages are dropped
    terse: bool = True          # telegram style: short replies
    max_reply_tokens: int = 1024  # cap on each model reply while working (0 = no cap)
    full_voice: bool = True     # final answers as detailed as needed; continued automatically if cut off

    @classmethod
    def from_dict(cls, data):
        data = dict(data or {})
        perms = data.get("permissions")
        data["permissions"] = perms if isinstance(perms, Policy) else \
            Policy.from_dict(perms, legacy_domains=data.get("allowed_domains"))
        if not isinstance(data.get("verify"), VerifyConfig):
            data["verify"] = VerifyConfig.from_dict(data.get("verify"))
        if data.get("mode") not in ("agent", "rules"):
            data["mode"] = "agent"
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self):
        return {"name": self.name, "description": self.description, "model": self.model,
                "system_prompt": self.system_prompt, "permissions": self.permissions.to_dict(),
                "max_steps": self.max_steps, "temperature": self.temperature, "think": self.think,
                "context_length": self.context_length, "verify": asdict(self.verify),
                "mode": self.mode, "plan_steps": self.plan_steps, "terse": self.terse,
                "max_reply_tokens": self.max_reply_tokens, "full_voice": self.full_voice}

    def to_yaml(self):
        return yaml.dump(self.to_dict(), sort_keys=False, allow_unicode=True)

    @property
    def slug(self):
        """File-safe name: 'File Helper' -> 'file_helper'."""
        return re.sub(r"[^a-z0-9]+", "_", self.name.lower()).strip("_") or "agent"


def _str_presenter(dumper, value):
    """Write multi-line strings (system prompts) in readable YAML block style."""
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


yaml.add_representer(str, _str_presenter)


def load_agent(path):
    with open(path, encoding="utf-8") as f:
        return AgentConfig.from_dict(yaml.safe_load(f))


def save_agent(config, folder=AGENTS_DIR):
    path = Path(folder) / f"{config.slug}.yaml"
    path.write_text(config.to_yaml(), encoding="utf-8")
    return path


def list_configs(folder):
    """{display name: path} for every YAML file in a folder."""
    out = {}
    for path in sorted(Path(folder).glob("*.yaml")):
        try:
            out[load_agent(path).name] = path
        except Exception:
            out[f"{path.name} (unreadable)"] = path
    return out
