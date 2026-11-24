import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .artwork_import import archive_members, base_name, detect_product
from .formats.msi import MsiError, is_msi, read_msi
from .formats.win32_resources import (
    RESOURCE_DIALOG, RESOURCE_MENU, RESOURCE_MESSAGE_TABLE, RESOURCE_STRING, UNUSED_CONTROL_ID, ResourceError, is_pe,
    parse_dialog, parse_menu, parse_message_table, parse_string_block, read_resources,
)
from .i18n_catalogs import compile_entries, header_entry, header_fields, write_po
from .paths import data_directory

TEXT_RESOURCE_TYPES = (RESOURCE_STRING, RESOURCE_DIALOG, RESOURCE_MENU, RESOURCE_MESSAGE_TABLE)
KIND_NAMES = {RESOURCE_STRING: "string", RESOURCE_DIALOG: "dialog", RESOURCE_MENU: "menu",
              RESOURCE_MESSAGE_TABLE: "message"}
INSTALLER_SUFFIXES = (".msi", ".exe")
PRIMARY_LANGUAGE_MASK = 0x3FF
LANGUAGE_ENGLISH = 0x09
NEUTRAL_LANGUAGES = (0x0000, 0x0400, 0x0800, 0x7F)
UNUSED_EXTENDED_CONTROL_ID = 0xFFFFFFFF
MAXIMUM_REFERENCES = 3
GETTEXT_SEPARATORS = ("\0", "\x04")
BRACKETED_ACCELERATOR = re.compile(r"\s?\(&[^&)]\)")
ESCAPED_OR_PLAIN_ACCELERATOR = re.compile(r"&(.)")

SINGLE_PLURAL = "nplurals=1; plural=0;"
GERMANIC_PLURAL = "nplurals=2; plural=(n != 1);"
FRENCH_PLURAL = "nplurals=2; plural=(n > 1);"
SLAVIC_PLURAL = ("nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) "
                 "? 1 : 2);")

LANGUAGES = {
    0x0401: ("ar", "cp1256", "nplurals=6; plural=(n==0 ? 0 : n==1 ? 1 : n==2 ? 2 : n%100>=3 && n%100<=10 ? 3 "
                             ": n%100>=11 ? 4 : 5);"),
    0x0404: ("zh_TW", "cp950", SINGLE_PLURAL),
    0x0405: ("cs", "cp1250", "nplurals=3; plural=(n==1) ? 0 : (n>=2 && n<=4) ? 1 : 2;"),
    0x0406: ("da", "cp1252", GERMANIC_PLURAL),
    0x0407: ("de", "cp1252", GERMANIC_PLURAL),
    0x0408: ("el", "cp1253", GERMANIC_PLURAL),
    0x0409: ("en", "cp1252", GERMANIC_PLURAL),
    0x040A: ("es", "cp1252", GERMANIC_PLURAL),
    0x040B: ("fi", "cp1252", GERMANIC_PLURAL),
    0x040C: ("fr", "cp1252", FRENCH_PLURAL),
    0x040D: ("he", "cp1255", GERMANIC_PLURAL),
    0x040E: ("hu", "cp1250", GERMANIC_PLURAL),
    0x0410: ("it", "cp1252", GERMANIC_PLURAL),
    0x0411: ("ja", "cp932", SINGLE_PLURAL),
    0x0412: ("ko", "cp949", SINGLE_PLURAL),
    0x0413: ("nl", "cp1252", GERMANIC_PLURAL),
    0x0414: ("nb", "cp1252", GERMANIC_PLURAL),
    0x0415: ("pl", "cp1250", "nplurals=3; plural=(n==1 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) "
                             "? 1 : 2);"),
    0x0416: ("pt_BR", "cp1252", FRENCH_PLURAL),
    0x0419: ("ru", "cp1251", SLAVIC_PLURAL),
    0x041D: ("sv", "cp1252", GERMANIC_PLURAL),
    0x041F: ("tr", "cp1254", GERMANIC_PLURAL),
    0x0804: ("zh_CN", "cp936", SINGLE_PLURAL),
    0x0816: ("pt", "cp1252", GERMANIC_PLURAL),
    0x0C0A: ("es", "cp1252", GERMANIC_PLURAL),
}


class TranslationImportError(ValueError):
    pass


def language_details(language_id):
    if language_id in LANGUAGES:
        return LANGUAGES[language_id]
    for known_id, details in LANGUAGES.items():
        if known_id & PRIMARY_LANGUAGE_MASK == language_id & PRIMARY_LANGUAGE_MASK:
            return details
    return (f"lcid{language_id:04x}", "cp1252", GERMANIC_PLURAL)


def language_code(language_id):
    return language_details(language_id)[0]


def is_english(language_id):
    return language_id & PRIMARY_LANGUAGE_MASK == LANGUAGE_ENGLISH


def is_neutral(language_id):
    return language_id in NEUTRAL_LANGUAGES or not language_id & PRIMARY_LANGUAGE_MASK


def has_letters(text):
    return any(character.isalpha() for character in text)


def control_keys(controls):
    counts = Counter(control.control_id for control in controls)
    keys = []
    for index, control in enumerate(controls):
        unused = control.control_id in (UNUSED_CONTROL_ID, UNUSED_EXTENDED_CONTROL_ID, 0)
        if unused or counts[control.control_id] > 1:
            keys.append(f"#{index}")
        else:
            keys.append(str(control.control_id))
    return keys


def menu_keys(items):
    counts = Counter(item.item_id for item in items if not item.is_popup)
    keys = []
    for item in items:
        if item.is_popup or not item.item_id or counts[item.item_id] > 1:
            keys.append("/".join(str(position) for position in item.path))
        else:
            keys.append(str(item.item_id))
    return keys


def resource_texts(resource, codec):
    kind = KIND_NAMES[resource.type_id]
    name = str(resource.name)
    if resource.type_id == RESOURCE_STRING:
        for string_id, text in parse_string_block(resource.name, resource.data).items():
            yield (kind, "", str(string_id)), text
    elif resource.type_id == RESOURCE_DIALOG:
        dialog = parse_dialog(resource.data)
        yield (kind, name, "caption"), dialog.caption
        for key, control in zip(control_keys(dialog.controls), dialog.controls):
            if isinstance(control.text, str):
                yield (kind, name, key), control.text
    elif resource.type_id == RESOURCE_MENU:
        items = parse_menu(resource.data)
        for key, item in zip(menu_keys(items), items):
            yield (kind, name, key), item.text
    elif resource.type_id == RESOURCE_MESSAGE_TABLE:
        for message_id, text in parse_message_table(resource.data, codec).items():
            yield (kind, name, str(message_id)), text


@dataclass
class Module:
    name: str
    resources: list
    cached_texts: dict = field(default_factory=dict)

    def languages(self):
        return Counter(resource.language for resource in self.resources if resource.type_id in TEXT_RESOURCE_TYPES)

    def texts(self, language_id):
        if language_id not in self.cached_texts:
            self.cached_texts[language_id] = self.read_texts(language_id)
        return self.cached_texts[language_id]

    def read_texts(self, language_id):
        chosen = {}
        for resource in self.resources:
            if resource.type_id not in TEXT_RESOURCE_TYPES:
                continue
            rank = language_rank(resource.language, language_id)
            if rank is None:
                continue
            slot = (resource.type_id, resource.name)
            if slot not in chosen or rank < chosen[slot][0]:
                chosen[slot] = (rank, resource)
        codec = language_details(language_id)[1]
        texts = {}
        for _, resource in sorted(chosen.values(), key=lambda item: (item[1].type_id, str(item[1].name))):
            try:
                for key, text in resource_texts(resource, codec):
                    text = text.rstrip("\0")
                    if has_letters(text) and not any(character in text for character in GETTEXT_SEPARATORS):
                        texts[key] = text
            except (ValueError, IndexError) as error:
                raise ResourceError(f"{self.name}: {KIND_NAMES[resource.type_id]} {resource.name}: {error}") from error
        return texts


def language_rank(resource_language, wanted_language):
    if resource_language == wanted_language:
        return 0
    if resource_language & PRIMARY_LANGUAGE_MASK == wanted_language & PRIMARY_LANGUAGE_MASK:
        return 1
    if is_english(wanted_language) and is_neutral(resource_language):
        return 2
    return None


@dataclass
class Installer:
    path: Path
    product: str = None
    language: int = None
    modules: dict = field(default_factory=dict)
    skipped: list = field(default_factory=list)

    @property
    def is_english(self):
        return self.language is not None and is_english(self.language)


def msi_product(database):
    if "Property" not in database.columns:
        return None, None
    properties = {row["Property"]: row["Value"] for row in database.read_rows("Property")}
    name = properties.get("ProductName")
    if not name:
        return None, None
    version = ".".join((properties.get("ProductVersion") or "").split(".")[:2])
    slug = re.sub(r"[^a-z0-9.]+", "-", name.lower().replace("microsoft", "")).strip("-")
    product = f"{slug}-{version}" if version else slug
    language = properties.get("ProductLanguage")
    return product, int(language) if language and language.isdigit() else None


def installer_members(data):
    if is_msi(data):
        database = read_msi(data)
        product, language = msi_product(database)
        return product, language, list(database.members())
    members = list(archive_members(data))
    return detect_product(name for name, _ in members), None, members


def load_installer(path, progress=lambda message: None):
    installer = Installer(Path(path))
    progress(f"Reading {installer.path.name}")
    try:
        installer.product, msi_language, members = installer_members(installer.path.read_bytes())
    except MsiError as error:
        raise TranslationImportError(f"{installer.path}: {error}") from error
    for name, content in members:
        module_name = base_name(name)
        if module_name.lower() in installer.modules or not is_pe(content):
            continue
        try:
            resources = read_resources(content)
        except ResourceError as error:
            installer.skipped.append(f"{module_name}: {error}")
            continue
        if any(resource.type_id in TEXT_RESOURCE_TYPES for resource in resources):
            installer.modules[module_name.lower()] = Module(module_name, resources)
    installer.language = msi_language or dominant_language(installer.modules.values())
    return installer


def dominant_language(modules):
    counts = Counter()
    for module in modules:
        counts.update(module.languages())
    for language, _ in counts.most_common():
        if not is_neutral(language):
            return language
    return None


@dataclass
class Occurrence:
    product: str
    module: str
    key: tuple
    english: str
    localized: str


@dataclass
class ReferenceCoverage:
    product: str
    shared_modules: set = field(default_factory=set)
    modules: dict = field(default_factory=dict)

    def count(self, module, kind, measure):
        counts = self.modules.setdefault(module, {}).setdefault(kind, Counter())
        counts[measure] += 1

    def totals(self, shared_only=False):
        totals = {}
        for module, kinds in self.modules.items():
            if shared_only and module not in self.shared_modules:
                continue
            for kind, counts in kinds.items():
                totals.setdefault(kind, Counter()).update(counts)
        return totals


@dataclass
class LanguageCatalog:
    language_id: int
    occurrences: list = field(default_factory=list)
    anchored: dict = field(default_factory=dict)
    chosen: dict = field(default_factory=dict)
    derived: dict = field(default_factory=dict)
    conflicts: dict = field(default_factory=dict)
    coverage: list = field(default_factory=list)

    @property
    def code(self):
        return language_code(self.language_id)


def reference(occurrence):
    kind, resource, item = occurrence.key
    location = f"{kind}:{resource}:{item}" if resource else f"{kind}:{item}"
    return f"{occurrence.product}/{occurrence.module}:{location}"


def strip_accelerator(text):
    return ESCAPED_OR_PLAIN_ACCELERATOR.sub(r"\1", BRACKETED_ACCELERATOR.sub("", text))


def pair_installers(english, localized, catalog, progress):
    for module_key in sorted(set(english.modules) & set(localized.modules)):
        english_module = english.modules[module_key]
        english_texts = english_module.texts(english.language)
        localized_texts = localized.modules[module_key].texts(localized.language)
        paired = 0
        for key in sorted(set(english_texts) & set(localized_texts)):
            catalog.occurrences.append(Occurrence(english.product, english_module.name, key,
                                                  english_texts[key], localized_texts[key]))
            paired += 1
        if paired:
            progress(f"{catalog.code}: {english.product} {english_module.name}: {paired} texts")


def anchor_reference(reference_installer, catalog):
    by_position = {}
    for occurrence in catalog.occurrences:
        by_position.setdefault((occurrence.module.lower(), occurrence.key), []).append(occurrence)
    for module_key, module in reference_installer.modules.items():
        for key, text in module.texts(reference_installer.language).items():
            for occurrence in by_position.get((module_key, key), ()):
                if occurrence.english == text:
                    catalog.anchored.setdefault(text, Counter())[occurrence.localized] += 1


def choose_translations(catalog):
    votes = {}
    first_seen = {}
    for position, occurrence in enumerate(catalog.occurrences):
        votes.setdefault(occurrence.english, Counter())[occurrence.localized] += 1
        first_seen.setdefault((occurrence.english, occurrence.localized), position)
    for english, counter in votes.items():
        candidates = catalog.anchored.get(english) or counter
        ranked = sorted(candidates.items(),
                        key=lambda item: (item[0] == english, -item[1], first_seen[(english, item[0])]))
        catalog.chosen[english] = ranked[0][0]
        if len(counter) > 1:
            catalog.conflicts[english] = counter
    for english in sorted(catalog.chosen):
        plain = strip_accelerator(english)
        if plain != english and plain not in catalog.chosen and plain not in catalog.derived:
            catalog.derived[plain] = (english, strip_accelerator(catalog.chosen[english]))


def measure_reference(reference_installer, catalog, paired_modules):
    by_position = {(occurrence.module.lower(), occurrence.key): occurrence.english
                   for occurrence in catalog.occurrences}
    coverage = ReferenceCoverage(reference_installer.product)
    for module_key, module in reference_installer.modules.items():
        if module_key in paired_modules:
            coverage.shared_modules.add(module.name)
        for key, text in module.texts(reference_installer.language).items():
            coverage.count(module.name, key[0], "total")
            if text in catalog.chosen:
                coverage.count(module.name, key[0], "translated")
            if by_position.get((module_key, key)) == text:
                coverage.count(module.name, key[0], "same_position")
    catalog.coverage.append(coverage)


def catalog_entries(catalog, sources):
    occurrences_by_text = {}
    for occurrence in catalog.occurrences:
        occurrences_by_text.setdefault(occurrence.english, []).append(occurrence)
    _, _, plural_forms = language_details(catalog.language_id)
    extra = [("X-Generator", "classicsync import-translations"), ("X-Source-Installers", ", ".join(sources)),
             ("X-Windows-Language-Id", f"0x{catalog.language_id:04X}")]
    entries = [header_entry(header_fields(catalog.code, plural_forms, extra))]
    for english in sorted(catalog.chosen):
        occurrences = occurrences_by_text[english]
        entry = {"msgid": english, "msgstr": catalog.chosen[english],
                 "references": [reference(occurrence) for occurrence in occurrences[:MAXIMUM_REFERENCES]]}
        if english in catalog.conflicts:
            alternatives = [f"{text!r} x{count}" for text, count in catalog.conflicts[english].most_common()
                            if text != catalog.chosen[english]]
            entry["comments"] = ["also translated as " + ", ".join(alternatives)]
        entries.append(entry)
    for plain in sorted(catalog.derived):
        source, translation = catalog.derived[plain]
        entries.append({"msgid": plain, "msgstr": translation, "comments": [f"{source!r} without its accelerator"]})
    return entries


def locale_root():
    return data_directory() / "locale"


def write_catalog(catalog, destination, sources):
    directory = Path(destination) / catalog.code / "LC_MESSAGES"
    entries = catalog_entries(catalog, sources)
    po_path = directory / "classicsync.po"
    write_po(po_path, entries)
    mo_path = directory / "classicsync.mo"
    mo_path.write_bytes(compile_entries(entries))
    return mo_path


@dataclass
class TranslationSummary:
    catalogs: list = field(default_factory=list)
    written: dict = field(default_factory=dict)
    references: list = field(default_factory=list)
    unpaired: list = field(default_factory=list)
    unrecognised: list = field(default_factory=list)


def installer_paths(paths):
    expanded = []
    for path in map(Path, paths):
        if path.is_dir():
            expanded.extend(sorted(child for child in path.iterdir()
                                   if child.is_file() and child.suffix.lower() in INSTALLER_SUFFIXES))
        else:
            expanded.append(path)
    return expanded


def import_translations(paths, destination=None, progress=None):
    progress = progress or (lambda message: None)
    destination = Path(destination) if destination else locale_root()
    summary = TranslationSummary()
    installers = []
    for path in installer_paths(paths):
        installer = load_installer(path, progress)
        if installer.product is None or installer.language is None:
            summary.unrecognised.append(installer.path)
            continue
        progress(f"{installer.path.name}: {installer.product}, {language_code(installer.language)}, "
                 f"{len(installer.modules)} modules with text")
        installers.append(installer)
    english_by_product = {}
    for installer in installers:
        if installer.is_english:
            english_by_product.setdefault(installer.product, installer)
    catalogs = {}
    sources = {}
    paired_products = set()
    for installer in installers:
        if installer.is_english:
            continue
        english = english_by_product.get(installer.product)
        if english is None:
            summary.unpaired.append(installer.path)
            continue
        catalog = catalogs.setdefault(installer.language, LanguageCatalog(installer.language))
        pair_installers(english, installer, catalog, progress)
        sources.setdefault(installer.language, []).extend([english.path.name, installer.path.name])
        paired_products.add(installer.product)
    summary.references = [installer for product, installer in english_by_product.items()
                          if product not in paired_products]
    for language, catalog in sorted(catalogs.items()):
        paired_modules = {occurrence.module.lower() for occurrence in catalog.occurrences}
        for reference_installer in summary.references:
            anchor_reference(reference_installer, catalog)
        choose_translations(catalog)
        for reference_installer in summary.references:
            measure_reference(reference_installer, catalog, paired_modules)
        summary.written[catalog.code] = write_catalog(catalog, destination, sorted(set(sources[language])))
        summary.catalogs.append(catalog)
    return summary
