import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..paths import data_directory
from .appmgr import AppManagerComponent, read_appmgr_ini
from .package import InstallError, read_cab_package

RECORD_FILE_NAME = "apps.json"


def appmgr_directory():
    return data_directory() / "appmgr"


@dataclass
class DesktopApp:
    name: str
    description: str
    ini_path: str
    cab_files: list = field(default_factory=list)
    uninstall: str = ""

    def to_component(self):
        return AppManagerComponent(
            name=self.name,
            description=self.description,
            cab_files=list(self.cab_files),
            uninstall=self.uninstall,
            ini_path=Path(self.ini_path) if self.ini_path else None,
        )


class DesktopAppRecords:
    def __init__(self, path=None):
        self.path = Path(path) if path else appmgr_directory() / RECORD_FILE_NAME
        self.apps = {}
        self.load()

    def load(self):
        try:
            stored = json.loads(self.path.read_text())
        except (OSError, ValueError):
            stored = []
        self.apps = {}
        for entry in stored if isinstance(stored, list) else []:
            known = {key: value for key, value in entry.items() if key in DesktopApp.__dataclass_fields__}
            try:
                app = DesktopApp(**known)
            except TypeError:
                continue
            self.apps[app.name.lower()] = app

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([asdict(app) for app in self.all()], indent=2))

    def all(self):
        return sorted(self.apps.values(), key=lambda app: app.name.lower())

    def get(self, name):
        return self.apps.get(name.lower())

    def add_component(self, component):
        app = DesktopApp(
            name=component.name,
            description=component.description,
            ini_path=str(Path(component.ini_path).resolve()) if component.ini_path else "",
            cab_files=list(component.cab_files),
            uninstall=component.uninstall,
        )
        self.apps[app.name.lower()] = app
        self.save()
        return app

    def add_cab(self, package):
        name = package.uninstall_name or Path(package.file_name).stem
        cab_files = [str(Path(package.path).resolve())] if package.path else []
        existing = self.apps.get(name.lower())
        if existing and not existing.ini_path:
            existing.cab_files = existing.cab_files + [cab for cab in cab_files if cab not in existing.cab_files]
            self.save()
            return existing
        app = DesktopApp(
            name=name,
            description=package.describe(),
            ini_path="",
            cab_files=cab_files,
            uninstall=package.uninstall_name,
        )
        self.apps[app.name.lower()] = app
        self.save()
        return app

    def add_file(self, path):
        path = Path(path)
        if path.suffix.lower() == ".ini":
            return [self.add_component(component) for component in read_appmgr_ini(path)]
        if path.suffix.lower() == ".cab":
            return [self.add_cab(read_cab_package(path))]
        raise InstallError(f"{path.name}: expected a .ini or .cab file")

    def remove(self, name):
        removed = self.apps.pop(name.lower(), None)
        if removed:
            self.save()
        return removed
