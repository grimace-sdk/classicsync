from dataclasses import dataclass, field
from pathlib import Path

from .package import InstallError, compatibility_problem, is_exact_processor, read_cab_package

HEADER_SECTION = "CEAppManager"
SUPPORTED_VERSION = "1.0"


@dataclass
class AppManagerComponent:
    name: str
    description: str
    cab_files: list
    uninstall: str
    ini_path: Path = None
    extra: dict = field(default_factory=dict)

    @property
    def directory(self):
        return self.ini_path.parent if self.ini_path else Path(".")

    def cab_paths(self):
        return [resolve_case_insensitive(self.directory, name) for name in self.cab_files]

    def packages(self):
        found = []
        for path in self.cab_paths():
            if path.exists():
                found.append(read_cab_package(path))
        return found


def resolve_case_insensitive(directory, name):
    candidate = Path(directory) / name.replace("\\", "/")
    if candidate.exists():
        return candidate
    try:
        for entry in candidate.parent.iterdir():
            if entry.name.lower() == candidate.name.lower():
                return entry
    except OSError:
        pass
    return candidate


def parse_ini_sections(text):
    sections = {}
    current = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("[") and "]" in line:
            name = line[1:line.index("]")].strip()
            current = sections.setdefault(name.lower(), {"__name__": name})
            continue
        if current is None or "=" not in line:
            continue
        key, _, value = line.partition("=")
        current.setdefault(key.strip().lower(), value.strip())
    return sections


def split_list(value):
    return [item.strip().strip('"') for item in value.split(",") if item.strip()]


def parse_appmgr_ini(text, ini_path=None):
    label = str(ini_path) if ini_path else "INI file"
    sections = parse_ini_sections(text)
    header = sections.get(HEADER_SECTION.lower())
    if header is None:
        raise InstallError(f"Could not find the \"{HEADER_SECTION}\" header in the file \"{label}\".")
    if header.get("version", "") != SUPPORTED_VERSION:
        raise InstallError(f"The file \"{label}\" contains an unsupported version number.")
    component_names = split_list(header.get("component", ""))
    if not component_names:
        raise InstallError(f"Error: Could not find section \"[{HEADER_SECTION}]\", key \"Component\"")
    components = []
    for name in component_names:
        section = sections.get(name.lower())
        if section is None:
            raise InstallError(f"Could not find the application component \"{name}\" in the file \"{label}\"")
        cab_files = split_list(section.get("cabfiles", ""))
        if not cab_files:
            raise InstallError("There are no CAB files listed.")
        extra = {key: value for key, value in section.items() if key not in ("__name__", "description", "cabfiles", "uninstall")}
        components.append(AppManagerComponent(
            name=section["__name__"],
            description=section.get("description", name),
            cab_files=cab_files,
            uninstall=section.get("uninstall", ""),
            ini_path=Path(ini_path) if ini_path else None,
            extra=extra,
        ))
    return components


def read_appmgr_ini(path):
    path = Path(path)
    try:
        text = path.read_bytes().decode("cp1252", errors="replace")
    except OSError as error:
        raise InstallError(f"Cannot open file \"{path}\"") from error
    return parse_appmgr_ini(text, path)


def select_package(packages, profile):
    chosen = None
    for package in packages:
        if compatibility_problem(package, profile):
            continue
        if is_exact_processor(package, profile):
            return package
        if chosen is None:
            chosen = package
    return chosen


def select_component_package(component, profile):
    packages = component.packages()
    if not packages:
        raise InstallError(f"Cannot read the source file.  Reinstall the setup program for this application and try again. ({component.name})")
    package = select_package(packages, profile)
    if package is None:
        raise InstallError(f"{component.name} does not support the connected device type.")
    return package
