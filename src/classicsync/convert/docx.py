import io
import posixpath
import zipfile
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from .bitmap import read_image, write_png
from .document import LINE_BREAK, CharacterFormat, Document, Paragraph, Picture, Run
from .errors import ConversionError

WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
RELATIONSHIP_NAMESPACE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_RELATIONSHIP_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/relationships"
DRAWING_NAMESPACE = "http://schemas.openxmlformats.org/drawingml/2006/main"
EMU_PER_TWIP = 635
W = "{%s}" % WORD_NAMESPACE
R = "{%s}" % RELATIONSHIP_NAMESPACE
A = "{%s}" % DRAWING_NAMESPACE
ALIGNMENT_VALUES = {"left": "left", "center": "center", "right": "right", "justify": "both"}
ALIGNMENT_NAMES = {"left": "left", "start": "left", "center": "center", "right": "right", "end": "right",
                   "both": "justify", "distribute": "justify"}
BULLET_NUMBERING_ID = 1
DECIMAL_NUMBERING_ID = 2


def attribute(element, name):
    return element.get(W + name) if element is not None else None


def on_off(element):
    if element is None:
        return None
    return attribute(element, "val") not in ("0", "false", "off", "none")


class DocxReader:
    def __init__(self, archive, report):
        self.archive = archive
        self.report = report
        self.relationships = self.read_relationships("word/_rels/document.xml.rels")
        self.style_formats = {}
        self.style_levels = {}
        self.numbering_kinds = {}
        self.default_font = ""
        self.default_size = 0
        self.read_styles()
        self.read_numbering()

    def read_xml(self, name):
        try:
            return ElementTree.fromstring(self.archive.read(name))
        except KeyError:
            return None

    def read_relationships(self, name):
        root = self.read_xml(name)
        relationships = {}
        if root is not None:
            for relationship in root:
                target = relationship.get("Target", "")
                if relationship.get("TargetMode") != "External":
                    target = posixpath.normpath(posixpath.join("word", target)).lstrip("/")
                relationships[relationship.get("Id")] = target
        return relationships

    def read_styles(self):
        root = self.read_xml("word/styles.xml")
        if root is None:
            return
        defaults = root.find(f"{W}docDefaults/{W}rPrDefault/{W}rPr")
        if defaults is not None:
            fonts = defaults.find(f"{W}rFonts")
            self.default_font = attribute(fonts, "ascii") or ""
            size = defaults.find(f"{W}sz")
            if size is not None:
                self.default_size = int(attribute(size, "val"))
        for style in root.findall(f"{W}style"):
            identifier = attribute(style, "styleId")
            name_element = style.find(f"{W}name")
            name = (attribute(name_element, "val") or "").lower()
            level = 0
            if name.startswith("heading ") and name[8:].isdigit():
                level = int(name[8:])
            outline = style.find(f"{W}pPr/{W}outlineLvl")
            if outline is not None and not level:
                level = int(attribute(outline, "val")) + 1
            if level:
                self.style_levels[identifier] = level
            self.style_formats[identifier] = self.character_format(style.find(f"{W}rPr"), CharacterFormat())

    def read_numbering(self):
        root = self.read_xml("word/numbering.xml")
        if root is None:
            return
        abstract_kinds = {}
        for abstract in root.findall(f"{W}abstractNum"):
            level = abstract.find(f"{W}lvl")
            format = attribute(level.find(f"{W}numFmt"), "val") if level is not None else "bullet"
            abstract_kinds[attribute(abstract, "abstractNumId")] = "bullet" if format in ("bullet", "none") else "number"
        for numbering in root.findall(f"{W}num"):
            abstract_id = attribute(numbering.find(f"{W}abstractNumId"), "val")
            self.numbering_kinds[attribute(numbering, "numId")] = abstract_kinds.get(abstract_id, "bullet")

    def character_format(self, properties, base):
        if properties is None:
            return base
        format = base
        for tag, name in (("b", "bold"), ("i", "italic"), ("strike", "strike"), ("dstrike", "strike")):
            value = on_off(properties.find(W + tag))
            if value is not None:
                format = format.changed(**{name: value})
        underline = properties.find(f"{W}u")
        if underline is not None:
            format = format.changed(underline=attribute(underline, "val") != "none")
        fonts = properties.find(f"{W}rFonts")
        if fonts is not None and attribute(fonts, "ascii"):
            format = format.changed(font=attribute(fonts, "ascii"))
        size = properties.find(f"{W}sz")
        if size is not None:
            format = format.changed(size_half_points=int(float(attribute(size, "val"))))
        colour = attribute(properties.find(f"{W}color"), "val")
        if colour and len(colour) == 6 and colour.lower() != "auto":
            rgb = tuple(bytes.fromhex(colour))
            format = format.changed(colour=None if rgb == (0, 0, 0) else rgb)
        vertical = attribute(properties.find(f"{W}vertAlign"), "val")
        if vertical == "superscript":
            format = format.changed(superscript=True)
        elif vertical == "subscript":
            format = format.changed(subscript=True)
        return format

    def read(self):
        root = self.read_xml("word/document.xml")
        if root is None:
            raise ConversionError("not a Word document (no word/document.xml)")
        document = Document()
        if self.default_font:
            document.default_font = self.default_font
        if self.default_size:
            document.default_size_half_points = self.default_size
        body = root.find(f"{W}body")
        for element in body:
            self.block(element, document)
        if not document.paragraphs:
            document.paragraphs.append(Paragraph())
        return document

    def block(self, element, document):
        if element.tag == W + "p":
            document.paragraphs.append(self.paragraph(element))
        elif element.tag == W + "tbl":
            self.report.lost("tables (cells become tab-separated paragraphs)")
            for row in element.iter(W + "tr"):
                merged = Paragraph()
                for cell_index, cell in enumerate(row.findall(W + "tc")):
                    if cell_index:
                        merged.append_text("\t", CharacterFormat())
                    for paragraph_index, paragraph in enumerate(cell.findall(W + "p")):
                        if paragraph_index:
                            merged.append_text(" ", CharacterFormat())
                        merged.runs.extend(self.paragraph(paragraph).runs)
                document.paragraphs.append(merged)
        elif element.tag == W + "sdt":
            content = element.find(W + "sdtContent")
            if content is not None:
                for child in content:
                    self.block(child, document)

    def paragraph(self, element):
        paragraph = Paragraph()
        properties = element.find(W + "pPr")
        base_format = CharacterFormat()
        if properties is not None:
            style = attribute(properties.find(W + "pStyle"), "val")
            if style:
                paragraph.heading_level = self.style_levels.get(style, 0)
                base_format = self.style_formats.get(style, base_format)
            alignment = attribute(properties.find(W + "jc"), "val")
            paragraph.alignment = ALIGNMENT_NAMES.get(alignment, "left")
            indent = properties.find(W + "ind")
            if indent is not None:
                paragraph.left_indent = int(attribute(indent, "left") or attribute(indent, "start") or 0)
                paragraph.right_indent = int(attribute(indent, "right") or attribute(indent, "end") or 0)
                if attribute(indent, "hanging"):
                    paragraph.first_line_indent = -int(attribute(indent, "hanging"))
                elif attribute(indent, "firstLine"):
                    paragraph.first_line_indent = int(attribute(indent, "firstLine"))
            spacing = properties.find(W + "spacing")
            if spacing is not None:
                paragraph.space_before = int(attribute(spacing, "before") or 0)
                paragraph.space_after = int(attribute(spacing, "after") or 0)
            tabs = properties.find(W + "tabs")
            if tabs is not None:
                paragraph.tab_stops = [int(attribute(tab, "pos")) for tab in tabs.findall(W + "tab")
                                       if attribute(tab, "val") != "clear"]
            numbering = properties.find(W + "numPr")
            if numbering is not None:
                identifier = attribute(numbering.find(W + "numId"), "val")
                if identifier and identifier != "0":
                    paragraph.list_kind = self.numbering_kinds.get(identifier, "bullet")
            paragraph.page_break_before = bool(on_off(properties.find(W + "pageBreakBefore")))
        for child in element:
            if child.tag == W + "r":
                self.run(child, paragraph, base_format)
            elif child.tag in (W + "hyperlink", W + "ins", W + "smartTag", W + "fldSimple"):
                for run in child.iter(W + "r"):
                    self.run(run, paragraph, base_format)
        return paragraph

    def run(self, element, paragraph, base_format):
        format = self.character_format(element.find(W + "rPr"), base_format)
        for child in element:
            if child.tag == W + "t":
                paragraph.append_text(child.text or "", format)
            elif child.tag == W + "tab":
                paragraph.append_text("\t", format)
            elif child.tag in (W + "br", W + "cr"):
                if attribute(child, "type") == "page":
                    self.report.lost("page breaks inside paragraphs")
                paragraph.append_text(LINE_BREAK, format)
            elif child.tag == W + "drawing":
                self.drawing(child, paragraph, format)
            elif child.tag == W + "pict":
                self.report.lost("VML pictures")

    def drawing(self, element, paragraph, format):
        blip = element.find(f".//{A}blip")
        if blip is None:
            self.report.lost("drawings that are not pictures")
            return
        target = self.relationships.get(blip.get(R + "embed"))
        try:
            bitmap = read_image(self.archive.read(target))
        except (KeyError, ConversionError, ValueError):
            self.report.lost("pictures other than PNG and BMP")
            return
        extent = element.find(".//{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent")
        width = bitmap.width * 15
        height = bitmap.height * 15
        if extent is not None:
            width = int(extent.get("cx")) // EMU_PER_TWIP
            height = int(extent.get("cy")) // EMU_PER_TWIP
        paragraph.runs.append(Run("", format, Picture(bitmap, width, height)))


def read_docx(data, report):
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise ConversionError("not a DOCX file") from error
    with archive:
        return DocxReader(archive, report).read()


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="png" ContentType="image/png"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
</Types>"""

PACKAGE_RELATIONSHIPS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{PACKAGE_RELATIONSHIP_NAMESPACE}">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

NUMBERING = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="{WORD_NAMESPACE}">
<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="360" w:hanging="360"/></w:pPr></w:lvl></w:abstractNum>
<w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="360" w:hanging="360"/></w:pPr></w:lvl></w:abstractNum>
<w:num w:numId="{BULLET_NUMBERING_ID}"><w:abstractNumId w:val="0"/></w:num>
<w:num w:numId="{DECIMAL_NUMBERING_ID}"><w:abstractNumId w:val="1"/></w:num>
</w:numbering>"""


def styles_xml(document):
    font = escape(document.default_font, {'"': "&quot;"})
    heading_sizes = {1: 32, 2: 28, 3: 26, 4: 24, 5: 22, 6: 22, 7: 20, 8: 20, 9: 20}
    headings = "".join(
        f'<w:style w:type="paragraph" w:styleId="Heading{level}"><w:name w:val="heading {level}"/>'
        f'<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>'
        f'<w:pPr><w:keepNext/><w:outlineLvl w:val="{level - 1}"/></w:pPr>'
        f'<w:rPr><w:b/><w:sz w:val="{size}"/></w:rPr></w:style>'
        for level, size in heading_sizes.items())
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:styles xmlns:w="{WORD_NAMESPACE}">'
            f'<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:cs="{font}"/>'
            f'<w:sz w:val="{document.default_size_half_points}"/></w:rPr></w:rPrDefault></w:docDefaults>'
            '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
            f"{headings}</w:styles>")


def run_properties(character, document):
    properties = []
    if character.font and character.font != document.default_font:
        font = escape(character.font, {'"': "&quot;"})
        properties.append(f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:cs="{font}"/>')
    if character.bold:
        properties.append("<w:b/>")
    if character.italic:
        properties.append("<w:i/>")
    if character.strike:
        properties.append("<w:strike/>")
    if character.colour is not None:
        properties.append('<w:color w:val="%02X%02X%02X"/>' % character.colour)
    if character.size_half_points:
        properties.append(f'<w:sz w:val="{character.size_half_points}"/>')
    if character.underline:
        properties.append('<w:u w:val="single"/>')
    if character.superscript:
        properties.append('<w:vertAlign w:val="superscript"/>')
    elif character.subscript:
        properties.append('<w:vertAlign w:val="subscript"/>')
    return f"<w:rPr>{''.join(properties)}</w:rPr>" if properties else ""


def text_runs(text, properties):
    pieces = []
    buffer = []

    def flush():
        if buffer:
            pieces.append(f'<w:r>{properties}<w:t xml:space="preserve">{escape("".join(buffer))}</w:t></w:r>')
            buffer.clear()

    for character in text:
        if character == "\t":
            flush()
            pieces.append(f"<w:r>{properties}<w:tab/></w:r>")
        elif character == LINE_BREAK:
            flush()
            pieces.append(f"<w:r>{properties}<w:br/></w:r>")
        elif ord(character) >= 32 or character == "\t":
            buffer.append(character)
    flush()
    return "".join(pieces)


def drawing_run(identifier, relationship, picture):
    width = (picture.width_twips or picture.bitmap.width * 15) * EMU_PER_TWIP
    height = (picture.height_twips or picture.bitmap.height * 15) * EMU_PER_TWIP
    return (
        '<w:r><w:drawing><wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
        f'<wp:extent cx="{width}" cy="{height}"/><wp:docPr id="{identifier}" name="Picture {identifier}"/>'
        f'<a:graphic xmlns:a="{DRAWING_NAMESPACE}"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f'<pic:nvPicPr><pic:cNvPr id="{identifier}" name="image{identifier}.png"/><pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip xmlns:r="{RELATIONSHIP_NAMESPACE}" r:embed="{relationship}"/>'
        '<a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{width}" cy="{height}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>'
        "</wp:inline></w:drawing></w:r>")


def paragraph_properties(paragraph):
    properties = []
    if paragraph.heading_level:
        properties.append(f'<w:pStyle w:val="Heading{paragraph.heading_level}"/>')
    if paragraph.page_break_before:
        properties.append("<w:pageBreakBefore/>")
    if paragraph.list_kind:
        identifier = BULLET_NUMBERING_ID if paragraph.list_kind == "bullet" else DECIMAL_NUMBERING_ID
        properties.append(f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{identifier}"/></w:numPr>')
    if paragraph.tab_stops:
        stops = "".join(f'<w:tab w:val="left" w:pos="{stop}"/>' for stop in paragraph.tab_stops)
        properties.append(f"<w:tabs>{stops}</w:tabs>")
    if paragraph.space_before or paragraph.space_after:
        properties.append(f'<w:spacing w:before="{paragraph.space_before}" w:after="{paragraph.space_after}"/>')
    if paragraph.left_indent or paragraph.right_indent or paragraph.first_line_indent:
        indent = f'w:left="{paragraph.left_indent}" w:right="{paragraph.right_indent}"'
        if paragraph.first_line_indent < 0:
            indent += f' w:hanging="{-paragraph.first_line_indent}"'
        elif paragraph.first_line_indent:
            indent += f' w:firstLine="{paragraph.first_line_indent}"'
        properties.append(f"<w:ind {indent}/>")
    if paragraph.alignment != "left":
        properties.append(f'<w:jc w:val="{ALIGNMENT_VALUES[paragraph.alignment]}"/>')
    return f"<w:pPr>{''.join(properties)}</w:pPr>" if properties else ""


def write_docx(document, report):
    images = []
    body = []
    for paragraph in document.paragraphs:
        content = [paragraph_properties(paragraph)]
        for run in paragraph.runs:
            if run.picture is not None:
                images.append(write_png(run.picture.bitmap))
                content.append(drawing_run(len(images), f"rIdImage{len(images)}", run.picture))
            else:
                content.append(text_runs(run.text, run_properties(run.format, document)))
        body.append(f"<w:p>{''.join(content)}</w:p>")
    document_xml = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document xmlns:w="{WORD_NAMESPACE}" '
                    f'xmlns:r="{RELATIONSHIP_NAMESPACE}"><w:body>{"".join(body)}'
                    '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
                    '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>'
                    "</w:sectPr></w:body></w:document>")
    relationships = [
        '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>',
        '<Relationship Id="rIdNumbering" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>',
    ]
    for number in range(1, len(images) + 1):
        relationships.append(f'<Relationship Id="rIdImage{number}" Type="http://schemas.openxmlformats.org/officeDocument/'
                             f'2006/relationships/image" Target="media/image{number}.png"/>')
    document_relationships = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                              f'<Relationships xmlns="{PACKAGE_RELATIONSHIP_NAMESPACE}">{"".join(relationships)}</Relationships>')
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", PACKAGE_RELATIONSHIPS)
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/styles.xml", styles_xml(document))
        archive.writestr("word/numbering.xml", NUMBERING)
        archive.writestr("word/_rels/document.xml.rels", document_relationships)
        for number, image in enumerate(images, 1):
            archive.writestr(f"word/media/image{number}.png", image)
    return output.getvalue()
