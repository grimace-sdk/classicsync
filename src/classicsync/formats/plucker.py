import re
import struct
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser

from .pdb import PalmDatabase, PdbRecord

TYPE = "Data"
CREATOR = "Plkr"
ATTRIBUTE_BACKUP = 0x0008
INDEX_UID = 1
COMPRESSION_DOC = 1
COMPRESSION_ZLIB = 2
RESERVED_HOME = 0

DATATYPE_PHTML = 0
DATATYPE_PHTML_COMPRESSED = 1

RECORD_HEADER = struct.Struct(">HHHBB")
PARAGRAPH_HEADER = struct.Struct(">HH")
MAX_RECORD_TEXT = 30000
MAX_PARAGRAPH = 4000
NAME_LIMIT = 31
ENCODING = "cp1252"

FUNCTION = b"\x00"
PAGE_LINK = 0x0A
LINK_END = 0x08
SET_FONT = 0x11
SET_ALIGNMENT = 0x29
HORIZONTAL_RULE = 0x33
NEW_LINE = 0x38
ITALIC_BEGIN, ITALIC_END = 0x40, 0x48
UNDERLINE_BEGIN, UNDERLINE_END = 0x60, 0x68
STRIKE_BEGIN, STRIKE_END = 0x70, 0x78

FONT_REGULAR = 0
FONT_BOLD = 7
FONT_FIXED = 8
HEADING_FONTS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
ALIGN_LEFT, ALIGN_RIGHT, ALIGN_CENTER = 0, 1, 2
RULE_HEIGHT = 2
RULE_WIDTH_PERCENT = 100
PARAGRAPH_SPACING = 1
BULLET = "• "

BLOCK_TAGS = {"p", "div", "section", "article", "header", "footer", "main", "aside", "blockquote", "li", "dt", "dd", "tr",
              "table", "ul", "ol", "dl", "figure", "figcaption", "pre", "address", "h1", "h2", "h3", "h4", "h5", "h6"}
SKIPPED_TAGS = {"script", "style", "head", "noscript", "template", "svg", "nav", "form", "button", "select", "iframe"}
WHITESPACE = re.compile(r"\s+")


def function(code, *data):
    return FUNCTION + bytes([code, *data])


def encode(text):
    return text.encode(ENCODING, errors="replace")


@dataclass
class Page:
    uid: int
    paragraphs: list = field(default_factory=list)


class PageBuilder:
    def __init__(self, uid):
        self.page = Page(uid)
        self.current = bytearray()
        self.pending_space = False

    def text(self, text):
        if not text:
            return
        if self.pending_space and self.current and not text.startswith(" "):
            self.current += b" "
        self.pending_space = False
        self.current += encode(text)
        if len(self.current) > MAX_PARAGRAPH:
            self.end_paragraph()

    def code(self, code, *data):
        if self.pending_space and self.current and not self.current.endswith(b" "):
            self.current += b" "
        self.pending_space = False
        self.current += function(code, *data)

    def new_line(self):
        self.pending_space = False
        self.code(NEW_LINE)

    def end_paragraph(self):
        if self.current.strip(b" "):
            self.page.paragraphs.append(bytes(self.current))
        self.current = bytearray()
        self.pending_space = False

    def finish(self):
        self.end_paragraph()
        return self.page


class MarkupConverter(HTMLParser):
    def __init__(self, builder, link_uid):
        super().__init__(convert_charrefs=True)
        self.builder = builder
        self.link_uid = link_uid
        self.skipping = 0
        self.preformatted = 0
        self.fonts = [FONT_REGULAR]
        self.title = ""
        self.in_title = False
        self.open_link = False

    def set_font(self, font):
        self.fonts.append(font)
        self.builder.code(SET_FONT, font)

    def restore_font(self):
        if len(self.fonts) > 1:
            self.fonts.pop()
        self.builder.code(SET_FONT, self.fonts[-1])

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == "title":
            self.in_title = True
        if tag in SKIPPED_TAGS:
            self.skipping += 1
            return
        if self.skipping:
            return
        if tag in BLOCK_TAGS:
            self.builder.end_paragraph()
        if tag in HEADING_FONTS:
            self.set_font(HEADING_FONTS[tag])
        elif tag in ("b", "strong", "th"):
            self.set_font(FONT_BOLD)
        elif tag in ("tt", "code", "kbd", "samp"):
            self.set_font(FONT_FIXED)
        elif tag == "pre":
            self.preformatted += 1
            self.set_font(FONT_FIXED)
        elif tag in ("i", "em", "cite", "var"):
            self.builder.code(ITALIC_BEGIN)
        elif tag in ("u", "ins"):
            self.builder.code(UNDERLINE_BEGIN)
        elif tag in ("s", "strike", "del"):
            self.builder.code(STRIKE_BEGIN)
        elif tag == "br":
            self.builder.new_line()
        elif tag == "hr":
            self.builder.end_paragraph()
            self.builder.code(HORIZONTAL_RULE, RULE_HEIGHT, 0, RULE_WIDTH_PERCENT)
            self.builder.end_paragraph()
        elif tag == "li":
            self.builder.text(BULLET)
        elif tag == "img" and attributes.get("alt"):
            self.builder.text(f"[{attributes['alt'].strip()}]")
        elif tag == "a" and attributes.get("href") and not self.open_link:
            uid = self.link_uid(attributes["href"])
            if uid:
                self.builder.code(PAGE_LINK, uid >> 8, uid & 0xFF)
                self.open_link = True
        elif tag in ("center",):
            self.builder.code(SET_ALIGNMENT, ALIGN_CENTER)

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in SKIPPED_TAGS:
            self.skipping = max(0, self.skipping - 1)
            return
        if self.skipping:
            return
        if tag in HEADING_FONTS or tag in ("b", "strong", "th", "tt", "code", "kbd", "samp"):
            self.restore_font()
        elif tag == "pre":
            self.preformatted = max(0, self.preformatted - 1)
            self.restore_font()
        elif tag in ("i", "em", "cite", "var"):
            self.builder.code(ITALIC_END)
        elif tag in ("u", "ins"):
            self.builder.code(UNDERLINE_END)
        elif tag in ("s", "strike", "del"):
            self.builder.code(STRIKE_END)
        elif tag == "a" and self.open_link:
            self.builder.code(LINK_END)
            self.open_link = False
        elif tag == "center":
            self.builder.code(SET_ALIGNMENT, ALIGN_LEFT)
        if tag in BLOCK_TAGS:
            self.builder.end_paragraph()

    def handle_data(self, data):
        if self.in_title:
            self.title += data
            return
        if self.skipping:
            return
        if self.preformatted:
            lines = data.split("\n")
            for index, line in enumerate(lines):
                if index:
                    self.builder.new_line()
                self.builder.current += encode(line)
            return
        if data[:1].isspace():
            self.builder.pending_space = True
        collapsed = WHITESPACE.sub(" ", data).strip()
        if collapsed:
            self.builder.text(collapsed)
        if data[-1:].isspace():
            self.builder.pending_space = True


def html_page(html, uid, link_uid=None):
    converter = MarkupConverter(PageBuilder(uid), link_uid or (lambda href: None))
    converter.feed(html)
    converter.close()
    return converter.builder.finish(), WHITESPACE.sub(" ", converter.title).strip()


def text_page(text, uid):
    builder = PageBuilder(uid)
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = [line.rstrip() for line in block.split("\n")]
        for index, line in enumerate(lines):
            if index:
                builder.new_line()
            builder.current += encode(line)
        builder.end_paragraph()
    return builder.finish()


def split_pages(pages, next_uid, next_label="Next part"):
    result = []
    for page in pages:
        parts = [Page(page.uid)]
        size = 0
        for paragraph in page.paragraphs:
            if parts[-1].paragraphs and size + len(paragraph) > MAX_RECORD_TEXT:
                parts.append(Page(next_uid))
                next_uid += 1
                size = 0
            parts[-1].paragraphs.append(paragraph)
            size += len(paragraph)
        for current, following in zip(parts, parts[1:]):
            current.paragraphs.append(function(PAGE_LINK, following.uid >> 8, following.uid & 0xFF) + encode(next_label)
                                      + function(LINK_END))
        result.extend(parts)
    return result, next_uid


def text_record(page, compression):
    body = b"".join(page.paragraphs)
    headers = b"".join(PARAGRAPH_HEADER.pack(len(paragraph), PARAGRAPH_SPACING) for paragraph in page.paragraphs)
    if compression == COMPRESSION_ZLIB:
        return RECORD_HEADER.pack(page.uid, len(page.paragraphs), len(body), DATATYPE_PHTML_COMPRESSED, 0) + headers + zlib.compress(body, 9)
    return RECORD_HEADER.pack(page.uid, len(page.paragraphs), len(body), DATATYPE_PHTML, 0) + headers + body


def document_name(title):
    ascii_title = "".join(character if 0x20 <= ord(character) <= 0x7E else "_" for character in title).strip()
    return ascii_title[:NAME_LIMIT] or "Plucker document"


def build_document(title, pages, compression=COMPRESSION_ZLIB, next_uid=None):
    next_uid = next_uid or max(page.uid for page in pages) + 1
    pages, _ = split_pages(pages, next_uid)
    home = pages[0].uid
    index = struct.pack(">HHH", INDEX_UID, compression, 1) + struct.pack(">HH", RESERVED_HOME, home)
    now = datetime.now().replace(microsecond=0)
    records = [PdbRecord(index, 0, 1)] + [PdbRecord(text_record(page, compression), 0, page.uid) for page in pages]
    return PalmDatabase(document_name(title), TYPE, CREATOR, ATTRIBUTE_BACKUP, 1, now, now, records=records)


def read_document(database):
    index = database.records[0].data
    _uid, compression, count = struct.unpack_from(">HHH", index)
    reserved = dict(struct.unpack_from(">HH", index, 6 + 4 * position) for position in range(count))
    pages = {}
    for record in database.records[1:]:
        uid, paragraph_count, _size, kind, _reserved = RECORD_HEADER.unpack_from(record.data)
        if kind not in (DATATYPE_PHTML, DATATYPE_PHTML_COMPRESSED):
            continue
        headers = [PARAGRAPH_HEADER.unpack_from(record.data, RECORD_HEADER.size + PARAGRAPH_HEADER.size * position)
                   for position in range(paragraph_count)]
        body = record.data[RECORD_HEADER.size + PARAGRAPH_HEADER.size * paragraph_count:]
        if kind == DATATYPE_PHTML_COMPRESSED:
            if compression != COMPRESSION_ZLIB:
                raise ValueError("DOC compressed Plucker documents are not supported")
            body = zlib.decompress(body)
        paragraphs = []
        offset = 0
        for size, _attributes in headers:
            paragraphs.append(body[offset:offset + size])
            offset += size
        pages[uid] = Page(uid, paragraphs)
    return reserved.get(RESERVED_HOME), pages


def plain_text(paragraph):
    output = bytearray()
    position = 0
    while position < len(paragraph):
        byte = paragraph[position]
        if byte == 0 and position + 1 < len(paragraph):
            code = paragraph[position + 1]
            if code == NEW_LINE:
                output += b"\n"
            position += 2 + (code & 0x07)
            continue
        output.append(byte)
        position += 1
    return output.decode(ENCODING, errors="replace")
