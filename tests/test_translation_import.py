import gettext
import os
from pathlib import Path

import pytest

from cab_builders import build_cab
from resource_builders import build_msi, build_pe, dialog, menu, menu_ex, message_table, string_block

from classicsync import i18n
from classicsync.cli import main
from classicsync.formats.msi import decode_stream_name, encode_stream_name, read_msi
from classicsync.formats.win32_resources import (
    Resource, parse_dialog, parse_menu, parse_message_table, parse_string_block, read_resources,
)
from classicsync.translation_import import (
    Installer, LanguageCatalog, Module, anchor_reference, choose_translations, import_translations, measure_reference,
    pair_installers, strip_accelerator, write_catalog,
)

INSTALLERS = Path(os.environ.get("CLASSICSYNC_INSTALLERS",
                                 Path(__file__).resolve().parents[1].parent / "classicsync-installers"))
ENGLISH_45 = INSTALLERS / "setup-async-4.5.msi"
GERMAN_45 = INSTALLERS / "async-4.5" / "setup-DE-DE.msi"
ENGLISH_31 = INSTALLERS / "msasync.exe"

ENGLISH = 0x0409
GERMAN = 0x0407

needs_installers = pytest.mark.skipif(not all(path.exists() for path in (ENGLISH_45, GERMAN_45, ENGLISH_31)),
                                      reason="original ActiveSync installers not found (set CLASSICSYNC_INSTALLERS)")


def test_stream_names_round_trip():
    for name, is_table in (("_StringPool", True), ("File", True), ("ActiveSync.cab", False), ("a-b", False)):
        encoded = encode_stream_name(name, is_table)
        assert decode_stream_name(encoded) == ("!" + name if is_table else name)
    assert encode_stream_name("_StringData", is_table=True) == "\u4840\u3f3f\u4577\u446c\u3b6a\u45e4\u4824"


def test_msi_tables_and_embedded_cabinet():
    long_text = "x" * 70000
    cabinet = build_cab([("main_exe", b"MZ main"), ("readme_txt", b"hello")], compression=1)
    data = build_msi([("main_exe", "MAIN~1.EXE|Main Program.exe", b"MZ main"), ("readme_txt", "readme.txt", b"hello")],
                     "Microsoft Example", "4.5.1.0", 1031, cabinet, long_text=long_text)
    database = read_msi(data)
    assert set(database.table_names) >= {"File", "Media", "Directory", "Component", "Property"}
    properties = {row["Property"]: row["Value"] for row in database.read_rows("Property")}
    assert properties["LongText"] == long_text
    assert properties["ProductLanguage"] == "1031"
    files = {file.key: file for file in database.files()}
    assert files["main_exe"].name == "Main Program.exe"
    assert files["main_exe"].directory == "ProgramFilesFolder/Example Product"
    assert files["readme_txt"].sequence == 2
    assert dict(database.members()) == {"ProgramFilesFolder/Example Product/Main Program.exe": b"MZ main",
                                        "ProgramFilesFolder/Example Product/readme.txt": b"hello"}


def test_string_dialog_menu_and_message_resources():
    strings = parse_string_block(2, string_block({0: "Connected", 3: "Not connected"}))
    assert strings == {16: "Connected", 19: "Not connected"}
    for extended in (False, True):
        parsed = parse_dialog(dialog("Options", [(1001, "&Sync"), (-1, "Label")], extended))
        assert parsed.caption == "Options" and parsed.font == "MS Shell Dlg"
        assert [(control.control_id & 0xFFFF, control.text) for control in parsed.controls] == [(1001, "&Sync"),
                                                                                                (0xFFFF, "Label")]
    tree = [("&File", [("&Open", 100), ("", 0), ("E&xit", 101)]), ("&Tools", [("&Options...", 200)])]
    for builder in (menu, menu_ex):
        items = parse_menu(builder(tree))
        assert [(item.path, item.item_id, item.text, item.is_popup) for item in items] == [
            ((0,), 0, "&File", True), ((0, 0), 100, "&Open", False), ((0, 1), 0, "", False),
            ((0, 2), 101, "E&xit", False), ((1,), 0, "&Tools", True), ((1, 0), 200, "&Options...", False)]
    assert parse_message_table(message_table({7: "Copying %1\r\n", 8: "Done\r\n"})) == {7: "Copying %1\r\n",
                                                                                     8: "Done\r\n"}


def test_pe_resource_directory():
    pe = build_pe([(6, 1, ENGLISH, string_block({1: "Sync"})), (6, 1, GERMAN, string_block({1: "Synchronisieren"})),
                   (4, 100, ENGLISH, menu([("&Tools", [("&Options...", 200)])]))])
    resources = read_resources(pe)
    assert sorted((resource.type_id, resource.name, resource.language) for resource in resources) == [
        (4, 100, ENGLISH), (6, 1, GERMAN), (6, 1, ENGLISH)]


def module(name, language, strings=None, menus=None, dialogs=None):
    resources = []
    if strings:
        resources.append(Resource(6, 1, language, string_block(strings)))
    for menu_id, tree in (menus or {}).items():
        resources.append(Resource(4, menu_id, language, menu(tree)))
    for dialog_id, (caption, controls) in (dialogs or {}).items():
        resources.append(Resource(5, dialog_id, language, dialog(caption, controls, extended=True)))
    return Module(name, resources)


def installer(product, language, modules):
    return Installer(Path(f"{product}-{language:x}"), product, language,
                     {module.name.lower(): module for module in modules})


def test_pairing_prefers_the_translation_used_at_the_reference_position():
    english = installer("product-4.5", ENGLISH, [
        module("Main.exe", ENGLISH, {1: "Sync", 2: "Remove", 3: "Connected", 4: "General"},
               {100: [("&Tools", [("&Options...", 200)])]},
               {10: ("Settings", [(5, "&Remove"), (-1, "General")])}),
        module("Other.dll", ENGLISH, {1: "Remove", 2: "General"}),
    ])
    german = installer("product-4.5", GERMAN, [
        module("Main.exe", GERMAN, {1: "Synchronisieren", 2: "Entfernen", 3: "Verbunden", 4: "Allgemein"},
               {100: [("E&xtras", [("&Optionen...", 200)])]},
               {10: ("Einstellungen", [(5, "Ent&fernen"), (-1, "General")])}),
        module("Other.dll", GERMAN, {1: "Loeschen", 2: "General"}),
    ])
    reference = installer("product-3.1", ENGLISH, [
        module("MAIN.EXE", ENGLISH, {1: "Sync", 2: "Remove", 5: "Old only"}, {100: [("&Tools", [("&Options...", 200)])]}),
    ])
    catalog = LanguageCatalog(GERMAN)
    pair_installers(english, german, catalog, lambda message: None)
    anchor_reference(reference, catalog)
    choose_translations(catalog)
    measure_reference(reference, catalog, {"main.exe", "other.dll"})
    assert catalog.chosen["&Options..."] == "&Optionen..."
    assert catalog.chosen["&Tools"] == "E&xtras"
    assert catalog.chosen["Settings"] == "Einstellungen"
    assert catalog.chosen["&Remove"] == "Ent&fernen"
    assert catalog.chosen["Remove"] == "Entfernen"
    assert dict(catalog.conflicts["Remove"]) == {"Entfernen": 1, "Loeschen": 1}
    assert catalog.chosen["General"] == "Allgemein"
    assert catalog.derived["Options..."] == ("&Options...", "Optionen...")
    totals = catalog.coverage[0].totals()
    assert dict(totals["string"]) == {"total": 3, "translated": 2, "same_position": 2}
    assert dict(totals["menu"]) == {"total": 2, "translated": 2, "same_position": 2}


def test_accelerators_are_stripped_in_both_styles():
    assert strip_accelerator("&Options...") == "Options..."
    assert strip_accelerator("\u30aa\u30d7\u30b7\u30e7\u30f3(&O)...") == "\u30aa\u30d7\u30b7\u30e7\u30f3..."
    assert strip_accelerator("Save && E&xit") == "Save & Exit"


def test_written_catalog_loads_through_i18n(tmp_path, monkeypatch):
    monkeypatch.setenv("CLASSICSYNC_HOME", str(tmp_path))
    catalog = LanguageCatalog(GERMAN)
    pair_installers(installer("p", ENGLISH, [module("A.exe", ENGLISH, {1: "Connected", 2: "Line\r\nbreak"})]),
                    installer("p", GERMAN, [module("A.exe", GERMAN, {1: "Verbunden", 2: "Zeilen\r\numbruch"})]),
                    catalog, lambda message: None)
    choose_translations(catalog)
    write_catalog(catalog, tmp_path / "locale", ["a", "b"])
    assert "de" in i18n.available_languages()
    try:
        i18n.set_language("de")
        assert i18n._("Connected") == "Verbunden"
        assert i18n._("Line\r\nbreak") == "Zeilen\r\numbruch"
    finally:
        i18n.set_language()


@pytest.mark.parametrize("text, values, expected", [
    ("%1!d! items not synchronized", (3,), "3 items not synchronized"),
    ("Copy %2 to %1.%n", ("B", "A"), "Copy A to B.\n"),
    ("%1!04X! and 100%%", (255,), "00FF and 100%"),
    ("%d of %s (%lu%%)", (2, "five", 40), "2 of five (40%)"),
    ("%-4s|%5.1f|%c", ("ab", 2.25, 65), "ab  |  2.2|A"),
])
def test_format_original(text, values, expected):
    assert i18n.format_original(text, *values) == expected


@pytest.fixture(scope="module")
def german_import(tmp_path_factory):
    destination = tmp_path_factory.mktemp("home") / "locale"
    summary = import_translations([ENGLISH_45, GERMAN_45, ENGLISH_31], destination)
    return destination, summary


@needs_installers
def test_german_import_known_pairs(german_import):
    destination, summary = german_import
    assert [catalog.code for catalog in summary.catalogs] == ["de"]
    with open(destination / "de" / "LC_MESSAGES" / "classicsync.mo", "rb") as handle:
        translations = gettext.GNUTranslations(handle)
    expected = {
        "&Synchronize": "&Synchronisieren",
        "Sync": "Synchronisieren",
        "Connected": "Verbunden",
        "Not connected": "Nicht verbunden",
        "&Options...": "&Optionen...",
        "&Tools": "&Extras",
        "Options...": "Optionen...",
        "Synchronize": "Synchronisieren",
    }
    assert {english: translations.gettext(english) for english in expected} == expected
    assert (destination / "de" / "LC_MESSAGES" / "classicsync.po").exists()


@needs_installers
def test_german_import_covers_most_of_activesync_31(german_import):
    _, summary = german_import
    coverage = summary.catalogs[0].coverage[0]
    assert coverage.product == "activesync-3.1"
    frontend_modules = {"wcesmgr.exe", "wcescomm.exe", "wcesview.dll", "ceappmgr.exe", "pegconv.dll", "outstore.dll",
                        "cefstore.dll"}
    strings = {"total": 0, "translated": 0, "same_position": 0}
    for module_name, kinds in coverage.modules.items():
        if module_name.lower() in frontend_modules:
            for measure in strings:
                strings[measure] += kinds.get("string", {}).get(measure, 0)
    assert strings["total"] > 900
    assert strings["same_position"] / strings["total"] > 0.85
    assert strings["translated"] >= strings["same_position"]
    menus = coverage.totals(shared_only=True)["menu"]
    assert menus["translated"] / menus["total"] > 0.85


@needs_installers
def test_command_installs_catalog_for_set_language(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLASSICSYNC_HOME", str(tmp_path))
    assert main(["import-translations", str(ENGLISH_45), str(GERMAN_45), str(ENGLISH_31)]) == 0
    assert "de: " in capsys.readouterr().out
    assert (tmp_path / "locale" / "de" / "LC_MESSAGES" / "classicsync.mo").exists()
    try:
        i18n.set_language("de")
        assert i18n._("Not connected") == "Nicht verbunden"
        assert "de" in i18n.available_languages()
    finally:
        i18n.set_language()
