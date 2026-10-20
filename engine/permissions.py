"""
engine/permissions.py: the permission policy. What an agent may do, where, and how.

Every capability has a mode:
    off    the agent can't even see the tools
    allow  the agent may use them freely
    ask    the run pauses for your OK (approve once, approve all for this run, or deny)

Scopes narrow it further: which folders, file types, websites and mail folders.
Some places are blocked for every agent regardless (see paths.PROTECTED).
"""
from dataclasses import asdict, dataclass, field, fields

OFF, ALLOW, ASK = "off", "allow", "ask"
MODES = (OFF, ALLOW, ASK)
MODE_LABEL = {OFF: "Off", ALLOW: "Allow", ASK: "Ask first"}
RISK_ICON = {"low": "🟢", "medium": "🟡", "high": "🔴"}

GROUPS = {"files": "📁 Files & folders", "internet": "🌐 Internet",
          "email": "✉️ Email", "interaction": "💬 Interaction"}

CAPABILITIES = {
    "files.read":   {"label": "Read", "risk": "low", "detail": "List folders and read files."},
    "files.create": {"label": "Create", "risk": "medium", "detail": "Create new files and folders. Never overwrites."},
    "files.modify": {"label": "Modify", "risk": "high", "detail": "Overwrite or add to existing files."},
    "files.move":   {"label": "Move / rename", "risk": "medium", "detail": "Move or rename files. Never overwrites: clashes get _1, _2..."},
    "files.delete": {"label": "Delete", "risk": "high", "detail": "Send files to the Trash (you can restore them)."},
    "internet.read":   {"label": "Read web pages", "risk": "medium", "detail": "Open pages on the allowed sites."},
    "internet.search": {"label": "Web search", "risk": "medium", "detail": "Search DuckDuckGo. Your search words are sent to DuckDuckGo."},
    "email.read":     {"label": "Read email", "risk": "medium", "detail": "Read your mailbox over IMAP, without marking mail read."},
    "email.organize": {"label": "Organize email", "risk": "high", "detail": "Move emails between folders/labels, mark read. Never sends or deletes."},
    "interaction.ask_user": {"label": "Ask you questions", "risk": "low", "detail": "Pause and ask you something (e.g. which folder to use)."},
}


def group_of(cap):
    return cap.split(".")[0]


def cap_title(cap):
    return f"{GROUPS[group_of(cap)].split(' ', 1)[1]}: {CAPABILITIES[cap]['label']}"


def _mode(value, allowed=MODES):
    # YAML reads bare off/on/yes/no as booleans, so accept those too.
    if value is True:
        value = ALLOW
    if value in (False, None):
        value = OFF
    return value if value in allowed else OFF


@dataclass
class FilePolicy:
    folders: list = field(default_factory=lambda: ["workspace"])  # subfolders included
    read: str = OFF
    create: str = OFF
    modify: str = OFF
    move: str = OFF
    delete: str = OFF
    ask_for_other_folders: bool = False   # ask you instead of refusing other folders
    file_types: list = field(default_factory=list)  # e.g. [".jpg", ".pdf"]; empty = all
    max_changes: int = 200                # max create/modify/move/delete per run


@dataclass
class InternetPolicy:
    read: str = OFF
    search: str = OFF
    domains: list = field(default_factory=list)  # subdomains included
    other_domains: str = "block"                 # "block" or "ask"


@dataclass
class EmailPolicy:
    read: str = OFF
    organize: str = OFF
    folders: list = field(default_factory=list)  # mail folders allowed; empty = all


@dataclass
class InteractionPolicy:
    ask_user: str = ALLOW


_GROUP_CLASSES = {"files": FilePolicy, "internet": InternetPolicy,
                  "email": EmailPolicy, "interaction": InteractionPolicy}

# Old flat format (v0.2) -> new capabilities
_LEGACY = {"files_read": ["files.read"], "files_write": ["files.create", "files.modify"],
           "internet": ["internet.read"], "email_read": ["email.read"], "email_write": ["email.organize"]}


@dataclass
class Policy:
    files: FilePolicy = field(default_factory=FilePolicy)
    internet: InternetPolicy = field(default_factory=InternetPolicy)
    email: EmailPolicy = field(default_factory=EmailPolicy)
    interaction: InteractionPolicy = field(default_factory=InteractionPolicy)

    def mode(self, cap):
        """Mode of a capability like 'files.move'. None (always-on tools) -> allow."""
        if cap is None or cap.startswith("internal."):
            return ALLOW
        group, action = cap.split(".")
        return getattr(getattr(self, group), action, OFF)

    def set_mode(self, cap, mode):
        group, action = cap.split(".")
        setattr(getattr(self, group), action, mode)

    def enabled(self):
        return [c for c in CAPABILITIES if self.mode(c) != OFF]

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data, legacy_domains=None):
        data = data or {}
        if isinstance(data, list):
            data = {p: ALLOW for p in data}
        # Old flat format has plain values ("files_read": "allow"); new format has a dict per group.
        if data and not all(isinstance(v, dict) for v in data.values()):
            pol = cls()
            for old, caps in _LEGACY.items():
                for cap in caps:
                    pol.set_mode(cap, _mode(data.get(old)))
            pol.internet.domains = list(legacy_domains or [])
            return pol
        pol = cls()
        for group, klass in _GROUP_CLASSES.items():
            raw = data.get(group) or {}
            obj = klass()
            for f in fields(klass):
                if f.name not in raw:
                    continue
                v = raw[f.name]
                if f.type is str or f.type == "str":
                    if f.name == "other_domains":
                        v = v if v in ("block", "ask") else "block"
                    elif f.name == "ask_user":
                        v = _mode(v, (OFF, ALLOW))
                    else:
                        v = _mode(v)
                elif f.name in ("folders", "domains", "file_types"):
                    v = [str(x).strip() for x in (v or []) if str(x).strip()]
                    if f.name == "file_types":
                        v = [x.lower() if x.startswith(".") else "." + x.lower() for x in v]
                elif f.name == "max_changes":
                    v = max(1, int(v or 1))
                else:
                    v = bool(v)
                setattr(obj, f.name, v)
            setattr(pol, group, obj)
        return pol
