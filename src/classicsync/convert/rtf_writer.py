from .bitmap import two_bit_dib, write_png
from .document import LINE_BREAK

SYMBOL_FONT = "Symbol"
BULLET_INDENT = 360
ALIGNMENT_WORDS = {"left": "", "center": "\\qc", "right": "\\qr", "justify": "\\qj"}
POCKET_WORD_1_SIZES = (16, 20, 24, 28, 32, 40, 48, 60, 72)


def escape_text(text, allow_unicode=True):
    pieces = []
    for character in text:
        code = ord(character)
        if character in "\\{}":
            pieces.append("\\" + character)
        elif character == "\t":
            pieces.append("\\tab ")
        elif character == LINE_BREAK:
            pieces.append("\\line ")
        elif 32 <= code < 128:
            pieces.append(character)
        elif code < 32:
            continue
        else:
            try:
                encoded = character.encode("cp1252")
                pieces.append("".join(f"\\'{byte:02x}" for byte in encoded))
            except UnicodeEncodeError:
                if not allow_unicode:
                    pieces.append("?")
                    continue
                signed = code if code < 32768 else code - 65536
                pieces.append(f"\\u{signed}?")
    return "".join(pieces)


class RtfWriter:
    def __init__(self, document, report, pocket_word_version=None):
        self.document = document
        self.report = report
        self.version = pocket_word_version
        self.fonts = document.fonts()
        if SYMBOL_FONT not in self.fonts:
            self.fonts.append(SYMBOL_FONT)
        self.colours = document.colours()

    def font_index(self, name):
        return self.fonts.index(name or self.document.default_font)

    def header(self):
        if self.version:
            lines = [f"{{\\pwd{self.version}\\ansi\\deff0\\deftab720"]
        else:
            lines = ["{\\rtf1\\ansi\\ansicpg1252\\deff0\\deftab720"]
        font_entries = []
        for index, name in enumerate(self.fonts):
            family = "\\fnil\\fcharset2" if name == SYMBOL_FONT else "\\fnil"
            font_entries.append(f"{{\\f{index}{family} {escape_text(name)};}}")
        lines.append("{\\fonttbl" + "".join(font_entries) + "}")
        colour_entries = "".join(f"\\red{red}\\green{green}\\blue{blue};" for red, green, blue in self.colours)
        lines.append("{\\colortbl;" + colour_entries + "}")
        styles = "".join(f"{{\\s{level} heading {level};}}" for level in range(1, 10))
        lines.append("{\\stylesheet{ Normal;}" + styles + "}")
        return "\r\n".join(lines) + "\r\n"

    def character_words(self, character):
        words = [f"\\plain\\f{self.font_index(character.font)}"]
        size = character.size_half_points or self.document.default_size_half_points
        if self.version == 1:
            size = min(POCKET_WORD_1_SIZES, key=lambda candidate: abs(candidate - size))
        words.append(f"\\fs{size}")
        if character.bold:
            words.append("\\b")
        if character.italic:
            words.append("\\i")
        if character.underline:
            words.append("\\ul")
        if character.strike:
            words.append("\\strike")
        if character.superscript:
            words.append("\\super")
        if character.subscript:
            words.append("\\sub")
        if character.colour is not None:
            if self.version == 1:
                self.report.lost("text colour (Pocket Word 1.0)")
            else:
                words.append(f"\\cf{self.colours.index(character.colour) + 1}")
        return "".join(words) + " "

    def paragraph_words(self, paragraph):
        words = ["\\pard"]
        if paragraph.heading_level:
            words.append(f"\\s{paragraph.heading_level}")
        if paragraph.alignment == "justify" and self.version == 1:
            self.report.lost("justified alignment (Pocket Word 1.0)")
        else:
            words.append(ALIGNMENT_WORDS.get(paragraph.alignment, ""))
        left_indent = paragraph.left_indent
        first_line_indent = paragraph.first_line_indent
        if paragraph.list_kind and not left_indent:
            left_indent = BULLET_INDENT
            first_line_indent = -BULLET_INDENT
        if left_indent:
            words.append(f"\\li{left_indent}")
        if paragraph.right_indent:
            words.append(f"\\ri{paragraph.right_indent}")
        if first_line_indent:
            words.append(f"\\fi{first_line_indent}")
        if self.version != 1:
            if paragraph.space_before:
                words.append(f"\\sb{paragraph.space_before}")
            if paragraph.space_after:
                words.append(f"\\sa{paragraph.space_after}")
        elif paragraph.space_before or paragraph.space_after:
            self.report.lost("paragraph spacing (Pocket Word 1.0)")
        for stop in paragraph.tab_stops:
            words.append(f"\\tx{stop}")
        if paragraph.page_break_before:
            if self.version:
                self.report.lost("page breaks")
            else:
                words.append("\\pagebb")
        return "".join(words) + " "

    def list_prefix(self, paragraph, number):
        symbol = self.font_index(SYMBOL_FONT)
        if paragraph.list_kind == "bullet":
            return (f"{{\\pntext\\f{symbol}\\'b7\\tab}}{{\\*\\pn\\pnlvlblt\\pnf{symbol}\\pnindent0"
                    f"{{\\pntxtb\\'b7}}}}")
        if self.version == 1:
            self.report.lost("numbered lists (written as typed numbers in Pocket Word 1.0)")
            return f"{number}.\\tab "
        return f"{{\\pntext {number}.\\tab}}{{\\*\\pn\\pnlvlbody\\pndec\\pnstart1\\pnindent360{{\\pntxta .}}}}"

    def picture(self, picture):
        bitmap = picture.bitmap
        width_goal = picture.width_twips or bitmap.width * 15
        height_goal = picture.height_twips or bitmap.height * 15
        sizes = f"\\picw{bitmap.width}\\pich{bitmap.height}\\picwgoal{width_goal}\\pichgoal{height_goal}"
        if self.version:
            dib = two_bit_dib(bitmap)
            stride = (bitmap.width * 2 + 31) // 32 * 4
            if not bitmap.is_grayscale():
                self.report.lost("picture colour (pictures are reduced to 4 grays)")
            return (f"{{\\pict\\dibitmap0{sizes}\\wbmbitspixel2\\wbmplanes1\\wbmwidthbytes{stride}\r\n"
                    f"\\bin{len(dib)} ").encode("ascii") + dib + b"}"
        hex_data = write_png(bitmap).hex()
        lines = "\r\n".join(hex_data[index:index + 128] for index in range(0, len(hex_data), 128))
        return f"{{\\pict\\pngblip{sizes}\r\n{lines}}}".encode("ascii")

    def write(self):
        output = bytearray(self.header().encode("ascii"))
        number = 0
        for paragraph in self.document.paragraphs:
            number = number + 1 if paragraph.list_kind == "number" else 0
            output.extend(self.paragraph_words(paragraph).encode("ascii"))
            if paragraph.list_kind and paragraph.runs:
                output.extend(self.list_prefix(paragraph, number).encode("ascii"))
            for run in paragraph.runs:
                output.extend(self.character_words(run.format).encode("ascii"))
                if run.picture is not None:
                    output.extend(self.picture(run.picture))
                else:
                    output.extend(escape_text(run.text, self.version != 1).encode("ascii"))
            output.extend(b"\\par\r\n")
        output.extend(b"}\r\n")
        return bytes(output)


def write_rtf(document, report):
    return RtfWriter(document, report).write()


def write_pocket_word(document, report, version=2):
    if version not in (1, 2):
        raise ValueError("Pocket Word version must be 1 or 2")
    return RtfWriter(document, report, version).write()

