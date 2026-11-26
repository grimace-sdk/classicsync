import struct

from classicsync.formats.pdb import read_pdb, write_pdb
from classicsync.formats.plucker import (
    COMPRESSION_DOC, FONT_BOLD, LINK_END, MAX_RECORD_TEXT, NEW_LINE, PAGE_LINK, SET_FONT, Page, build_document, function, html_page,
    plain_text, read_document, text_page,
)
from classicsync.palm.plucker import build_plucker


def test_html_becomes_plucker_markup():
    page, title = html_page("<html><head><title>Hi</title><script>x()</script></head><body><h1>Big</h1>"
                            "<p>Some <b>bold</b> and <i>slanted</i><br>text</p><ul><li>one</li></ul></body></html>", 2)
    assert title == "Hi"
    assert page.paragraphs[0] == function(SET_FONT, 1) + b"Big" + function(SET_FONT, 0)
    assert page.paragraphs[1] == (b"Some " + function(SET_FONT, FONT_BOLD) + b"bold" + function(SET_FONT, 0) + b" and "
                                  + function(0x40) + b"slanted" + function(0x48) + function(NEW_LINE) + b"text")
    assert plain_text(page.paragraphs[2]) == "• one"


def test_document_round_trips_with_links_and_compression(tmp_path):
    (tmp_path / "index.html").write_text('<p>See <a href="more.html">more</a>.</p>')
    (tmp_path / "more.html").write_text("<title>More</title><p>The rest.</p>")
    (tmp_path / "notes.txt").write_text("Line one\nline two\n\nNew paragraph")
    document, skipped = build_plucker([str(tmp_path / "index.html"), str(tmp_path / "more.html"), str(tmp_path / "notes.txt")],
                                      title="Test")
    assert not skipped and (document.name, document.type, document.creator) == ("Test", "Data", "Plkr")
    home, pages = read_document(read_pdb(write_pdb(document)))
    assert home == 2 and sorted(pages) == [2, 3, 4]
    link = pages[2].paragraphs[1]
    assert function(PAGE_LINK, 0, 3) + b"more" + function(LINK_END) in link
    assert [plain_text(paragraph) for paragraph in pages[4].paragraphs] == ["Line one\nline two", "New paragraph"]
    index = document.records[0].data
    assert struct.unpack(">HHHHH", index) == (1, 2, 1, 0, 2)


def test_long_pages_split_into_linked_records():
    paragraph = b"x" * 1000
    pages = [Page(2, [paragraph] * (MAX_RECORD_TEXT // 1000 + 5))]
    document = build_document("Long", pages, COMPRESSION_DOC)
    home, parsed = read_document(document)
    assert sorted(parsed) == [2, 3]
    assert parsed[2].paragraphs[-1] == function(PAGE_LINK, 0, 3) + b"Next part" + function(LINK_END)
    assert all(record.data[6] == 0 for record in document.records[1:])


def test_text_page_keeps_lines():
    assert text_page("a\nb\n\nc", 2).paragraphs == [b"a" + function(NEW_LINE) + b"b", b"c"]
