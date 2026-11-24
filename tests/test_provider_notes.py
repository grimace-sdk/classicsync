import asyncio
import os
from pathlib import Path

import pytest
from fake_device import FakeRapiClient

from classicsync.convert.errors import Report
from classicsync.convert.rtf_reader import read_rtf
from classicsync.convert.rtf_writer import write_pocket_word
from classicsync.sync import Partnership, SyncOptions, synchronize
from classicsync.sync.folder import FolderProvider
from classicsync.sync.providers.notes.markdown import document_from_markdown, markdown_from_document
from classicsync.sync.providers.notes.provider import NotesProvider
from classicsync.sync.providers.notes.pwi import is_pwi, pwi_paragraphs, pwi_text

SAMPLES = Path(os.environ.get("CLASSICSYNC_PWI_SAMPLES", Path(__file__).resolve().parents[2] / "sh3" / "emu" / "rom" / "nk-a51-ce1.01" / "files"))
PROVIDERS = {"folder": FolderProvider, "notes": NotesProvider}


def paragraph_record(identifier, stream):
    header = (b"A\x00" + identifier.to_bytes(2, "little") + b"\x09\x00\x01\x00" + len(stream).to_bytes(2, "little")
              + b"\x01\x00\xff\xff" + (identifier + 1).to_bytes(2, "little") + bytes(10) + b"\x02\x00\x00\x00")
    return header + stream + bytes(4)


def synthetic_ink_note():
    first = b"\xe5\x01\x00\xe6\x0a\x00Shopping\xc4\x00"
    second = b"\xe5\x01\x00\xc0\x1c\xff\x88\xc2\x86\xc1 tea\xc4\x00"
    ink = b"B\x00\x30\x00\x03\x00\x01\x00" + bytes(range(200, 256)) * 4
    return b"{\\pwi\x15\x00\x00\x01\x01" + bytes(40) + paragraph_record(0x26, first) + ink + paragraph_record(0x28, second)


def test_pwi_text_is_decoded():
    data = synthetic_ink_note()
    assert is_pwi(data)
    assert pwi_paragraphs(data) == ["Shopping", "＜よう tea"]


@pytest.mark.skipif(not (SAMPLES / "memo.pwi").exists(), reason="Pocket Word 1.0 .pwi samples not found (set CLASSICSYNC_PWI_SAMPLES)")
def test_pwi_samples_decode():
    assert pwi_paragraphs((SAMPLES / "memo.pwi").read_bytes())[0] == "社内連絡メモ"
    assert "Microsoft(R) Pocket Word(R)" in pwi_text((SAMPLES / "welcome.pwi").read_bytes())


@pytest.mark.parametrize("markdown", [
    "# Shopping\n- **milk** and *eggs*\n1. first\n2. second\n\nplain 3 \\* 4 snake\\_case\n",
    "\\- not a list\n***both*** and 2. too\n",
])
def test_markdown_round_trips_through_pocket_word(markdown):
    assert markdown_from_document(document_from_markdown(markdown)) == markdown
    pocket_word = write_pocket_word(document_from_markdown(markdown), Report(), 2)
    assert markdown_from_document(read_rtf(pocket_word, Report())) == markdown


def sync(client, partnership, root):
    options = SyncOptions(object_types=["notes"], type_providers={"notes": "notes"},
                          provider_settings={"notes_folder": str(root)})
    report = asyncio.run(synchronize(client, partnership, options, providers=PROVIDERS))
    assert not [action for action in report.actions if action.error], report.actions
    assert not report.errors
    return report


def test_notes_sync_both_ways(tmp_path):
    client = FakeRapiClient()
    root = tmp_path / "Markdown"
    partnership = Partnership.for_device("HPC", tmp_path / "partnerships")
    pocket_word = write_pocket_word(document_from_markdown("Call **Ada**\n"), Report(), 2)
    client.put_file("\\My Documents\\Call.pwd", pocket_word)
    client.put_file("\\My Documents\\Ink.pwi", synthetic_ink_note())
    client.put_file("\\My Documents\\Picture.bmp", b"BM not a note")

    sync(client, partnership, root)
    assert (root / "My Documents" / "Call.md").read_text() == "Call **Ada**\n"
    assert (root / "My Documents" / "Ink.md").read_text() == "Shopping\n＜よう tea\n"
    assert not list(root.rglob("Picture*"))

    (root / "My Documents" / "Call.md").write_text("Call **Ada** and *Grace*\n")
    (root / "Todo.md").write_text("# Todo\n- write tests\n")
    report = sync(client, partnership, root)
    assert report.counts() == {"update to device": 1, "add to device": 1}
    assert markdown_from_document(read_rtf(client.file("\\My Documents\\Call.pwd"), Report())) == "Call **Ada** and *Grace*\n"
    assert markdown_from_document(read_rtf(client.file("\\My Documents\\Todo.pwd"), Report())) == "# Todo\n- write tests\n"
    assert sync(client, partnership, root).counts() == {}


def test_edited_ink_note_is_kept_as_a_new_note(tmp_path):
    client = FakeRapiClient()
    root = tmp_path / "Markdown"
    partnership = Partnership.for_device("HPC", tmp_path / "partnerships")
    ink = synthetic_ink_note()
    client.put_file("\\My Documents\\Ink.pwi", ink)
    sync(client, partnership, root)

    (root / "My Documents" / "Ink.md").write_text("Shopping\nmore tea\n")
    report = sync(client, partnership, root)
    assert report.counts() == {"add to device": 1}
    assert client.file("\\My Documents\\Ink.pwi") == ink
    assert (root / "My Documents" / "Ink.md").read_text() == "Shopping\n＜よう tea\n"
    edited = client.file("\\My Documents\\Ink (edited).pwd")
    assert markdown_from_document(read_rtf(edited, Report())) == "Shopping\nmore tea\n"


def test_device_delete_moves_markdown_to_trash(tmp_path):
    client = FakeRapiClient()
    root = tmp_path / "Markdown"
    partnership = Partnership.for_device("HPC", tmp_path / "partnerships")
    client.put_file("\\My Documents\\Call.pwd", write_pocket_word(document_from_markdown("Call\n"), Report(), 2))
    sync(client, partnership, root)
    del client.files["\\my documents\\call.pwd"]
    assert sync(client, partnership, root).counts() == {"delete to desktop": 1}
    assert not (root / "My Documents" / "Call.md").exists()
    assert list((root / ".trash").rglob("Call.md"))
