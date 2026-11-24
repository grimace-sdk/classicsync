import os
import sys
from pathlib import Path


def data_directory():
    if os.environ.get("CLASSICSYNC_HOME"):
        return Path(os.environ["CLASSICSYNC_HOME"])
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "classicsync"


def user_data_directory():
    if os.environ.get("CLASSICSYNC_HOME"):
        return Path(os.environ["CLASSICSYNC_HOME"]) / "data"
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "classicsync"


def partnerships_directory():
    return data_directory() / "partnerships"


def sync_plugins_directory():
    return data_directory() / "sync-plugins"


def plugins_directory():
    return data_directory() / "plugins"
