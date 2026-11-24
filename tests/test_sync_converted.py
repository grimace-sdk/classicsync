import os
import time

import pytest

from classicsync.convert import convert
from classicsync.sync.converted import ConvertedMirror
from classicsync.sync.folder import FileStore, Trash
from classicsync.sync.objects import DeviceFile

RTF_LETTER = rb"{\rtf1\ansi{\fonttbl{\f0 Tahoma;}}\f0\fs20 Dear Velo,\par {\b bold} words\par}"


def pocket_word_bytes():
    return convert(RTF_LETTER, "rtf", "pwd", version=2).data


WORD_AND_EXCEL = {"document": "docx", "spreadsheet": "xlsx", "image": "png"}


def make_store(root, messages, formats=None):
    trash = Trash(root)
    mirror = ConvertedMirror(root, ["My Documents"], 2, messages.append, formats or WORD_AND_EXCEL, trash)
    return FileStore(root, ["\\My Documents"], 1, "Handheld_PC", trash, mirror)


def test_device_document_gets_converted_copy(tmp_path):
    messages = []
    store = make_store(tmp_path, messages)
    store.write_item(None, "My Documents/Letter.pwd", DeviceFile("My Documents/Letter.pwd", pocket_word_bytes()))
    converted = tmp_path / "Converted" / "My Documents" / "Letter.docx"
    assert converted.exists()
    assert b"word/document.xml" in converted.read_bytes()
    assert "Converted/My Documents/Letter.docx" not in "".join(store.list_items())


def test_edited_converted_copy_is_written_back_to_raw(tmp_path):
    store = make_store(tmp_path, [])
    store.write_item(None, "My Documents/Letter.pwd", DeviceFile("My Documents/Letter.pwd", pocket_word_bytes()))
    raw = tmp_path / "My Documents" / "Letter.pwd"
    before = raw.read_bytes()
    converted = tmp_path / "Converted" / "My Documents" / "Letter.docx"
    edited = convert(rb"{\rtf1\ansi Changed on the desktop\par}", "rtf", "docx").data
    time.sleep(0.01)
    converted.write_bytes(edited)
    os.utime(converted, None)
    items = store.list_items()
    assert "My Documents/Letter.pwd" in items
    after = raw.read_bytes()
    assert after != before and after.startswith(b"{\\pwd2")
    assert b"Changed on the desktop" in after


def test_untouched_converted_copy_never_rewrites_raw(tmp_path):
    store = make_store(tmp_path, [])
    store.write_item(None, "My Documents/Letter.pwd", DeviceFile("My Documents/Letter.pwd", pocket_word_bytes()))
    raw = tmp_path / "My Documents" / "Letter.pwd"
    before = raw.read_bytes()
    store.list_items()
    store.list_items()
    assert raw.read_bytes() == before


def test_new_desktop_document_becomes_device_file(tmp_path):
    store = make_store(tmp_path, [])
    new_copy = tmp_path / "Converted" / "My Documents" / "Budget.xlsx"
    new_copy.parent.mkdir(parents=True)
    new_copy.write_bytes(convert(b"Item,Cost\nTea,3\nCake,4\n", "csv", "xlsx").data)
    items = store.list_items()
    assert "My Documents/Budget.pxl" in items
    assert (tmp_path / "My Documents" / "Budget.pxl").exists()


def test_deleting_raw_moves_converted_copy_to_trash(tmp_path):
    store = make_store(tmp_path, [])
    store.write_item(None, "My Documents/Letter.pwd", DeviceFile("My Documents/Letter.pwd", pocket_word_bytes()))
    store.delete_item("My Documents/Letter.pwd", "My Documents/Letter.pwd")
    assert not (tmp_path / "Converted" / "My Documents" / "Letter.docx").exists()
    assert list((tmp_path / ".trash").rglob("Letter.docx"))


def pocket_excel_bytes():
    from classicsync.convert.errors import Report
    from classicsync.convert.pocket_excel import write_pocket_excel
    from classicsync.convert.workbook import Cell, Sheet, Workbook
    first = Sheet("Costs", cells={(0, 0): Cell("Tea"), (0, 1): Cell(3.0), (1, 1): Cell(6.0, formula="B1*2")})
    second = Sheet("Notes", cells={(0, 0): Cell("kept")})
    return write_pocket_excel(Workbook([first, second]), Report(), 2)


def touch_later(path, data):
    time.sleep(0.01)
    path.write_bytes(data)
    os.utime(path, None)


def test_format_change_regenerates_copies_without_touching_raw(tmp_path):
    store = make_store(tmp_path, [])
    store.write_item(None, "My Documents/Letter.pwd", DeviceFile("My Documents/Letter.pwd", pocket_word_bytes()))
    raw = tmp_path / "My Documents" / "Letter.pwd"
    before = raw.read_bytes()
    store = make_store(tmp_path, [], {"document": "odt", "spreadsheet": "xlsx", "image": "png"})
    store.list_items()
    converted = tmp_path / "Converted" / "My Documents"
    assert (converted / "Letter.odt").exists() and not (converted / "Letter.docx").exists()
    assert list((tmp_path / ".trash").rglob("Letter.docx"))
    assert raw.read_bytes() == before
    store.list_items()
    assert raw.read_bytes() == before


@pytest.mark.parametrize("desktop_format", ["rtf", "odt", "html", "txt"])
def test_edits_flow_back_from_any_document_format(tmp_path, desktop_format):
    store = make_store(tmp_path, [], {"document": desktop_format})
    store.write_item(None, "My Documents/Letter.pwd", DeviceFile("My Documents/Letter.pwd", pocket_word_bytes()))
    copy = tmp_path / "Converted" / "My Documents" / f"Letter.{desktop_format}"
    assert copy.exists()
    touch_later(copy, convert(rb"{\rtf1\ansi Edited elsewhere\par}", "rtf", desktop_format).data)
    store.list_items()
    assert b"Edited elsewhere" in (tmp_path / "My Documents" / "Letter.pwd").read_bytes()


def test_new_opendocument_files_become_device_files(tmp_path):
    store = make_store(tmp_path, [], {"document": "rtf", "spreadsheet": "csv"})
    folder = tmp_path / "Converted" / "My Documents"
    folder.mkdir(parents=True)
    (folder / "Memo.odt").write_bytes(convert(rb"{\rtf1\ansi Memo text\par}", "rtf", "odt").data)
    (folder / "Sums.ods").write_bytes(convert(b"a,1\nb,2\n", "csv", "ods").data)
    items = store.list_items()
    assert {"My Documents/Memo.pwd", "My Documents/Sums.pxl"} <= set(items)
    assert b"Memo text" in (tmp_path / "My Documents" / "Memo.pwd").read_bytes()
    store.list_items()
    assert (folder / "Memo.odt").exists() and not (folder / "Memo.rtf").exists()


def test_csv_edit_keeps_other_sheets_and_unchanged_formulas(tmp_path):
    from classicsync.convert.errors import Report
    from classicsync.convert.pocket_excel import read_pocket_excel
    store = make_store(tmp_path, [], {"spreadsheet": "csv"})
    store.write_item(None, "My Documents/Costs.pxl", DeviceFile("My Documents/Costs.pxl", pocket_excel_bytes()))
    copy = tmp_path / "Converted" / "My Documents" / "Costs.csv"
    assert copy.read_bytes().splitlines() == [b"Tea,3", b",6"]
    touch_later(copy, b"Coffee,3\r\n,6\r\n")
    store.list_items()
    workbook = read_pocket_excel((tmp_path / "My Documents" / "Costs.pxl").read_bytes(), Report())
    assert [sheet.name for sheet in workbook.sheets] == ["Costs", "Notes"]
    assert workbook.sheets[0].cells[(0, 0)].value == "Coffee"
    assert workbook.sheets[0].cells[(1, 1)].formula == "B1*2"
    assert workbook.sheets[1].cells[(0, 0)].value == "kept"


def test_platform_defaults(tmp_path):
    from classicsync.sync.converted import default_formats
    assert default_formats("win32") == {"document": "docx", "spreadsheet": "xlsx", "image": "png"}
    assert default_formats("linux") == {"document": "docx", "spreadsheet": "xlsx", "image": "png"}
    assert default_formats("darwin", tmp_path) == {"document": "rtf", "spreadsheet": "csv", "image": "png"}
    (tmp_path / "Numbers.app").mkdir()
    assert default_formats("darwin", tmp_path)["spreadsheet"] == "xlsx"


def test_folder_provider_passes_formats(tmp_path):
    from classicsync.sync.folder import FolderProvider
    from classicsync.sync.objects import FILES, DeviceInfo
    from classicsync.sync.provider import ProviderContext
    from classicsync.sync.settings_schema import provider_schema
    keys = {setting.key: setting for setting in provider_schema(FolderProvider)}
    assert keys["converted_documents"].choice_values() == ["rtf", "docx", "odt", "html", "txt"]
    assert keys["converted_spreadsheets"].choice_values() == ["xlsx", "ods", "csv"]
    context = ProviderContext(DeviceInfo("Velo", 2, 0), tmp_path, {"folder": str(tmp_path / "data"), "converted_documents": "html"})
    store = FolderProvider(context).open_store(FILES)
    store.write_item(None, "My Documents/Letter.pwd", DeviceFile("My Documents/Letter.pwd", pocket_word_bytes()))
    assert (tmp_path / "data" / "Converted" / "My Documents" / "Letter.html").exists()
