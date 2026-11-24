import re
from dataclasses import dataclass, field, replace

from .bitmap import Bitmap, read_dib, read_png, unpack_indices
from .document import LINE_BREAK, CharacterFormat, Document, Paragraph, Picture, Run
from .errors import ConversionError

CHARSET_CODEPAGES = {
    0: None, 1: None, 2: "symbol", 77: "mac_roman", 128: "cp932", 129: "cp949", 134: "cp936", 136: "cp950",
    161: "cp1253", 162: "cp1254", 163: "cp1258", 177: "cp1255", 178: "cp1256", 186: "cp1257", 204: "cp1251",
    222: "cp874", 238: "cp1250",
}
SPECIAL_CHARACTERS = {
    "tab": "\t", "line": LINE_BREAK, "bullet": "•", "emdash": "—", "endash": "–", "emspace": " ",
    "enspace": " ", "lquote": "‘", "rquote": "’", "ldblquote": "“", "rdblquote": "”",
    "cell": "\t", "zwj": "‍", "zwnj": "‌", "ltrmark": "", "rtlmark": "",
}
SYMBOL_CHARACTERS = {"~": " ", "_": "‑", "-": "", "{": "{", "}": "}", "\\": "\\"}
SKIPPED_DESTINATIONS = {
    "info", "header", "headerl", "headerr", "headerf", "footer", "footerl", "footerr", "footerf", "footnote",
    "annotation", "atnid", "atnauthor", "atnref", "atrfstart", "atrfend", "comment", "pwdcomment", "objdata",
    "objclass", "objname", "fldinst", "nonshppict", "themedata", "colorschememapping", "datastore", "latentstyles",
    "listtable", "listoverridetable", "rsidtbl", "generator", "xmlnstbl", "mmathPr", "pgdsctbl", "filetbl",
    "revtbl", "bkmkstart", "bkmkend", "template", "keywords", "doccomm", "title", "author", "operator", "company",
    "falt", "panose", "fname", "txe", "ftnsep", "ftnsepc", "aftnsep", "aftnsepc", "pnseclvl", "userprops",
    "wgrffmtfilter", "pgptbl", "fchars", "lchars", "xe", "tc", "sp", "sn", "sv", "shpinst", "shptxt",
}
UNDERLINE_OFF_WORDS = {"ulnone", "ul0"}
UNDERLINE_WORDS = {"ul", "uld", "uldash", "uldashd", "uldashdd", "uldb", "ulhair", "ulth", "ulw", "ulwave", "ulthd",
                   "ulldash", "ulthdash", "ulthdashd", "ulthdashdd", "ulthldash", "ululdbwave"}
KNOWN_STARRED_DESTINATIONS = {"pn", "shppict", "pict", "listtext", "pntext"}
PARAGRAPH_WORDS = {"pard", "sectd", "ql", "qc", "qr", "qj", "qd", "li", "ri", "fi", "sb", "sa", "tx", "s", "ls", "ilvl",
                   "trowd", "intbl"}
HEADING_NAME = re.compile(r"^heading\s*(\d)$", re.IGNORECASE)
NUMBERED_LIST_TEXT = re.compile(r"^\s*[0-9A-Za-z]{1,4}[.)]")


@dataclass
class ParagraphFormat:
    alignment: str = "left"
    left_indent: int = 0
    right_indent: int = 0
    first_line_indent: int = 0
    space_before: int = 0
    space_after: int = 0
    tab_stops: tuple = ()
    list_kind: str = ""
    style: int = 0


@dataclass
class GroupState:
    destination: str = "text"
    character: CharacterFormat = field(default_factory=CharacterFormat)
    font_index: int = None
    style_number: int = 0
    unicode_skip: int = 1
    hidden: bool = False


@dataclass
class PictureState:
    kind: str = ""
    parameters: dict = field(default_factory=dict)
    data: bytearray = field(default_factory=bytearray)
    hex_digits: list = field(default_factory=list)


def tokenize(data):
    index = 0
    length = len(data)
    while index < length:
        byte = data[index]
        if byte == 0x7B:
            yield "open", None, None
            index += 1
        elif byte == 0x7D:
            yield "close", None, None
            index += 1
        elif byte == 0x5C:
            index += 1
            if index >= length:
                break
            following = data[index]
            if chr(following).isalpha():
                start = index
                while index < length and chr(data[index]).isalpha() and index - start < 32:
                    index += 1
                word = data[start:index].decode("ascii")
                parameter = None
                number_start = index
                if index < length and data[index] == 0x2D:
                    index += 1
                while index < length and chr(data[index]).isdigit():
                    index += 1
                if index > number_start and data[number_start:index] != b"-":
                    parameter = int(data[number_start:index])
                else:
                    index = number_start
                if index < length and data[index] == 0x20:
                    index += 1
                if word == "bin" and parameter:
                    yield "binary", word, data[index:index + parameter]
                    index += parameter
                else:
                    yield "word", word, parameter
            elif following == 0x27:
                yield "hex", None, int(data[index + 1:index + 3], 16)
                index += 3
            else:
                yield "symbol", chr(following), None
                index += 1
        elif byte in (0x0D, 0x0A):
            index += 1
        else:
            start = index
            while index < length and data[index] not in (0x7B, 0x7D, 0x5C, 0x0D, 0x0A):
                index += 1
            yield "text", None, data[start:index]


class RtfReader:
    def __init__(self, report):
        self.report = report
        self.document = Document()
        self.fonts = {}
        self.font_charsets = {}
        self.colours = []
        self.colour_parts = {}
        self.style_levels = {}
        self.codepage = "cp1252"
        self.default_font_index = 0
        self.paragraph = Paragraph()
        self.paragraph_format = ParagraphFormat()
        self.pending_list_kind = ""
        self.pending_page_break = False
        self.font_entry = None
        self.style_entry = None
        self.picture = None
        self.list_text = None
        self.pending_bytes = bytearray()
        self.skip_count = 0
        self.dialect = ""

    def read(self, data):
        stack = [GroupState()]
        expecting_destination = False
        tokens = tokenize(data)
        for kind, word, value in tokens:
            state = stack[-1]
            if kind != "hex" and kind != "text":
                self.flush_bytes(state)
            if kind == "open":
                stack.append(replace(state))
                expecting_destination = False
                continue
            if kind == "close":
                self.close_group(state)
                if len(stack) > 1:
                    stack.pop()
                continue
            if kind == "symbol" and word == "*":
                expecting_destination = True
                continue
            if expecting_destination:
                expecting_destination = False
                if kind == "word" and word not in KNOWN_STARRED_DESTINATIONS:
                    state.destination = "skip"
                    continue
            if state.destination == "skip":
                continue
            if kind == "word":
                self.control_word(state, word, value)
            elif kind == "binary":
                if state.destination == "pict" and self.picture is not None:
                    self.picture.data.extend(value)
            elif kind == "hex":
                self.hex_byte(state, value)
            elif kind == "symbol":
                self.symbol(state, word)
            elif kind == "text":
                self.text_bytes(state, value)
        self.flush_bytes(stack[-1])
        if self.paragraph.runs:
            self.finish_paragraph(stack[-1])
        if not self.document.paragraphs:
            self.document.paragraphs.append(Paragraph())
        default_name = self.fonts.get(self.default_font_index)
        if default_name:
            self.document.default_font = default_name
        return self.document

    def codepage_for(self, state):
        charset = self.font_charsets.get(state.font_index)
        codepage = CHARSET_CODEPAGES.get(charset)
        if codepage == "symbol":
            return "latin-1"
        return codepage or self.codepage

    def flush_bytes(self, state):
        if not self.pending_bytes:
            return
        text = bytes(self.pending_bytes).decode(self.codepage_for(state), errors="replace")
        self.pending_bytes.clear()
        self.emit_text(state, text)

    def hex_byte(self, state, value):
        if self.skip_count:
            self.skip_count -= 1
            return
        if state.destination == "pict":
            self.picture.hex_digits.append(f"{value:02x}")
            return
        self.pending_bytes.append(value)

    def text_bytes(self, state, value):
        if state.destination == "pict":
            if self.picture is not None:
                self.picture.hex_digits.append(value.decode("ascii", errors="ignore"))
            return
        if self.skip_count:
            skipped = min(self.skip_count, len(value))
            self.skip_count -= skipped
            value = value[skipped:]
        self.pending_bytes.extend(value)

    def symbol(self, state, character):
        text = SYMBOL_CHARACTERS.get(character)
        if text is not None:
            self.emit_text(state, text)

    def emit_text(self, state, text):
        if not text:
            return
        if state.destination == "fonttbl":
            if self.font_entry is not None:
                self.font_entry.append(text)
                if ";" in text:
                    self.fonts[state.font_index] = "".join(self.font_entry).split(";")[0].strip()
                    self.font_entry = []
            return
        if state.destination == "colortbl":
            for _ in range(text.count(";")):
                parts = self.colour_parts
                self.colours.append((parts["red"], parts["green"], parts["blue"]) if parts else None)
                self.colour_parts = {}
            return
        if state.destination == "stylesheet":
            if self.style_entry is not None:
                self.style_entry.append(text)
            return
        if state.destination in ("listtext", "pntext"):
            if self.list_text is not None:
                self.list_text.append(text)
            return
        if state.destination != "text" or state.hidden:
            return
        self.paragraph.append_text(text, self.character_format(state))

    def character_format(self, state):
        return state.character.changed(font=self.fonts.get(state.font_index, ""))

    def close_group(self, state):
        if state.destination == "stylesheet" and self.style_entry is not None:
            name = "".join(self.style_entry).split(";")[0].strip()
            match = HEADING_NAME.match(name)
            if match and state.style_number:
                self.style_levels[state.style_number] = int(match.group(1))
            self.style_entry = []
        elif state.destination == "pict" and self.picture is not None:
            self.finish_picture(state)
        elif state.destination in ("listtext", "pntext") and self.list_text is not None:
            text = "".join(self.list_text)
            self.list_text = None
            if text.strip():
                self.pending_list_kind = "number" if NUMBERED_LIST_TEXT.match(text) else "bullet"

    def control_word(self, state, word, value):
        destination = state.destination
        if word in ("rtf", "pwd"):
            self.dialect = f"{word}{value}"
            return
        if word in ("fonttbl", "colortbl", "stylesheet", "pict", "listtext", "pntext", "pn"):
            state.destination = word
            if word == "fonttbl":
                self.font_entry = None
            elif word == "colortbl":
                self.colour_parts = {}
            elif word == "stylesheet":
                self.style_entry = []
            elif word == "pict":
                self.picture = PictureState()
            elif word in ("listtext", "pntext"):
                self.list_text = []
            elif word == "pn":
                if not self.paragraph_format.list_kind:
                    self.paragraph_format.list_kind = "bullet"
            return
        if word in SKIPPED_DESTINATIONS:
            state.destination = "skip"
            return
        if destination == "fonttbl":
            if word == "f":
                state.font_index = value
                self.font_entry = []
            elif word == "fcharset":
                self.font_charsets[state.font_index] = value
            return
        if destination == "colortbl":
            if word in ("red", "green", "blue"):
                self.colour_parts[word] = value or 0
            return
        if destination == "pict":
            self.picture_word(word, value)
            return
        if destination == "stylesheet":
            if word == "s":
                state.style_number = value or 0
            return
        if destination == "pn":
            if word == "pnlvlblt":
                self.paragraph_format.list_kind = "bullet"
            elif word in ("pndec", "pnucltr", "pnlcltr", "pnucrm", "pnlcrm"):
                self.paragraph_format.list_kind = "number"
            return
        if word == "ansicpg" and value:
            self.codepage = f"cp{value}"
        elif word == "deff":
            self.default_font_index = value or 0
        elif word == "uc":
            state.unicode_skip = value or 0
        elif word == "u":
            self.emit_text(state, chr(value % 65536))
            self.skip_count = state.unicode_skip
        elif word in SPECIAL_CHARACTERS:
            self.emit_text(state, SPECIAL_CHARACTERS[word])
        elif word in ("par", "row"):
            self.finish_paragraph(state)
        elif word == "page":
            if self.paragraph.runs:
                self.finish_paragraph(state)
            self.pending_page_break = True
        else:
            self.formatting_word(state, word, value)

    def formatting_word(self, state, word, value):
        character = state.character
        paragraph = self.paragraph_format
        enabled = value != 0
        if state.destination != "text" and word in PARAGRAPH_WORDS:
            return
        if word == "plain":
            state.character = CharacterFormat()
            state.font_index = None
            state.hidden = False
        elif word == "b":
            state.character = character.changed(bold=enabled)
        elif word == "i":
            state.character = character.changed(italic=enabled)
        elif word in UNDERLINE_WORDS:
            state.character = character.changed(underline=enabled)
        elif word in UNDERLINE_OFF_WORDS:
            state.character = character.changed(underline=False)
        elif word in ("strike", "striked", "deleted"):
            state.character = character.changed(strike=enabled)
        elif word == "super":
            state.character = character.changed(superscript=True, subscript=False)
        elif word == "sub":
            state.character = character.changed(subscript=True, superscript=False)
        elif word == "up":
            state.character = character.changed(superscript=enabled, subscript=False)
        elif word == "dn":
            state.character = character.changed(subscript=enabled, superscript=False)
        elif word == "nosupersub":
            state.character = character.changed(superscript=False, subscript=False)
        elif word == "f":
            state.font_index = value
        elif word == "fs":
            state.character = character.changed(size_half_points=value or 0)
        elif word == "cf":
            colour = self.colours[value] if value is not None and 0 < value < len(self.colours) else None
            state.character = character.changed(colour=colour if colour != (0, 0, 0) else None)
        elif word == "v":
            state.hidden = enabled
        elif word in ("pard", "sectd"):
            self.paragraph_format = ParagraphFormat()
        elif word == "ql":
            paragraph.alignment = "left"
        elif word == "qc":
            paragraph.alignment = "center"
        elif word == "qr":
            paragraph.alignment = "right"
        elif word in ("qj", "qd"):
            paragraph.alignment = "justify"
        elif word == "li":
            paragraph.left_indent = value or 0
        elif word == "ri":
            paragraph.right_indent = value or 0
        elif word == "fi":
            paragraph.first_line_indent = value or 0
        elif word == "sb":
            paragraph.space_before = value or 0
        elif word == "sa":
            paragraph.space_after = value or 0
        elif word == "tx" and value is not None:
            paragraph.tab_stops = paragraph.tab_stops + (value,)
        elif word == "s":
            paragraph.style = value or 0
        elif word in ("ls", "ilvl") and not paragraph.list_kind:
            paragraph.list_kind = "bullet"
        elif word in ("trowd", "intbl"):
            self.report.lost("tables (cells become tab-separated paragraphs)")
        elif word in ("object", "field"):
            if word == "object":
                self.report.lost("embedded objects (only their picture results are kept)")

    def finish_paragraph(self, state):
        format = self.paragraph_format
        list_kind = format.list_kind or self.pending_list_kind
        self.pending_list_kind = ""
        paragraph = self.paragraph
        paragraph.alignment = format.alignment
        paragraph.left_indent = format.left_indent
        paragraph.right_indent = format.right_indent
        paragraph.first_line_indent = format.first_line_indent
        paragraph.space_before = format.space_before
        paragraph.space_after = format.space_after
        paragraph.tab_stops = list(format.tab_stops)
        paragraph.list_kind = list_kind
        paragraph.heading_level = self.style_levels.get(format.style, 0)
        paragraph.page_break_before = self.pending_page_break
        self.pending_page_break = False
        self.document.paragraphs.append(paragraph)
        self.paragraph = Paragraph()

    def picture_word(self, word, value):
        picture = self.picture
        if word in ("dibitmap", "wbitmap", "pngblip", "jpegblip", "emfblip", "wmetafile", "macpict", "pmmetafile"):
            picture.kind = word
        picture.parameters[word] = value

    def finish_picture(self, state):
        picture = self.picture
        self.picture = None
        data = bytes(picture.data)
        if not data and picture.hex_digits:
            digits = "".join(picture.hex_digits)
            digits = "".join(character for character in digits if character in "0123456789abcdefABCDEF")
            data = bytes.fromhex(digits[:len(digits) // 2 * 2])
        bitmap = None
        try:
            if picture.kind == "dibitmap":
                bitmap, _, _ = read_dib(data)
            elif picture.kind == "wbitmap":
                bitmap = device_bitmap(data, picture.parameters)
            elif picture.kind == "pngblip":
                bitmap = read_png(data)
        except (ConversionError, ValueError, IndexError) as error:
            self.report.lost(f"a picture that could not be decoded ({error})")
            return
        if bitmap is None:
            self.report.lost(f"pictures in {picture.kind or 'unknown'} format")
            return
        parameters = picture.parameters
        width = parameters.get("picwgoal") or bitmap.width * 15
        height = parameters.get("pichgoal") or bitmap.height * 15
        width = width * (parameters.get("picscalex") or 100) // 100
        height = height * (parameters.get("picscaley") or 100) // 100
        self.paragraph.runs.append(Run("", self.character_format(state), Picture(bitmap, width, height)))


def device_bitmap(data, parameters):
    bits_per_pixel = parameters.get("wbmbitspixel") or 1
    width = parameters.get("picw") or 0
    height = parameters.get("pich") or 0
    stride = parameters.get("wbmwidthbytes") or (width * bits_per_pixel + 15) // 16 * 2
    if bits_per_pixel not in (1, 2, 4, 8):
        raise ConversionError(f"{bits_per_pixel}-bit device bitmaps")
    levels = (1 << bits_per_pixel) - 1
    palette = [(level * 255 // levels,) * 3 for level in range(levels + 1)]
    rows = []
    for row in range(height):
        indices = unpack_indices(data[row * stride:(row + 1) * stride], width, bits_per_pixel)
        rows.append([palette[index] for index in indices])
    return Bitmap(width, height, rows)


def read_rtf(data, report):
    if not data.lstrip().startswith(b"{\\"):
        raise ConversionError("not an RTF or Pocket Word document")
    if data.lstrip().startswith(b"{\\pwd") and b"\\pwdcrypt" in data[:200]:
        raise ConversionError("password-protected Pocket Word documents are not supported")
    return RtfReader(report).read(data)
