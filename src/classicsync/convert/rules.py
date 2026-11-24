import os

from .registry import DESKTOP_DEFAULTS, FORMATS, format_for_extension

NO_CONVERSION = ""
DEVICE_TO_DESKTOP = "device to desktop"
DESKTOP_TO_DEVICE = "desktop to device"

DESKTOP_TO_DEVICE_DEFAULTS = {"docx": "pwd", "rtf": "pwd", "xlsx": "pxl"}
LEGACY_DESKTOP_TO_DEVICE_DEFAULTS = {"bmp": "2bp", "png": "2bp", "ttf": "fnt", "fon": "fnt"}


def device_sources():
    return sorted(name for name, format in FORMATS.items() if format.device and format.reader is not None)


def desktop_sources():
    device_kinds = {format.kind for format in FORMATS.values() if format.device}
    return sorted(name for name, format in FORMATS.items() if not format.device and format.kind in device_kinds)


def sources(direction):
    return device_sources() if direction == DEVICE_TO_DESKTOP else desktop_sources()


def targets(direction, source):
    kind = FORMATS[source].kind
    wanted_device = direction == DESKTOP_TO_DEVICE
    return [name for name, format in FORMATS.items() if format.kind == kind and format.device == wanted_device and name != source]


def default_rule(direction, source, version=2):
    if direction == DEVICE_TO_DESKTOP:
        return DESKTOP_DEFAULTS.get(source, NO_CONVERSION)
    target = DESKTOP_TO_DEVICE_DEFAULTS.get(source)
    if not target and version == 1:
        target = LEGACY_DESKTOP_TO_DEVICE_DEFAULTS.get(source)
    return target or NO_CONVERSION


def rule(direction, source, overrides=None, version=2):
    chosen = (overrides or {}).get(source)
    if chosen is not None and (chosen == NO_CONVERSION or chosen in targets(direction, source)):
        return chosen
    return default_rule(direction, source, version)


def converted_name(name, target):
    return os.path.splitext(name)[0] + FORMATS[target].extensions[0]


def plan_conversion(direction, name, overrides=None, version=2):
    source = format_for_extension(os.path.splitext(name)[1])
    if source not in sources(direction):
        return None
    target = rule(direction, source, overrides, version)
    if not target:
        return None
    return source, target, converted_name(name, target)


def desktop_conversion(name, overrides=None):
    return plan_conversion(DEVICE_TO_DESKTOP, name, overrides)


def device_conversion(name, version=2, overrides=None):
    return plan_conversion(DESKTOP_TO_DEVICE, name, overrides, version)
