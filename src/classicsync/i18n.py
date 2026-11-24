import gettext
import locale
import os
import re
from pathlib import Path

from .paths import data_directory

DOMAIN = "classicsync"
LOCALE_DIRECTORY = Path(__file__).parent / "locale"

_translations = gettext.NullTranslations()
_language = None


def system_languages():
    languages = []
    for variable in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(variable)
        if value:
            languages.extend(part for part in value.split(":") if part)
    if not languages:
        try:
            code = locale.getlocale(locale.LC_MESSAGES)[0] if hasattr(locale, "LC_MESSAGES") else locale.getlocale()[0]
        except ValueError:
            code = None
        if code:
            languages.append(code)
    return [language.split(".")[0] for language in languages if language not in ("C", "POSIX")]


def imported_locale_directory():
    return data_directory() / "locale"


def locale_directories():
    return [imported_locale_directory(), LOCALE_DIRECTORY]


def available_languages():
    found = set()
    for directory in locale_directories():
        if directory.exists():
            found.update(path.parent.parent.name for path in directory.glob(f"*/LC_MESSAGES/{DOMAIN}.mo"))
    return sorted(found)


def load_translations(languages):
    translations = None
    for directory in locale_directories():
        for path in gettext.find(DOMAIN, directory, languages=languages, all=True):
            with open(path, "rb") as handle:
                catalog = gettext.GNUTranslations(handle)
            if translations is None:
                translations = catalog
            else:
                translations.add_fallback(catalog)
    return translations or gettext.NullTranslations()


def set_language(language=None):
    global _translations, _language
    languages = [language] if language else system_languages()
    _translations = load_translations(languages or None)
    _language = language or (languages[0] if languages else None)
    return _translations


def current_language():
    return _language


def _(message):
    return _translations.gettext(message) if message else message


def ngettext(singular, plural, count):
    return _translations.ngettext(singular, plural, count)


def pgettext(context, message):
    return _translations.pgettext(context, message)


def N_(message):
    return message


def menu_label(original):
    label, separator, accelerator = original.partition("\t")
    return _(original).partition("\t")[0] + separator + accelerator


def plain_newlines(text):
    return text.replace("\r\n", "\n")


FORMAT_MESSAGE_MARKER = re.compile(r"%[1-9]\d?(?![0-9.]*[a-zA-Z])")
FORMAT_MESSAGE_INSERT = re.compile(r"%(\d+)(?:!([^!]+)!)?|%([nt%.! ])")
PRINTF_CONVERSION = re.compile(r"%([-+ #0]*)(\*|\d+)?(?:\.(\*|\d+))?(hh|h|ll|l|I64|I32|L|w)?([diouxXeEfgGcCsSp%])")
FORMAT_MESSAGE_ESCAPES = {"n": "\n", "t": "\t", "%": "%", ".": ".", "!": "!", " ": " "}


def printf_conversion(flags, width, precision, conversion, value):
    conversion = {"C": "c", "S": "s", "p": "X"}.get(conversion, conversion)
    if conversion == "c" and isinstance(value, int):
        value = chr(value)
        conversion = "s"
    if conversion in "diouxX" and not isinstance(value, int):
        conversion = "s"
    specification = "%" + flags + (width or "") + (f".{precision}" if precision else "") + conversion
    return specification % value


def format_message_inserts(text, values):
    def insert(match):
        if match.group(3):
            return FORMAT_MESSAGE_ESCAPES[match.group(3)]
        value = values[int(match.group(1)) - 1]
        specification = PRINTF_CONVERSION.fullmatch("%" + (match.group(2) or "s"))
        if specification is None:
            return str(value)
        flags, width, precision, _, conversion = specification.groups()
        return printf_conversion(flags, width, precision, conversion, value)
    return FORMAT_MESSAGE_INSERT.sub(insert, text)


def format_printf(text, values):
    remaining = iter(values)

    def convert(match):
        flags, width, precision, _, conversion = match.groups()
        if conversion == "%":
            return "%"
        if width == "*":
            width = str(next(remaining))
        if precision == "*":
            precision = str(next(remaining))
        return printf_conversion(flags, width, precision, conversion, next(remaining))
    return PRINTF_CONVERSION.sub(convert, text)


def format_message(text, *values):
    return format_message_inserts(text, values)


def format_original(text, *values):
    if FORMAT_MESSAGE_MARKER.search(text):
        return format_message_inserts(text, values)
    return format_printf(text, values)
