import os
import time

from classicsync.convert import convert
from classicsync.sync.converted import ConvertedMirror
from classicsync.sync.folder import FileStore, Trash
from classicsync.sync.objects import DeviceFile

RTF_LETTER = rb"{\rtf1\ansi{\fonttbl{\f0 Tahoma;}}\f0\fs20 Dear Velo,\par {\b bold} words\par}"


def pocket_word_bytes():
    return convert(RTF_LETTER, "rtf", "pwd", version=2).data


def make_store(root, messages):
    mirror = ConvertedMirror(root, ["My Documents"], 2, messages.append)
    return FileStore(root, ["\\My Documents"], 1, "Handheld_PC", Trash(root), mirror)


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
