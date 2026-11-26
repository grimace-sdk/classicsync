import importlib
import importlib.metadata
import importlib.util
import inspect
import logging
import os
import platform
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .. import __version__
from ..i18n import N_
from ..paths import plugins_directory, sync_plugins_directory
from .provider import Provider

log = logging.getLogger("classicsync.sync")

ENTRY_POINT_GROUP = "classicsync.sync_providers"
CONDUIT_ENTRY_POINT_GROUP = "classicsync.palm_conduits"
LIBRARY_FOLDER = "lib"

ORIGIN_BUILTIN = "built-in"
ORIGIN_ENVIRONMENT = "entry point"
ORIGIN_LIBRARY = "plugin library"
ORIGIN_FILE = "plugin file"
ORIGIN_LABELS = {
    ORIGIN_BUILTIN: N_("built-in"), ORIGIN_ENVIRONMENT: N_("installed package"), ORIGIN_LIBRARY: N_("plugin library"),
    ORIGIN_FILE: N_("plugin file"),
}


@dataclass
class PluginSource:
    name: str
    origin: str
    location: str = ""
    version: str = ""
    providers: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    conduits: list = field(default_factory=list)


def normalized_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def library_tag():
    return f"{sys.implementation.cache_tag}-{platform.machine().lower() or 'any'}"


def library_directory(plugin_directory=None):
    return Path(os.path.abspath(Path(plugin_directory or plugins_directory()) / LIBRARY_FOLDER / library_tag()))


def activate_library(plugin_directory=None):
    library = library_directory(plugin_directory)
    if not library.is_dir():
        return None
    if str(library) not in sys.path:
        sys.path.append(str(library))
        importlib.invalidate_caches()
    return library


def builtin_plugins():
    from .folder import FolderProvider
    from .providers import load_builtin_plugins
    providers, errors = load_builtin_plugins()
    return [FolderProvider, *providers], errors


def builtin_providers():
    return builtin_plugins()[0]


def builtin_conduits():
    from ..palm.conduits import CONDUITS
    return list(CONDUITS)


def conduits_in_module(module):
    from ..palm.conduit import Conduit, FreeformConduit, RecordConduit
    exported = getattr(module, "CONDUITS", None)
    if exported is not None:
        return list(exported)
    return [value for value in vars(module).values()
            if inspect.isclass(value) and issubclass(value, Conduit) and value not in (Conduit, RecordConduit, FreeformConduit)
            and value.__module__ == module.__name__ and value.name]


def providers_in_module(module):
    exported = getattr(module, "PROVIDERS", None)
    if exported is not None:
        return list(exported)
    return [value for value in vars(module).values()
            if inspect.isclass(value) and issubclass(value, Provider) and value is not Provider
            and value.__module__ == module.__name__ and value.name]


def distribution_location(distribution):
    try:
        return Path(os.path.normpath(os.fspath(distribution.locate_file(""))))
    except (TypeError, ValueError):
        return None


def is_inside(path, directory):
    return path is not None and directory is not None and (str(path) + os.sep).startswith(str(directory) + os.sep)


def distribution_entry_points(distribution):
    return [entry_point for entry_point in distribution.entry_points
            if entry_point.group in (ENTRY_POINT_GROUP, CONDUIT_ENTRY_POINT_GROUP)]


def source_from_distribution(distribution, origin):
    entry_points = distribution_entry_points(distribution)
    if not entry_points:
        return None
    source = PluginSource(distribution.metadata["Name"] or "", origin, str(distribution_location(distribution) or ""),
                          distribution.version or "")
    for entry_point in entry_points:
        try:
            loaded = entry_point.load()
        except Exception as error:
            log.warning("sync provider %s failed to load: %s", entry_point.name, error)
            source.errors.append(f"{entry_point.name}: {error}")
            continue
        if entry_point.group == CONDUIT_ENTRY_POINT_GROUP:
            source.conduits.extend(conduits_in_module(loaded) if inspect.ismodule(loaded) else [loaded])
        else:
            source.providers.extend(providers_in_module(loaded) if inspect.ismodule(loaded) else [loaded])
    return source


def environment_sources(library=None):
    sources = []
    seen = set()
    for distribution in importlib.metadata.distributions():
        name = normalized_name(distribution.metadata["Name"] or "")
        if name in seen or is_inside(distribution_location(distribution), library):
            continue
        seen.add(name)
        source = source_from_distribution(distribution, ORIGIN_ENVIRONMENT)
        if source:
            sources.append(source)
    return sources


def library_sources(library):
    if library is None or not library.is_dir():
        return []
    sources = []
    for distribution in importlib.metadata.distributions(path=[str(library)]):
        source = source_from_distribution(distribution, ORIGIN_LIBRARY)
        if source:
            sources.append(source)
    return sorted(sources, key=lambda source: normalized_name(source.name))


def load_plugin_module(path):
    module_name = f"classicsync_sync_plugin_{path.stem}"
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(module_name, loader=None, origin=str(path)))
    module.__file__ = str(path)
    code = compile(path.read_bytes(), str(path), "exec")
    sys.modules[module_name] = module
    try:
        exec(code, module.__dict__)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


def file_sources(directory):
    sources = []
    if directory is None or not directory.is_dir():
        return sources
    for path in sorted(directory.glob("*.py")):
        source = PluginSource(path.stem, ORIGIN_FILE, str(path))
        try:
            module = load_plugin_module(path)
            source.providers = providers_in_module(module)
            source.conduits = conduits_in_module(module)
            source.version = str(getattr(module, "__version__", ""))
        except Exception as error:
            log.warning("sync plugin %s failed to load: %s", path, error)
            source.errors.append(str(error))
        sources.append(source)
    return sources


def classicsync_version():
    try:
        return importlib.metadata.version("classicsync")
    except importlib.metadata.PackageNotFoundError:
        return __version__


def discover_plugins(plugin_directory=None):
    library = activate_library(plugin_directory)
    providers, errors = builtin_plugins()
    builtin = PluginSource("classicsync", ORIGIN_BUILTIN, version=classicsync_version(), providers=providers, errors=errors,
                           conduits=builtin_conduits())
    legacy_directory = None if plugin_directory else sync_plugins_directory()
    plugin_directory = Path(plugin_directory or plugins_directory())
    return [builtin, *environment_sources(library), *library_sources(library), *file_sources(legacy_directory),
            *file_sources(plugin_directory)]


def providers_from_sources(sources):
    providers = {}
    for source in sources:
        for provider in source.providers:
            if not getattr(provider, "name", ""):
                continue
            if provider.name in providers:
                log.info("sync provider %s from %s replaces an earlier one", provider.name, provider.__module__)
            providers[provider.name] = provider
    return providers


def load_providers(plugin_directory=None):
    return providers_from_sources(discover_plugins(plugin_directory))


def conduits_from_sources(sources):
    conduits = {}
    for source in sources:
        for conduit_class in source.conduits:
            if not getattr(conduit_class, "name", ""):
                continue
            if conduit_class.name in conduits:
                log.info("Palm conduit %s from %s replaces an earlier one", conduit_class.name, conduit_class.__module__)
            conduits[conduit_class.name] = conduit_class
    return conduits


def load_conduits(plugin_directory=None):
    return conduits_from_sources(discover_plugins(plugin_directory))
