import re

from ..i18n import N_, _

PRODUCT_NAME = "ClassicSync"

NAMING_CLASSICSYNC = "classicsync"
NAMING_AUTHENTIC = "authentic"

PRODUCT_TITLES = {
    "hpcexplorer11": "H/PC Explorer",
    "ceservices22": "Windows CE Services",
    "activesync31": "ActiveSync",
}

AUTHENTIC_TITLES = {
    "hpcexplorer11": "Microsoft H/PC Explorer",
    "ceservices22": "Microsoft Windows CE Services",
    "activesync31": "Microsoft ActiveSync",
}

FRONTEND_STYLES = {
    "hpcexplorer11": "H/PC Explorer 1.1",
    "ceservices22": "Windows CE Services 2.2",
    "activesync31": "ActiveSync 3.1",
}

ORIGINAL_PRODUCT_NAMES = {
    "hpcexplorer11": ("Microsoft H/PC Explorer", "Handheld PC Explorer", "H/PC Explorer"),
    "ceservices22": ("Microsoft Windows CE Services", "Windows CE Services"),
    "activesync31": ("Microsoft ActiveSync", "ActiveSync"),
}

ORIGINAL_VERSION_LINES = {
    "hpcexplorer11": N_("Microsoft H/PC Explorer Version 1.1"),
    "ceservices22": N_("Microsoft\u00ae Windows\u00ae CE Services Version 2.2"),
    "activesync31": N_("Microsoft\u00ae ActiveSync\u00ae Version 3.1"),
}

REGISTERED_MARK = "\u00ae"

_naming = NAMING_CLASSICSYNC


def set_naming(naming):
    global _naming
    _naming = naming if naming in (NAMING_CLASSICSYNC, NAMING_AUTHENTIC) else NAMING_CLASSICSYNC


def authentic():
    return _naming == NAMING_AUTHENTIC


def identity(frontend_key=None):
    if authentic() and frontend_key in AUTHENTIC_TITLES:
        return AUTHENTIC_TITLES[frontend_key]
    return PRODUCT_NAME


def title(frontend_key=None):
    if authentic() and frontend_key in AUTHENTIC_TITLES:
        return AUTHENTIC_TITLES[frontend_key]
    return PRODUCT_TITLES.get(frontend_key, PRODUCT_NAME)


def style_name(frontend_key):
    return FRONTEND_STYLES.get(frontend_key, PRODUCT_NAME)


def product_name_pattern(name):
    words = [re.escape(word) + "(?:" + REGISTERED_MARK + ")?" for word in name.split(" ")]
    return " ".join(words)


def rebrand(text, frontend_key):
    if authentic():
        return text
    names = ORIGINAL_PRODUCT_NAMES.get(frontend_key, ())
    if not names:
        return text
    pattern = "|".join(product_name_pattern(name) for name in names)
    return re.sub(pattern, PRODUCT_NAME, text)


def about_headline(frontend_key, version):
    if authentic() and frontend_key in ORIGINAL_VERSION_LINES:
        return _(ORIGINAL_VERSION_LINES[frontend_key])
    return _("{product} {version} ({style} style)").format(product=PRODUCT_NAME, version=version,
                                                          style=style_name(frontend_key))


def disclaimer():
    return _("ClassicSync is not affiliated with Microsoft. Windows CE, Handheld PC Explorer and ActiveSync are trademarks of "
             "Microsoft Corporation.")


