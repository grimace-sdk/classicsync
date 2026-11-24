import base64
import csv
import email.parser
import importlib.metadata
import os
import re
import hashlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

from .. import __version__
from ..i18n import _
from ..paths import plugins_directory
from .plugins import (
    ENTRY_POINT_GROUP, ORIGIN_FILE, ORIGIN_LIBRARY, discover_plugins, distribution_location, is_inside, library_directory,
    library_tag, load_plugin_module, normalized_name, providers_in_module,
)
from .state import read_json, write_json_atomically

MANIFEST_FILE = "manifest.json"
MANIFEST_VERSION = 1
KIND_FILE = "file"
KIND_PACKAGE = "package"
TOOL_UV = "uv"
TOOL_PIP = "pip"
TOOL_DIRECT = "direct"
HOST_DISTRIBUTION = "classicsync"
INSTALLER_NAME = "classicsync"
INSTALLER_OUTPUT_LINES = 12
WHEEL_DATA_SCHEMES = ("purelib", "platlib")
REQUIREMENT_NAME = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
EGG_FRAGMENT = re.compile(r"[#&]egg=([A-Za-z0-9][A-Za-z0-9._-]*)")
EXTRA_MARKER = re.compile(r"\bextra\s*==")
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


class PluginError(ValueError):
    pass


@dataclass
class InstalledPlugin:
    name: str
    kind: str
    spec: str
    version: str = ""
    providers: list = field(default_factory=list)
    file: str = ""
    library: str = ""
    tool: str = ""
    installed: str = ""
    errors: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, name, stored):
        known = {key: value for key, value in stored.items() if key in {item.name for item in fields(cls)} and key != "errors"}
        return cls(**{**known, "name": name})

    def to_dict(self):
        stored = asdict(self)
        stored.pop("name")
        stored.pop("errors")
        return stored


@dataclass
class LibraryDistribution:
    name: str
    version: str
    path: Path
    requires: list
    entry_points: list


@dataclass
class Installer:
    tool: str
    executable: str

    def install_command(self, target, spec, upgrade=False, reinstall_names=(), find_links=None):
        links = ["--find-links", str(find_links)] if find_links else []
        if self.tool == TOOL_UV:
            if is_bundled():
                python = ["--python-version", f"{sys.version_info.major}.{sys.version_info.minor}"]
            else:
                python = ["--python", sys.executable]
            upgrade_arguments = ["--upgrade"] if upgrade else []
            for name in reinstall_names:
                upgrade_arguments += ["--reinstall-package", name]
            return [self.executable, "pip", "install", *python, "--target", str(target), *links, *upgrade_arguments, spec]
        return [self.executable, "-m", "pip", "install", "--target", str(target), *links, "--upgrade", "--no-input",
                "--disable-pip-version-check", spec]


def is_bundled():
    return bool(getattr(sys, "frozen", False))


def uv_candidates():
    candidates = [os.environ.get("UV"), shutil.which("uv")]
    try:
        import uv
        candidates.append(uv.find_uv_bin())
    except (ImportError, FileNotFoundError):
        pass
    name = "uv.exe" if os.name == "nt" else "uv"
    places = [Path.home() / ".local" / "bin", Path.home() / ".cargo" / "bin", Path(sys.executable).parent]
    if os.environ.get("LOCALAPPDATA"):
        places.append(Path(os.environ["LOCALAPPDATA"]) / "uv" / "bin")
    return candidates + [str(place / name) for place in places]


def find_uv():
    for candidate in uv_candidates():
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def pip_available():
    if is_bundled():
        return False
    try:
        subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True, check=True, **NO_WINDOW)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def find_installer():
    uv = find_uv()
    if uv:
        return Installer(TOOL_UV, uv)
    if pip_available():
        return Installer(TOOL_PIP, sys.executable)
    return None


def manifest_path(plugin_directory):
    return plugin_directory / MANIFEST_FILE


def load_manifest(plugin_directory=None):
    plugin_directory = Path(plugin_directory or plugins_directory())
    stored = read_json(manifest_path(plugin_directory), {})
    entries = stored.get("plugins", {}) if isinstance(stored, dict) else {}
    return {name: InstalledPlugin.from_dict(name, entry) for name, entry in entries.items() if isinstance(entry, dict)}


def save_manifest(manifest, plugin_directory=None):
    plugin_directory = Path(plugin_directory or plugins_directory())
    write_json_atomically(manifest_path(plugin_directory), {
        "version": MANIFEST_VERSION, "plugins": {name: entry.to_dict() for name, entry in sorted(manifest.items())},
    })


def find_manifest_entry(manifest, name):
    wanted = normalized_name(name)
    for entry in manifest.values():
        if normalized_name(entry.name) == wanted:
            return entry
    for entry in manifest.values():
        if name in entry.providers or (entry.file and Path(entry.file).stem == name):
            return entry
    return None


def requirement_name(requirement):
    requirement_part, separator, marker = requirement.partition(";")
    if EXTRA_MARKER.search(marker):
        return None
    match = REQUIREMENT_NAME.match(requirement_part)
    return normalized_name(match.group(1)) if match else None


def requested_name(spec):
    egg = EGG_FRAGMENT.search(spec)
    if egg:
        return normalized_name(egg.group(1))
    path = Path(spec)
    if path.suffix == ".whl":
        return normalized_name(path.name.split("-")[0])
    if path.exists() or "://" in spec or os.sep in spec or "/" in spec:
        return None
    return requirement_name(spec)


def library_distributions(library):
    found = {}
    if not library.is_dir():
        return found
    for path in sorted(library.glob("*.dist-info")):
        distribution = importlib.metadata.Distribution.at(path)
        name = distribution.metadata["Name"]
        if not name:
            continue
        entry_points = [entry_point.name for entry_point in distribution.entry_points if entry_point.group == ENTRY_POINT_GROUP]
        found[normalized_name(name)] = LibraryDistribution(name, distribution.version, path, list(distribution.requires or []),
                                                           entry_points)
    return found


def running_distributions(library):
    found = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata["Name"]
        if name and not is_inside(distribution_location(distribution), library):
            found.setdefault(normalized_name(name), distribution.version)
    return found


def remove_empty_directories(directory, library):
    while directory != library and is_inside(directory, library) and directory.is_dir() and not any(directory.iterdir()):
        directory.rmdir()
        directory = directory.parent


def remove_distribution(library, distribution):
    record = distribution.path / "RECORD"
    touched_directories = set()
    if record.is_file():
        with record.open(newline="", encoding="utf-8") as handle:
            rows = [row for row in csv.reader(handle) if row]
        for row in rows:
            path = Path(os.path.normpath(library / row[0]))
            if is_inside(path, library) and (path.is_file() or path.is_symlink()):
                path.unlink()
                touched_directories.add(path.parent)
    shutil.rmtree(distribution.path, ignore_errors=True)
    for directory in sorted(touched_directories, key=lambda path: len(path.parts), reverse=True):
        cache = directory / "__pycache__"
        if cache.is_dir():
            shutil.rmtree(cache, ignore_errors=True)
        remove_empty_directories(directory, library)


def prune_library(library):
    running = running_distributions(library)
    pruned = []
    for name, distribution in library_distributions(library).items():
        if name == HOST_DISTRIBUTION or running.get(name) == distribution.version:
            remove_distribution(library, distribution)
            pruned.append(distribution.name)
    return pruned


def remove_orphans(library, manifest):
    distributions = library_distributions(library)
    wanted = [normalized_name(entry.name) for entry in manifest.values() if entry.kind == KIND_PACKAGE]
    keep = set()
    while wanted:
        name = wanted.pop()
        if name in keep or name not in distributions:
            continue
        keep.add(name)
        wanted.extend(filter(None, map(requirement_name, distributions[name].requires)))
    removed = []
    for name, distribution in distributions.items():
        if name not in keep:
            remove_distribution(library, distribution)
            removed.append(distribution.name)
    return removed


def last_lines(text):
    return "\n".join(text.strip().splitlines()[-INSTALLER_OUTPUT_LINES:])


def record_hash(data):
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
    return f"sha256={digest}"


def write_host_wheel(directory):
    version = __version__
    dist_info = f"{HOST_DISTRIBUTION}-{version}.dist-info"
    files = {
        f"{dist_info}/METADATA": f"Metadata-Version: 2.1\nName: {HOST_DISTRIBUTION}\nVersion: {version}\n".encode(),
        f"{dist_info}/WHEEL": b"Wheel-Version: 1.0\nGenerator: classicsync\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record_lines = [f"{name},{record_hash(data)},{len(data)}\n" for name, data in files.items()]
    files[f"{dist_info}/RECORD"] = ("".join(record_lines) + f"{dist_info}/RECORD,,\n").encode()
    wheel = directory / f"{HOST_DISTRIBUTION}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return wheel


def run_installer(installer, library, spec, upgrade, known_names):
    with tempfile.TemporaryDirectory(prefix="classicsync-host-") as host_directory:
        write_host_wheel(Path(host_directory))
        command = installer.install_command(library, spec, upgrade, known_names if upgrade else (), host_directory)
        try:
            done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
                                  **NO_WINDOW)
        except OSError as error:
            raise PluginError(_("could not run {tool}: {error}").format(tool=installer.tool, error=error)) from error
    if done.returncode != 0:
        output = last_lines(done.stderr or done.stdout or "")
        raise PluginError(_("{tool} could not install {spec}:\n{output}").format(tool=installer.tool, spec=spec, output=output))


def missing_requirements(requires, library):
    available = {HOST_DISTRIBUTION, *running_distributions(library), *library_distributions(library)}
    names = [requirement_name(requirement) for requirement in requires]
    return sorted({name for name in names if name and name not in available})


def wheel_members(archive, dist_info, library):
    data_prefix = dist_info[:-len(".dist-info")] + ".data/"
    members = []
    for member in archive.infolist():
        if member.is_dir():
            continue
        relative = member.filename
        if relative.startswith(data_prefix):
            scheme, separator, inner = relative[len(data_prefix):].partition("/")
            if scheme not in WHEEL_DATA_SCHEMES:
                continue
            relative = inner
        target = Path(os.path.normpath(library / relative))
        if not is_inside(target, library):
            raise PluginError(_("{wheel} contains an unsafe path: {path}").format(wheel=archive.filename, path=member.filename))
        members.append((member, relative, target))
    return members


def unpack_wheel(wheel, library):
    if not wheel.name.endswith("-none-any.whl"):
        raise PluginError(_("{wheel} is built for a particular platform; installing it needs uv or pip").format(wheel=wheel.name))
    try:
        archive = zipfile.ZipFile(wheel)
    except (OSError, zipfile.BadZipFile) as error:
        raise PluginError(_("{wheel} is not a wheel: {error}").format(wheel=wheel.name, error=error)) from error
    with archive:
        names = archive.namelist()
        dist_info = next((name.split("/")[0] for name in names if name.count("/") == 1 and name.endswith(".dist-info/METADATA")), None)
        if dist_info is None:
            raise PluginError(_("{wheel} is not a wheel: it has no .dist-info/METADATA").format(wheel=wheel.name))
        metadata = email.parser.BytesParser().parsebytes(archive.read(f"{dist_info}/METADATA"))
        wheel_info = archive.read(f"{dist_info}/WHEEL").decode("utf-8", "replace") if f"{dist_info}/WHEEL" in names else ""
        if "root-is-purelib: true" not in wheel_info.lower():
            raise PluginError(_("{wheel} contains compiled code; installing it needs uv or pip").format(wheel=wheel.name))
        missing = missing_requirements(metadata.get_all("Requires-Dist") or [], library)
        if missing:
            raise PluginError(_("{wheel} needs {requirements}, and installing those needs uv or pip").format(
                wheel=wheel.name, requirements=", ".join(missing)))
        members = wheel_members(archive, dist_info, library)
        existing = library_distributions(library).get(normalized_name(metadata["Name"] or ""))
        if existing:
            remove_distribution(library, existing)
        for member, relative, target in members:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))
    written = [relative for member, relative, target in members if not relative.startswith(f"{dist_info}/RECORD")]
    (library / dist_info / "INSTALLER").write_text(INSTALLER_NAME + "\n", encoding="utf-8")
    with (library / dist_info / "RECORD").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        for relative in [*written, f"{dist_info}/INSTALLER", f"{dist_info}/RECORD"]:
            writer.writerow([relative, "", ""])


def install_distributions(spec, library, installer, upgrade, known_names=()):
    library.mkdir(parents=True, exist_ok=True)
    before = {name: distribution.version for name, distribution in library_distributions(library).items()}
    if installer:
        run_installer(installer, library, spec, upgrade, known_names)
    else:
        unpack_wheel(Path(spec), library)
    prune_library(library)
    after = library_distributions(library)
    changed = [distribution for name, distribution in after.items() if before.get(name) != distribution.version]
    plugins = [distribution for distribution in changed if distribution.entry_points]
    if not plugins:
        wanted = {normalized_name(name) for name in known_names} | {requested_name(spec)}
        plugins = [distribution for name, distribution in after.items() if name in wanted and distribution.entry_points]
    if not plugins:
        for distribution in changed:
            remove_distribution(library, distribution)
        raise PluginError(_("{spec} has no {group} entry points, so it is not a classicsync plugin").format(
            spec=spec, group=ENTRY_POINT_GROUP))
    return plugins


def install_file(path, plugin_directory):
    try:
        module = load_plugin_module(path)
        providers = providers_in_module(module)
    except Exception as error:
        raise PluginError(_("{file} failed to load: {error}").format(file=path.name, error=error)) from error
    if not providers:
        raise PluginError(_("{file} defines no sync provider (a Provider subclass with a name)").format(file=path.name))
    plugin_directory.mkdir(parents=True, exist_ok=True)
    target = plugin_directory / path.name
    if path.resolve() != target.resolve():
        shutil.copy2(path, target)
    return InstalledPlugin(path.stem, KIND_FILE, str(path), str(getattr(module, "__version__", "")), file=path.name,
                           tool=TOOL_DIRECT)


def needs_resolver_message(spec):
    return _("installing {spec} needs uv or pip, and neither is available here. Install uv (https://docs.astral.sh/uv/), "
             "or install a .py file or a pure-Python wheel (.whl) of the plugin instead.").format(spec=spec)


def describe_loaded(entries, plugin_directory):
    sources = {}
    for source in discover_plugins(plugin_directory):
        if source.origin in (ORIGIN_LIBRARY, ORIGIN_FILE):
            sources[(source.origin, normalized_name(source.name))] = source
    for entry in entries:
        origin = ORIGIN_FILE if entry.kind == KIND_FILE else ORIGIN_LIBRARY
        source = sources.get((origin, normalized_name(entry.name if entry.kind == KIND_PACKAGE else Path(entry.file).stem)))
        if source:
            entry.providers = [provider.name for provider in source.providers if getattr(provider, "name", "")]
            entry.errors = list(source.errors)
    return entries


def install_plugin(spec, plugin_directory=None, upgrade=False):
    plugin_directory = Path(plugin_directory or plugins_directory())
    path = Path(spec).expanduser()
    if path.exists():
        spec = str(path.resolve())
        path = Path(spec)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest = load_manifest(plugin_directory)
    if path.suffix == ".py" and path.is_file():
        entries = [install_file(path, plugin_directory)]
    else:
        known_names = [entry.name for entry in manifest.values() if entry.kind == KIND_PACKAGE and entry.spec == spec]
        installer = find_installer()
        if installer is None and not (path.suffix == ".whl" and path.is_file()):
            raise PluginError(needs_resolver_message(spec))
        tool = installer.tool if installer else TOOL_DIRECT
        distributions = install_distributions(spec, library_directory(plugin_directory), installer, upgrade, known_names)
        entries = [InstalledPlugin(distribution.name, KIND_PACKAGE, spec, distribution.version, library=library_tag(), tool=tool)
                   for distribution in distributions]
    for entry in describe_loaded(entries, plugin_directory):
        entry.installed = now
        existing = find_manifest_entry(manifest, entry.name)
        if existing and existing.kind == entry.kind:
            manifest.pop(existing.name)
        manifest[entry.name] = entry
    save_manifest(manifest, plugin_directory)
    return entries


def remove_plugin(name, plugin_directory=None):
    plugin_directory = Path(plugin_directory or plugins_directory())
    library = library_directory(plugin_directory)
    manifest = load_manifest(plugin_directory)
    entry = find_manifest_entry(manifest, name)
    if entry is None:
        loose_file = plugin_directory / f"{name}.py"
        if loose_file.is_file():
            loose_file.unlink()
            return InstalledPlugin(name, KIND_FILE, str(loose_file), file=loose_file.name)
        raise PluginError(_("no plugin called {name} was installed with 'classicsync plugin install'").format(name=name))
    if entry.kind == KIND_FILE:
        (plugin_directory / entry.file).unlink(missing_ok=True)
    else:
        distribution = library_distributions(library).get(normalized_name(entry.name))
        if distribution:
            remove_distribution(library, distribution)
    manifest.pop(entry.name)
    remove_orphans(library, manifest)
    save_manifest(manifest, plugin_directory)
    return entry


def update_plugin(name, plugin_directory=None):
    plugin_directory = Path(plugin_directory or plugins_directory())
    entry = find_manifest_entry(load_manifest(plugin_directory), name)
    if entry is None:
        raise PluginError(_("no plugin called {name} was installed with 'classicsync plugin install'").format(name=name))
    if entry.kind == KIND_FILE and not Path(entry.spec).is_file():
        raise PluginError(_("{name} was installed from {spec}, which no longer exists; install it again from its new location").format(
            name=entry.name, spec=entry.spec))
    return install_plugin(entry.spec, plugin_directory, upgrade=True)


def plugin_present(entry, plugin_directory=None):
    plugin_directory = Path(plugin_directory or plugins_directory())
    if entry.kind == KIND_FILE:
        return (plugin_directory / entry.file).is_file()
    return normalized_name(entry.name) in library_distributions(library_directory(plugin_directory))
