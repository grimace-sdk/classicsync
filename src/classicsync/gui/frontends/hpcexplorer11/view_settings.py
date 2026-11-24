import json
from dataclasses import asdict, dataclass, field

from ...settings import data_directory


@dataclass
class ViewSettings:
    view: str = "large"
    show_folders: bool = True
    show_toolbar: bool = True
    show_status_bar: bool = True
    hide_system_files: bool = True
    full_path_in_title: bool = False
    description_bars: bool = True
    sash_position: int = 190
    window_rect: list = field(default_factory=list)

    @classmethod
    def path(cls):
        return data_directory() / "hpcexplorer11.json"

    @classmethod
    def load(cls):
        try:
            stored = json.loads(cls.path().read_text())
        except (OSError, ValueError):
            return cls()
        known = {name: value for name, value in stored.items() if name in cls.__dataclass_fields__}
        return cls(**known)

    def save(self):
        path = self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))
