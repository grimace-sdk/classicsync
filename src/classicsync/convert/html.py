import base64
import html
import re
from html.parser import HTMLParser

from .bitmap import read_image, write_png
from .document import LINE_BREAK, CharacterFormat, Document, Paragraph, Picture, Run
from .errors import ConversionError
from .text import decode_text

TWIPS_PER_PIXEL = 15
TWIPS_PER_POINT = 20
BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "tr", "dt", "dd", "title"}
SKIPPED_TAGS = {"script", "style", "head", "title"}
LIST_TAGS = {"ul": "bullet", "ol": "number"}
LENGTH = re.compile(r"(-?[\d.]+)\s*(pt|px|em|in|cm|mm)?")
UNIT_TWIPS = {"pt": 20, "px": 15, "em": 240, "in": 1440, "cm": 567, "mm": 56.7, None: 15}
NAMED_COLOURS = {"black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0), "green": (0, 128, 0),
                 "blue": (0, 0, 255), "yellow": (255, 255, 0), "gray": (128, 128, 128), "grey": (128, 128, 128),
                 "navy": (0, 0, 128), "maroon": (128, 0, 0), "purple": (128, 0, 128), "teal": (0, 128, 128)}
FONT_SIZE_HALF_POINTS = {"1": 16, "2": 20, "3": 24, "4": 28, "5": 36, "6": 48, "7": 72}


def colour_css(colour):
    return "#%02x%02x%02x" % colour


def run_html(run):
    if run.picture is not None:
        picture = run.picture
        encoded = base64.b64encode(write_png(picture.bitmap)).decode("ascii")
        width = round(picture.width_twips / TWIPS_PER_PIXEL) if picture.width_twips else picture.bitmap.width
        height = round(picture.height_twips / TWIPS_PER_PIXEL) if picture.height_twips else picture.bitmap.height
        return f'<img src="data:image/png;base64,{encoded}" width="{width}" height="{height}" alt="">'
    text = html.escape(run.text).replace(LINE_BREAK, "<br>")
    character = run.format
    styles = []
    if character.font:
        styles.append(f"font-family: '{character.font}'")
    if character.size_half_points:
        styles.append(f"font-size: {character.size_half_points / 2:g}pt")
    if character.colour is not None:
        styles.append(f"color: {colour_css(character.colour)}")
    if styles:
        text = f'<span style="{"; ".join(styles)}">{text}</span>'
    for enabled, tag in ((character.bold, "b"), (character.italic, "i"), (character.underline, "u"),
                         (character.strike, "s"), (character.superscript, "sup"), (character.subscript, "sub")):
        if enabled:
            text = f"<{tag}>{text}</{tag}>"
    return text


def paragraph_style(paragraph):
    styles = []
    if paragraph.alignment != "left":
        styles.append(f"text-align: {paragraph.alignment}")
    if paragraph.left_indent and not paragraph.list_kind:
        styles.append(f"margin-left: {paragraph.left_indent / TWIPS_PER_POINT:g}pt")
    if paragraph.right_indent:
        styles.append(f"margin-right: {paragraph.right_indent / TWIPS_PER_POINT:g}pt")
    if paragraph.first_line_indent and not paragraph.list_kind:
        styles.append(f"text-indent: {paragraph.first_line_indent / TWIPS_PER_POINT:g}pt")
    if paragraph.space_before:
        styles.append(f"margin-top: {paragraph.space_before / TWIPS_PER_POINT:g}pt")
    if paragraph.space_after:
        styles.append(f"margin-bottom: {paragraph.space_after / TWIPS_PER_POINT:g}pt")
    if paragraph.page_break_before:
        styles.append("page-break-before: always")
    return f' style="{"; ".join(styles)}"' if styles else ""


def write_html(document, report, title=""):
    body = []
    open_list = ""
    for paragraph in document.paragraphs:
        list_tag = {"bullet": "ul", "number": "ol"}.get(paragraph.list_kind, "")
        if list_tag != open_list:
            if open_list:
                body.append(f"</{open_list}>")
            if list_tag:
                body.append(f"<{list_tag}>")
            open_list = list_tag
        if paragraph.tab_stops:
            report.lost("tab stop positions")
        content = "".join(run_html(run) for run in paragraph.runs) or "<br>"
        tag = "li" if list_tag else (f"h{paragraph.heading_level}" if paragraph.heading_level else "p")
        body.append(f"<{tag}{paragraph_style(paragraph)}>{content}</{tag}>")
    if open_list:
        body.append(f"</{open_list}>")
    font = html.escape(document.default_font)
    size = document.default_size_half_points / 2
    page = ["<!DOCTYPE html>", "<html>", "<head>", '<meta charset="utf-8">',
            f"<title>{html.escape(title or document.title)}</title>",
            f"<style>body {{ font-family: '{font}'; font-size: {size:g}pt; }} "
            "p, li, h1, h2, h3, h4, h5, h6 { white-space: pre-wrap; margin: 0; }</style>",
            "</head>", "<body>"] + body + ["</body>", "</html>", ""]
    return "\n".join(page).encode("utf-8")


def parse_colour(value):
    value = value.strip().lower()
    if value in NAMED_COLOURS:
        return NAMED_COLOURS[value]
    match = re.match(r"#([0-9a-f]{6})$", value)
    if match:
        return tuple(bytes.fromhex(match.group(1)))
    match = re.match(r"#([0-9a-f]{3})$", value)
    if match:
        return tuple(int(digit * 2, 16) for digit in match.group(1))
    match = re.match(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", value)
    if match:
        return tuple(int(part) for part in match.groups())
    return None


def length_twips(value):
    match = LENGTH.match(value.strip())
    if not match:
        return 0
    return round(float(match.group(1)) * UNIT_TWIPS[match.group(2)])


def parse_style(value):
    styles = {}
    for declaration in (value or "").split(";"):
        name, _, setting = declaration.partition(":")
        if setting:
            styles[name.strip().lower()] = setting.strip()
    return styles


class DocumentBuilder(HTMLParser):
    def __init__(self, report):
        super().__init__(convert_charrefs=True)
        self.report = report
        self.document = Document()
        self.format_stack = [(None, CharacterFormat())]
        self.paragraph = Paragraph()
        self.paragraph_tags = []
        self.list_stack = []
        self.skip_depth = 0
        self.preformatted = 0

    def current_format(self):
        return self.format_stack[-1][1]

    def finish_paragraph(self, force=False):
        if self.paragraph.runs or force:
            if self.list_stack and not self.paragraph.list_kind and self.paragraph_tags and \
                    self.paragraph_tags[-1][0] == "li":
                self.paragraph.list_kind = self.list_stack[-1]
            self.document.paragraphs.append(self.paragraph)
        template = self.paragraph
        self.paragraph = Paragraph(alignment=template.alignment if self.paragraph_tags else "left")
        if self.paragraph_tags:
            self.apply_paragraph_style(self.paragraph_tags[-1][1])

    def apply_paragraph_style(self, attributes):
        styles = parse_style(attributes.get("style"))
        alignment = styles.get("text-align") or attributes.get("align")
        if alignment in ("left", "center", "right", "justify"):
            self.paragraph.alignment = alignment
        if "margin-left" in styles:
            self.paragraph.left_indent = length_twips(styles["margin-left"])
        if "margin-right" in styles:
            self.paragraph.right_indent = length_twips(styles["margin-right"])
        if "text-indent" in styles:
            self.paragraph.first_line_indent = length_twips(styles["text-indent"])

    def handle_starttag(self, tag, attributes_list):
        attributes = {name: value or "" for name, value in attributes_list}
        if tag in SKIPPED_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in LIST_TAGS:
            self.finish_paragraph()
            self.list_stack.append(LIST_TAGS[tag])
            return
        if tag == "br":
            self.paragraph.append_text(LINE_BREAK, self.current_format())
            return
        if tag == "img":
            self.image(attributes)
            return
        if tag == "table":
            self.report.lost("tables (cells become tab-separated paragraphs)")
        if tag in ("td", "th") and self.paragraph.runs:
            self.paragraph.append_text("\t", self.current_format())
        if tag in BLOCK_TAGS:
            self.finish_paragraph()
            self.paragraph_tags.append((tag, attributes))
            self.apply_paragraph_style(attributes)
            if tag[0] == "h" and tag[1:].isdigit():
                self.paragraph.heading_level = int(tag[1:])
            if tag == "pre":
                self.preformatted += 1
        character = self.current_format()
        styles = parse_style(attributes.get("style"))
        if tag in ("b", "strong") or tag[0] == "h" and tag[1:].isdigit() or tag == "th":
            character = character.changed(bold=True)
        if tag in ("i", "em", "cite", "var"):
            character = character.changed(italic=True)
        if tag in ("u", "ins"):
            character = character.changed(underline=True)
        if tag in ("s", "strike", "del"):
            character = character.changed(strike=True)
        if tag == "sup":
            character = character.changed(superscript=True)
        if tag == "sub":
            character = character.changed(subscript=True)
        if tag in ("pre", "code", "tt"):
            character = character.changed(font="Courier New")
        if tag == "font":
            if attributes.get("face"):
                character = character.changed(font=attributes["face"].split(",")[0].strip())
            if attributes.get("size") in FONT_SIZE_HALF_POINTS:
                character = character.changed(size_half_points=FONT_SIZE_HALF_POINTS[attributes["size"]])
            if attributes.get("color"):
                character = character.changed(colour=parse_colour(attributes["color"]))
        weight = styles.get("font-weight", "")
        if weight in ("bold", "bolder") or weight.isdigit() and int(weight) >= 600:
            character = character.changed(bold=True)
        elif weight in ("normal", "lighter") or weight.isdigit():
            character = character.changed(bold=False)
        if styles.get("font-style") in ("italic", "oblique"):
            character = character.changed(italic=True)
        decoration = styles.get("text-decoration", "")
        if "underline" in decoration:
            character = character.changed(underline=True)
        if "line-through" in decoration:
            character = character.changed(strike=True)
        if "font-family" in styles:
            character = character.changed(font=styles["font-family"].split(",")[0].strip().strip("'\""))
        if "font-size" in styles:
            size = length_twips(styles["font-size"])
            if size:
                character = character.changed(size_half_points=round(size / 10))
        if "color" in styles:
            character = character.changed(colour=parse_colour(styles["color"]))
        self.format_stack.append((tag, character))

    def handle_endtag(self, tag):
        if tag in SKIPPED_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag in LIST_TAGS:
            self.finish_paragraph()
            if self.list_stack:
                self.list_stack.pop()
            return
        for depth in range(len(self.format_stack) - 1, 0, -1):
            if self.format_stack[depth][0] == tag:
                del self.format_stack[depth:]
                break
        if tag in BLOCK_TAGS:
            only_break = len(self.paragraph.runs) == 1 and self.paragraph.text() == LINE_BREAK
            if only_break:
                self.paragraph.runs = []
            self.finish_paragraph(force=only_break)
            for depth in range(len(self.paragraph_tags) - 1, -1, -1):
                if self.paragraph_tags[depth][0] == tag:
                    del self.paragraph_tags[depth:]
                    break
            self.paragraph = Paragraph()
            if self.paragraph_tags:
                self.apply_paragraph_style(self.paragraph_tags[-1][1])
            if tag == "pre":
                self.preformatted = max(0, self.preformatted - 1)

    def handle_data(self, data):
        if self.skip_depth:
            return
        if self.preformatted:
            lines = data.split("\n")
            for index, line in enumerate(lines):
                if index:
                    self.finish_paragraph(force=True)
                if line:
                    self.paragraph.append_text(line, self.current_format())
            return
        text = re.sub(r"[ \r\n\f\v]+", " ", data)
        if not self.paragraph.runs:
            text = text.lstrip()
        if text:
            self.paragraph.append_text(text, self.current_format())

    def image(self, attributes):
        source = attributes.get("src", "")
        match = re.match(r"data:image/[\w.+-]+;base64,(.*)$", source, re.DOTALL)
        if not match:
            self.report.lost("linked images (only embedded data: images are kept)")
            return
        try:
            bitmap = read_image(base64.b64decode(match.group(1)))
        except (ConversionError, ValueError) as error:
            self.report.lost(f"an image that could not be decoded ({error})")
            return
        width = length_twips(attributes.get("width") or "") or bitmap.width * TWIPS_PER_PIXEL
        height = length_twips(attributes.get("height") or "") or bitmap.height * TWIPS_PER_PIXEL
        self.paragraph.runs.append(Run("", self.current_format(), Picture(bitmap, width, height)))

    def result(self):
        self.finish_paragraph()
        for paragraph in self.document.paragraphs:
            if paragraph.runs and paragraph.runs[-1].picture is None:
                paragraph.runs[-1].text = paragraph.runs[-1].text.rstrip(" ")
        if not self.document.paragraphs:
            self.document.paragraphs.append(Paragraph())
        return self.document


def read_html(data, report):
    builder = DocumentBuilder(report)
    builder.feed(decode_text(data))
    builder.close()
    return builder.result()
