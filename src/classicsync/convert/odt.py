import io
import re
import zipfile
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from .bitmap import read_image, write_png
from .document import LINE_BREAK, CharacterFormat, Document, Paragraph, Picture, Run
from .errors import ConversionError

OFFICE_NAMESPACE = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
STYLE_NAMESPACE = "urn:oasis:names:tc:opendocument:xmlns:style:1.0"
TEXT_NAMESPACE = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
TABLE_NAMESPACE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
DRAW_NAMESPACE = "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
FO_NAMESPACE = "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
SVG_NAMESPACE = "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"
NUMBER_NAMESPACE = "urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0"
MANIFEST_NAMESPACE = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
OFFICE = "{%s}" % OFFICE_NAMESPACE
STYLE = "{%s}" % STYLE_NAMESPACE
TEXT = "{%s}" % TEXT_NAMESPACE
TABLE = "{%s}" % TABLE_NAMESPACE
DRAW = "{%s}" % DRAW_NAMESPACE
FO = "{%s}" % FO_NAMESPACE
SVG = "{%s}" % SVG_NAMESPACE
XLINK = "{%s}" % XLINK_NAMESPACE
NAMESPACE_DECLARATIONS = (
    f'xmlns:office="{OFFICE_NAMESPACE}" xmlns:style="{STYLE_NAMESPACE}" xmlns:text="{TEXT_NAMESPACE}" '
    f'xmlns:table="{TABLE_NAMESPACE}" xmlns:draw="{DRAW_NAMESPACE}" xmlns:fo="{FO_NAMESPACE}" '
    f'xmlns:svg="{SVG_NAMESPACE}" xmlns:xlink="{XLINK_NAMESPACE}" xmlns:number="{NUMBER_NAMESPACE}" '
    'xmlns:of="urn:oasis:names:tc:opendocument:xmlns:of:1.2" office:version="1.2"'
)
TEXT_MIMETYPE = "application/vnd.oasis.opendocument.text"
SPREADSHEET_MIMETYPE = "application/vnd.oasis.opendocument.spreadsheet"
TWIPS_PER_UNIT = {"in": 1440, "cm": 1440 / 2.54, "mm": 1440 / 25.4, "pt": 20, "pc": 240, "px": 15}
LENGTH = re.compile(r"(-?[\d.]+)\s*(in|cm|mm|pt|pc|px)?")
ALIGNMENT_VALUES = {"left": "start", "center": "center", "right": "end", "justify": "justify"}
ALIGNMENT_NAMES = {"start": "left", "left": "left", "center": "center", "end": "right", "right": "right",
                   "justify": "justify"}


def quoted(value):
    return escape(str(value), {'"': "&quot;"})


def length_twips(value):
    if not value:
        return 0
    match = LENGTH.match(value.strip())
    if not match:
        return 0
    return round(float(match.group(1)) * TWIPS_PER_UNIT[match.group(2) or "pt"])


def twips_length(twips):
    return f"{twips / 1440:.4f}in"


def font_size_half_points(value):
    if not value or value.endswith("%"):
        return 0
    return round(length_twips(value) / 10)


def parse_colour(value):
    if value and re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return tuple(bytes.fromhex(value[1:]))
    return None


def package(mimetype, parts):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(zipfile.ZipInfo("mimetype"), mimetype, compress_type=zipfile.ZIP_STORED)
        entries = "".join(f'<manifest:file-entry manifest:full-path="{quoted(name)}" manifest:media-type="{media_type}"/>'
                          for name, (_, media_type) in parts.items())
        archive.writestr("META-INF/manifest.xml", (
            f'<?xml version="1.0" encoding="UTF-8"?>\n<manifest:manifest xmlns:manifest="{MANIFEST_NAMESPACE}" '
            f'manifest:version="1.2"><manifest:file-entry manifest:full-path="/" manifest:media-type="{mimetype}"/>'
            f"{entries}</manifest:manifest>"))
        for name, (data, _) in parts.items():
            archive.writestr(name, data)
    return output.getvalue()


def open_package(data, expected_mimetype, description):
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise ConversionError(f"not an {description} file") from error
    try:
        mimetype = archive.read("mimetype").decode("ascii", "replace").strip()
    except KeyError:
        mimetype = ""
    if mimetype and not mimetype.startswith(expected_mimetype):
        archive.close()
        raise ConversionError(f"not an {description} file ({mimetype})")
    return archive


def read_part(archive, name):
    try:
        return ElementTree.fromstring(archive.read(name))
    except KeyError:
        return None


class StyleSheet:
    def __init__(self):
        self.styles = {}
        self.defaults = {}
        self.list_kinds = {}

    def add_from(self, root):
        if root is None:
            return
        for container_name in ("styles", "automatic-styles"):
            for container in root.iter(OFFICE + container_name):
                for element in container:
                    if element.tag == STYLE + "style":
                        self.styles[(element.get(STYLE + "family"), element.get(STYLE + "name"))] = element
                    elif element.tag == STYLE + "default-style":
                        self.defaults[element.get(STYLE + "family")] = element
                    elif element.tag == TEXT + "list-style":
                        first = next(iter(element), None)
                        kind = "number" if first is not None and first.tag == TEXT + "list-level-style-number" else "bullet"
                        self.list_kinds[element.get(STYLE + "name")] = kind

    def chain(self, family, name):
        elements = []
        seen = set()
        while name and (family, name) in self.styles and name not in seen:
            seen.add(name)
            element = self.styles[(family, name)]
            elements.append(element)
            name = element.get(STYLE + "parent-style-name")
        default = self.defaults.get(family)
        if default is not None:
            elements.append(default)
        return list(reversed(elements))

    def properties(self, family, name, kind):
        merged = {}
        for element in self.chain(family, name):
            for properties in element.findall(STYLE + kind):
                merged.update(properties.attrib)
        return merged

    def style_attribute(self, family, name, attribute):
        for element in reversed(self.chain(family, name)):
            if element.get(attribute):
                return element.get(attribute)
        return None


def character_format(attributes, base, fonts):
    format = base
    weight = attributes.get(FO + "font-weight")
    if weight:
        format = format.changed(bold=weight == "bold" or (weight.isdigit() and int(weight) >= 600))
    style = attributes.get(FO + "font-style")
    if style:
        format = format.changed(italic=style in ("italic", "oblique"))
    underline = attributes.get(STYLE + "text-underline-style")
    if underline:
        format = format.changed(underline=underline != "none")
    strike = attributes.get(STYLE + "text-line-through-style")
    if strike:
        format = format.changed(strike=strike != "none")
    position = attributes.get(STYLE + "text-position")
    if position:
        offset = position.split()[0]
        if offset in ("super", "sub"):
            raised = 1 if offset == "super" else -1
        else:
            try:
                raised = float(offset.rstrip("%"))
            except ValueError:
                raised = 0
        format = format.changed(superscript=raised > 0, subscript=raised < 0)
    font = attributes.get(STYLE + "font-name")
    font = fonts.get(font, font) if font else attributes.get(FO + "font-family")
    if font:
        format = format.changed(font=font.strip("'\""))
    size = font_size_half_points(attributes.get(FO + "font-size"))
    if size:
        format = format.changed(size_half_points=size)
    colour = attributes.get(FO + "color")
    if colour:
        rgb = parse_colour(colour)
        format = format.changed(colour=None if rgb in (None, (0, 0, 0)) else rgb)
    return format


class OdtReader:
    def __init__(self, archive, report):
        self.archive = archive
        self.report = report
        self.styles = StyleSheet()
        self.fonts = {}
        self.document = Document()

    def read_fonts(self, root):
        if root is None:
            return
        for face in root.iter(STYLE + "font-face"):
            family = face.get(SVG + "font-family")
            if family:
                self.fonts[face.get(STYLE + "name")] = family.strip("'\"")

    def read(self):
        content = read_part(self.archive, "content.xml")
        if content is None:
            raise ConversionError("not an OpenDocument text (no content.xml)")
        styles = read_part(self.archive, "styles.xml")
        self.read_fonts(styles)
        self.read_fonts(content)
        self.styles.add_from(styles)
        self.styles.add_from(content)
        default_text = self.styles.properties("paragraph", None, "text-properties")
        default_format = character_format(default_text, CharacterFormat(), self.fonts)
        if default_format.font:
            self.document.default_font = default_format.font
        if default_format.size_half_points:
            self.document.default_size_half_points = default_format.size_half_points
        body = content.find(f"{OFFICE}body/{OFFICE}text")
        if body is None:
            raise ConversionError("not an OpenDocument text (no office:text)")
        for element in body:
            self.block(element, "", None)
        if not self.document.paragraphs:
            self.document.paragraphs.append(Paragraph())
        return self.document

    def block(self, element, list_kind, list_style):
        if element.tag in (TEXT + "p", TEXT + "h"):
            self.document.paragraphs.append(self.paragraph(element, list_kind))
        elif element.tag == TEXT + "list":
            style = element.get(TEXT + "style-name") or list_style
            kind = self.styles.list_kinds.get(style, "bullet")
            for item in element:
                if item.tag in (TEXT + "list-item", TEXT + "list-header"):
                    for child in item:
                        self.block(child, kind, style)
        elif element.tag == TABLE + "table":
            self.report.lost("tables (cells become tab-separated paragraphs)")
            for row in element.iter(TABLE + "table-row"):
                merged = Paragraph()
                for cell_index, cell in enumerate(row.findall(TABLE + "table-cell")):
                    if cell_index:
                        merged.append_text("\t", CharacterFormat())
                    for paragraph_index, paragraph in enumerate(cell.iter(TEXT + "p")):
                        if paragraph_index:
                            merged.append_text(" ", CharacterFormat())
                        merged.runs.extend(self.paragraph(paragraph, "").runs)
                self.document.paragraphs.append(merged)
        elif element.tag in (TEXT + "section", TEXT + "index-body"):
            for child in element:
                self.block(child, list_kind, list_style)
        elif element.tag == TEXT + "table-of-content":
            body = element.find(TEXT + "index-body")
            if body is not None:
                self.block(body, list_kind, list_style)

    def paragraph(self, element, list_kind):
        paragraph = Paragraph(list_kind=list_kind)
        style = element.get(TEXT + "style-name")
        if element.tag == TEXT + "h":
            paragraph.heading_level = int(element.get(TEXT + "outline-level") or 1)
        else:
            level = self.styles.style_attribute("paragraph", style, STYLE + "default-outline-level")
            if level and level.isdigit():
                paragraph.heading_level = int(level)
        attributes = self.styles.properties("paragraph", style, "paragraph-properties")
        paragraph.alignment = ALIGNMENT_NAMES.get(attributes.get(FO + "text-align"), "left")
        paragraph.left_indent = length_twips(attributes.get(FO + "margin-left"))
        paragraph.right_indent = length_twips(attributes.get(FO + "margin-right"))
        paragraph.first_line_indent = length_twips(attributes.get(FO + "text-indent"))
        paragraph.space_before = length_twips(attributes.get(FO + "margin-top"))
        paragraph.space_after = length_twips(attributes.get(FO + "margin-bottom"))
        paragraph.page_break_before = attributes.get(FO + "break-before") == "page"
        for element_style in self.styles.chain("paragraph", style):
            stops = element_style.find(f"{STYLE}paragraph-properties/{STYLE}tab-stops")
            if stops is not None:
                paragraph.tab_stops = [length_twips(stop.get(STYLE + "position")) for stop in stops]
        base = character_format(self.styles.properties("paragraph", style, "text-properties"), CharacterFormat(), self.fonts)
        self.inline(element, paragraph, base)
        return paragraph

    def inline(self, element, paragraph, format):
        if element.text:
            paragraph.append_text(element.text, format)
        for child in element:
            if child.tag in (TEXT + "span",):
                attributes = self.styles.properties("text", child.get(TEXT + "style-name"), "text-properties")
                self.inline(child, paragraph, character_format(attributes, format, self.fonts))
            elif child.tag == TEXT + "s":
                paragraph.append_text(" " * int(child.get(TEXT + "c") or 1), format)
            elif child.tag == TEXT + "tab":
                paragraph.append_text("\t", format)
            elif child.tag == TEXT + "line-break":
                paragraph.append_text(LINE_BREAK, format)
            elif child.tag == DRAW + "frame":
                self.frame(child, paragraph, format)
            elif child.tag in (TEXT + "note", OFFICE + "annotation"):
                self.report.lost("notes and comments")
            elif child.tag in (TEXT + "a", TEXT + "meta", TEXT + "ruby", TEXT + "ruby-base"):
                self.inline(child, paragraph, format)
            elif child.tag in (TEXT + "bookmark", TEXT + "bookmark-start", TEXT + "bookmark-end", TEXT + "soft-page-break",
                               TEXT + "sequence-decls"):
                pass
            else:
                text = "".join(child.itertext())
                if text:
                    paragraph.append_text(text, format)
            if child.tail:
                paragraph.append_text(child.tail, format)

    def frame(self, element, paragraph, format):
        image = element.find(DRAW + "image")
        if image is None:
            self.report.lost("drawings and text frames")
            return
        try:
            bitmap = read_image(self.archive.read(image.get(XLINK + "href", "")))
        except (KeyError, ConversionError, ValueError):
            self.report.lost("pictures other than PNG and BMP")
            return
        width = length_twips(element.get(SVG + "width")) or bitmap.width * 15
        height = length_twips(element.get(SVG + "height")) or bitmap.height * 15
        paragraph.runs.append(Run("", format, Picture(bitmap, width, height)))


def read_odt(data, report):
    archive = open_package(data, TEXT_MIMETYPE, "ODT")
    with archive:
        return OdtReader(archive, report).read()


def text_properties(character, document, fonts):
    attributes = []
    if character.font and character.font != document.default_font:
        attributes.append(f'style:font-name="{quoted(fonts[character.font])}"')
    if character.bold:
        attributes.append('fo:font-weight="bold"')
    if character.italic:
        attributes.append('fo:font-style="italic"')
    if character.underline:
        attributes.append('style:text-underline-style="solid" style:text-underline-width="auto" '
                          'style:text-underline-color="font-color"')
    if character.strike:
        attributes.append('style:text-line-through-style="solid"')
    if character.superscript:
        attributes.append('style:text-position="super 58%"')
    elif character.subscript:
        attributes.append('style:text-position="sub 58%"')
    if character.size_half_points:
        attributes.append(f'fo:font-size="{character.size_half_points / 2:g}pt"')
    if character.colour is not None:
        attributes.append('fo:color="#%02x%02x%02x"' % character.colour)
    return " ".join(attributes)


def paragraph_properties(paragraph):
    attributes = []
    if paragraph.alignment != "left":
        attributes.append(f'fo:text-align="{ALIGNMENT_VALUES[paragraph.alignment]}"')
    for name, value in (("margin-left", paragraph.left_indent), ("margin-right", paragraph.right_indent),
                        ("text-indent", paragraph.first_line_indent), ("margin-top", paragraph.space_before),
                        ("margin-bottom", paragraph.space_after)):
        if value:
            attributes.append(f'fo:{name}="{twips_length(value)}"')
    if paragraph.page_break_before:
        attributes.append('fo:break-before="page"')
    stops = ""
    if paragraph.tab_stops:
        stops = "<style:tab-stops>" + "".join(f'<style:tab-stop style:position="{twips_length(stop)}"/>'
                                              for stop in paragraph.tab_stops) + "</style:tab-stops>"
    if not attributes and not stops:
        return ""
    if stops:
        return f'<style:paragraph-properties {" ".join(attributes)}>{stops}</style:paragraph-properties>'
    return f'<style:paragraph-properties {" ".join(attributes)}/>'


def text_content(text):
    pieces = []
    for match in re.finditer(r"\t|\n| {2,}|[^\t\n ]+| ", text):
        piece = match.group(0)
        if piece == "\t":
            pieces.append("<text:tab/>")
        elif piece == LINE_BREAK:
            pieces.append("<text:line-break/>")
        elif piece.startswith("  "):
            pieces.append(f' <text:s text:c="{len(piece) - 1}"/>')
        else:
            pieces.append(escape("".join(character for character in piece if ord(character) >= 32)))
    return "".join(pieces)


def font_faces(document):
    return {font: f"F{index}" for index, font in enumerate(document.fonts(), 1)}


def styles_xml(document, fonts):
    faces = "".join(f'<style:font-face style:name="{name}" svg:font-family="{quoted(font)}"/>' for font, name in fonts.items())
    headings = "".join(
        f'<style:style style:name="Heading_20_{level}" style:display-name="Heading {level}" style:family="paragraph" '
        f'style:parent-style-name="Standard" style:next-style-name="Standard" style:default-outline-level="{level}">'
        f'<style:text-properties fo:font-weight="bold" fo:font-size="{size}pt"/></style:style>'
        for level, size in {1: 16, 2: 14, 3: 13, 4: 12, 5: 11, 6: 11, 7: 10, 8: 10, 9: 10}.items())
    lists = ('<text:list-style style:name="ListBullet"><text:list-level-style-bullet text:level="1" text:bullet-char="•">'
             '<style:list-level-properties text:space-before="0.25in" text:min-label-width="0.25in"/>'
             '</text:list-level-style-bullet></text:list-style>'
             '<text:list-style style:name="ListNumber"><text:list-level-style-number text:level="1" style:num-suffix="." '
             'style:num-format="1"><style:list-level-properties text:space-before="0.25in" text:min-label-width="0.25in"/>'
             '</text:list-level-style-number></text:list-style>')
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<office:document-styles {NAMESPACE_DECLARATIONS}>'
            f"<office:font-face-decls>{faces}</office:font-face-decls><office:styles>"
            '<style:default-style style:family="paragraph">'
            f'<style:text-properties style:font-name="{fonts[document.default_font]}" '
            f'fo:font-size="{document.default_size_half_points / 2:g}pt"/></style:default-style>'
            '<style:style style:name="Standard" style:family="paragraph"/>'
            f"{headings}{lists}</office:styles></office:document-styles>")


def write_odt(document, report):
    fonts = font_faces(document)
    paragraph_styles = {}
    text_styles = {}
    images = []
    body = []
    open_list = ""

    def paragraph_style_name(paragraph):
        properties = paragraph_properties(paragraph)
        parent = f"Heading_20_{paragraph.heading_level}" if paragraph.heading_level else "Standard"
        if not properties:
            return parent
        key = (parent, properties)
        if key not in paragraph_styles:
            paragraph_styles[key] = f"P{len(paragraph_styles) + 1}"
        return paragraph_styles[key]

    def text_style_name(character):
        properties = text_properties(character, document, fonts)
        if not properties:
            return None
        if properties not in text_styles:
            text_styles[properties] = f"T{len(text_styles) + 1}"
        return text_styles[properties]

    for paragraph in document.paragraphs:
        if paragraph.list_kind != open_list:
            if open_list:
                body.append("</text:list>")
            if paragraph.list_kind:
                list_style = "ListNumber" if paragraph.list_kind == "number" else "ListBullet"
                body.append(f'<text:list text:style-name="{list_style}">')
            open_list = paragraph.list_kind
        content = []
        for run in paragraph.runs:
            if run.picture is not None:
                images.append(write_png(run.picture.bitmap))
                picture = run.picture
                width = picture.width_twips or picture.bitmap.width * 15
                height = picture.height_twips or picture.bitmap.height * 15
                content.append(f'<draw:frame draw:name="Picture {len(images)}" text:anchor-type="as-char" '
                               f'svg:width="{twips_length(width)}" svg:height="{twips_length(height)}">'
                               f'<draw:image xlink:href="Pictures/image{len(images)}.png" xlink:type="simple" '
                               'xlink:show="embed" xlink:actuate="onLoad"/></draw:frame>')
                continue
            text = text_content(run.text)
            style = text_style_name(run.format)
            content.append(f'<text:span text:style-name="{style}">{text}</text:span>' if style else text)
        style = paragraph_style_name(paragraph)
        if paragraph.heading_level:
            element = (f'<text:h text:style-name="{style}" text:outline-level="{paragraph.heading_level}">'
                       f'{"".join(content)}</text:h>')
        else:
            element = f'<text:p text:style-name="{style}">{"".join(content)}</text:p>'
        body.append(f"<text:list-item>{element}</text:list-item>" if open_list else element)
    if open_list:
        body.append("</text:list>")
    automatic = []
    for (parent, properties), name in paragraph_styles.items():
        automatic.append(f'<style:style style:name="{name}" style:family="paragraph" style:parent-style-name="{parent}">'
                         f"{properties}</style:style>")
    for properties, name in text_styles.items():
        automatic.append(f'<style:style style:name="{name}" style:family="text"><style:text-properties {properties}/>'
                         "</style:style>")
    faces = "".join(f'<style:font-face style:name="{name}" svg:font-family="{quoted(font)}"/>' for font, name in fonts.items())
    content_xml = (f'<?xml version="1.0" encoding="UTF-8"?>\n<office:document-content {NAMESPACE_DECLARATIONS}>'
                   f"<office:font-face-decls>{faces}</office:font-face-decls>"
                   f'<office:automatic-styles>{"".join(automatic)}</office:automatic-styles>'
                   f'<office:body><office:text>{"".join(body)}</office:text></office:body></office:document-content>')
    parts = {
        "content.xml": (content_xml, "text/xml"),
        "styles.xml": (styles_xml(document, fonts), "text/xml"),
    }
    for number, image in enumerate(images, 1):
        parts[f"Pictures/image{number}.png"] = (image, "image/png")
    return package(TEXT_MIMETYPE, parts)
