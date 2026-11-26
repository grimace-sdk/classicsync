import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..paths import partnerships_directory
from .objects import KIND_DATABASE

STATE_VERSION = 1
PARTNERSHIP_VERSION = 1
PARTNERSHIP_FILE = "partnership.json"


def safe_directory_name(name):
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .")
    return cleaned or "Device"


@dataclass
class SyncOptions:
    provider: str = "folder"
    object_types: list = None
    conflict: dict = field(default_factory=dict)
    file_folders: list = field(default_factory=lambda: ["\\My Documents"])
    file_depth: int = 1
    provider_settings: dict = field(default_factory=dict)
    type_providers: dict = field(default_factory=dict)
    conflict_prompt: str = "skip"
    dry_run: bool = False

    @classmethod
    def from_dict(cls, stored):
        known = {name: value for name, value in stored.items() if name in cls.__dataclass_fields__ and name != "dry_run"}
        return cls(**known)

    def to_dict(self):
        stored = asdict(self)
        stored.pop("dry_run")
        return stored

    def conflict_policy(self, object_type):
        if object_type.key in self.conflict:
            return self.conflict[object_type.key]
        if self.conflict_prompt and object_type.kind == KIND_DATABASE:
            return "skip"
        if object_type.kind == KIND_DATABASE and "*" in self.conflict:
            return self.conflict["*"]
        return object_type.conflict_default


def write_json_atomically(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".new")
    partial.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    partial.replace(path)


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


@dataclass
class Partnership:
    name: str
    directory: Path
    partner_id: int = None
    created: str = ""
    desktop_name: str = ""
    platform: str = ""

    @classmethod
    def for_device(cls, name, base=None):
        return cls(name, Path(base or partnerships_directory()) / safe_directory_name(name))

    @classmethod
    def load(cls, directory):
        info = read_json(directory / PARTNERSHIP_FILE, None)
        if info:
            return cls(info.get("name") or directory.name, directory, info.get("partner_id"), info.get("created", ""),
                       info.get("desktop_name", ""), info.get("platform", ""))
        state = read_json(directory / "state.json", {})
        return cls(state.get("device", directory.name), directory)

    @classmethod
    def list_all(cls, base=None):
        base = Path(base or partnerships_directory())
        if not base.is_dir():
            return []
        return [cls.load(directory) for directory in sorted(base.iterdir()) if directory.is_dir()]

    @classmethod
    def new_directory(cls, name, base=None):
        base = Path(base or partnerships_directory())
        directory = base / safe_directory_name(name)
        counter = 2
        while directory.exists():
            directory = base / f"{safe_directory_name(name)} ({counter})"
            counter += 1
        return directory

    @property
    def explicit(self):
        return self.partner_id is not None

    @property
    def label(self):
        return f"{self.partner_id:08x}" if self.explicit else ""

    @property
    def info_path(self):
        return self.directory / PARTNERSHIP_FILE

    @property
    def state_path(self):
        return self.directory / "state.json"

    @property
    def options_path(self):
        return self.directory / "options.json"

    def save_info(self):
        write_json_atomically(self.info_path, {
            "version": PARTNERSHIP_VERSION, "name": self.name, "partner_id": self.partner_id, "created": self.created,
            "desktop_name": self.desktop_name, "platform": self.platform,
        })

    def load_state(self):
        state = read_json(self.state_path, {})
        if state.get("version") != STATE_VERSION:
            state = {"version": STATE_VERSION, "device": self.name, "types": {}}
        return state

    def save_state(self, state):
        write_json_atomically(self.state_path, state)

    def load_options(self):
        return SyncOptions.from_dict(read_json(self.options_path, {}))

    def save_options(self, options):
        write_json_atomically(self.options_path, options.to_dict())

    def remove(self):
        for path in (self.info_path, self.state_path, self.options_path):
            path.unlink(missing_ok=True)
        try:
            self.directory.rmdir()
        except OSError:
            pass
