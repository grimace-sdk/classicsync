import json
from dataclasses import asdict, dataclass, field

from ..paths import data_directory


@dataclass
class Settings:
    serial_enabled: bool = True
    serial_port: str = ""
    serial_baud: int = 0
    usb_enabled: bool = True
    last_baud: int = 0
    network_enabled: bool = False
    show_tray_icon: bool = True
    open_on_connect: bool = True
    sync_clock_on_connect: bool = False
    sync_mode: str = "manual"
    show_details: bool = True
    toolbar_style: str = "large"
    rapi_proxy: str = "127.0.0.1:9990"
    frontend: str = "auto"
    language: str = ""
    naming: str = "classicsync"
    convert_files: bool = True
    device_to_desktop: dict = field(default_factory=dict)
    desktop_to_device: dict = field(default_factory=dict)
    last_frontend: str = ""
    last_upload_folder: str = ""
    last_download_folder: str = ""
    window_rect: list = field(default_factory=list)
    saved_passwords: dict = field(default_factory=dict)

    @classmethod
    def path(cls):
        return data_directory() / "settings.json"

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
