import importlib
import logging
import sys
from dataclasses import dataclass

log = logging.getLogger("classicsync.sync")


@dataclass(frozen=True)
class BuiltinPlugin:
    name: str
    module: str
    platform: str = ""
    extra: str = ""


BUILTIN_PLUGINS = (
    BuiltinPlugin("caldav", "classicsync.sync.providers.caldav.provider"),
    BuiltinPlugin("outlook", "classicsync.sync.providers.outlook.provider", "win32", "windows"),
    BuiltinPlugin("macos", "classicsync.sync.providers.macos.provider", "darwin", "macos"),
    BuiltinPlugin("favorites", "classicsync.sync.providers.favorites.provider"),
    BuiltinPlugin("notes", "classicsync.sync.providers.notes.provider"),
)


def load_builtin_plugins():
    providers = []
    errors = []
    for plugin in BUILTIN_PLUGINS:
        if plugin.platform and not sys.platform.startswith(plugin.platform):
            continue
        try:
            module = importlib.import_module(plugin.module)
        except ModuleNotFoundError as error:
            if error.name and plugin.module.startswith(error.name):
                continue
            hint = f" (install classicsync[{plugin.extra}])" if plugin.extra else ""
            log.info("built-in sync provider %s unavailable: %s", plugin.name, error)
            errors.append(f"{plugin.name}: {error}{hint}")
            continue
        except Exception as error:
            log.warning("built-in sync provider %s failed to load: %s", plugin.name, error)
            errors.append(f"{plugin.name}: {error}")
            continue
        providers.extend(module.PROVIDERS)
    return providers, errors
