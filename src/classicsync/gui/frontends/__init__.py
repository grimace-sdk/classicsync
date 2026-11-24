import importlib

from ...i18n import _

FRONTENDS = {
    "hpcexplorer11": ("classicsync.gui.frontends.hpcexplorer11", "HpcExplorerFrontend", "H/PC Explorer 1.1", (1,)),
    "ceservices22": ("classicsync.gui.frontends.ceservices22", "CeServicesFrontend", "Windows CE Services 2.2", (2,)),
    "activesync31": ("classicsync.gui.frontends.activesync31", "ActiveSyncFrontend", "ActiveSync 3.1", (3,)),
}

AUTOMATIC = "auto"
DEFAULT_IDLE = "activesync31"


def available_frontends():
    found = {}
    for key, (module_name, class_name, label, versions) in FRONTENDS.items():
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        frontend_class = getattr(module, class_name, None)
        if frontend_class:
            found[key] = frontend_class
    return found


def frontend_for_version(major, available):
    for key, (module_name, class_name, label, versions) in FRONTENDS.items():
        if major in versions and key in available:
            return key
    return DEFAULT_IDLE if DEFAULT_IDLE in available else next(iter(available))


def frontend_label(key):
    return FRONTENDS[key][2] if key in FRONTENDS else _("Automatic (match the device)")
