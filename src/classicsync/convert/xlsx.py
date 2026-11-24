import io
import posixpath
import re
import zipfile
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from .errors import ConversionError
from .formula import shift_formula
from .workbook import (Cell, CellError, CellStyle, DefinedName, Sheet, Workbook, column_letters,
                       column_number)

SPREADSHEET_NAMESPACE = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELATIONSHIP_NAMESPACE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_RELATIONSHIP_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/relationships"
S = "{%s}" % SPREADSHEET_NAMESPACE
R = "{%s}" % RELATIONSHIP_NAMESPACE
FIRST_CUSTOM_NUMBER_FORMAT = 164
BUILTIN_NUMBER_FORMATS = {
    0: "General", 1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00", 5: '"$"#,##0_);("$"#,##0)',
    6: '"$"#,##0_);[Red]("$"#,##0)', 7: '"$"#,##0.00_);("$"#,##0.00)', 8: '"$"#,##0.00_);[Red]("$"#,##0.00)',
    9: "0%", 10: "0.00%", 11: "0.00E+00", 12: "# ?/?", 13: "# ??/??", 14: "m/d/yy", 15: "d-mmm-yy", 16: "d-mmm",
    17: "mmm-yy", 18: "h:mm AM/PM", 19: "h:mm:ss AM/PM", 20: "h:mm", 21: "h:mm:ss", 22: "m/d/yy h:mm",
    37: "#,##0_);(#,##0)", 38: "#,##0_);[Red](#,##0)", 39: "#,##0.00_);(#,##0.00)", 40: "#,##0.00_);[Red](#,##0.00)",
    41: '_(* #,##0_);_(* (#,##0);_(* "-"_);_(@_)', 42: '_("$"* #,##0_);_("$"* (#,##0);_("$"* "-"_);_(@_)',
    43: '_(* #,##0.00_);_(* (#,##0.00);_(* "-"??_);_(@_)',
    44: '_("$"* #,##0.00_);_("$"* (#,##0.00);_("$"* "-"??_);_(@_)', 45: "mm:ss", 46: "[h]:mm:ss", 47: "mm:ss.0",
    48: "##0.0E+0", 49: "@",
}
BUILTIN_NUMBER_FORMAT_IDS = {text: identifier for identifier, text in BUILTIN_NUMBER_FORMATS.items()}
CELL_REFERENCE = re.compile(r"([A-Z]+)(\d+)")
CHARACTER_WIDTH_PADDING = 0.71


def attribute_flag(element, name):
    if element is None:
        return False
    return element.get("val", "1") not in ("0", "false")


class XlsxReader:
    def __init__(self, archive, report):
        self.archive = archive
        self.report = report
        self.shared_strings = []
        self.styles = []

    def xml(self, name):
        try:
            return ElementTree.fromstring(self.archive.read(name))
        except KeyError:
            return None

    def relationships(self, part):
        directory, name = posixpath.split(part)
        root = self.xml(posixpath.join(directory, "_rels", name + ".rels"))
        targets = {}
        if root is not None:
            for relationship in root:
                target = relationship.get("Target", "")
                if target.startswith("/"):
                    targets[relationship.get("Id")] = target.lstrip("/")
                else:
                    targets[relationship.get("Id")] = posixpath.normpath(posixpath.join(directory, target))
        return targets

    def read_shared_strings(self, part):
        root = self.xml(part)
        if root is None:
            return
        for item in root.findall(S + "si"):
            self.shared_strings.append("".join(text.text or "" for text in item.iter(S + "t")))

    def read_styles(self, part):
        root = self.xml(part)
        if root is None:
            return
        number_formats = dict(BUILTIN_NUMBER_FORMATS)
        formats = root.find(S + "numFmts")
        if formats is not None:
            for number_format in formats:
                number_formats[int(number_format.get("numFmtId"))] = number_format.get("formatCode")
        fonts = []
        fonts_element = root.find(S + "fonts")
        for font in (fonts_element if fonts_element is not None else []):
            name = font.find(S + "name")
            size = font.find(S + "sz")
            underline = font.find(S + "u")
            fonts.append(CellStyle(bold=attribute_flag(font.find(S + "b"), "b"),
                                   italic=attribute_flag(font.find(S + "i"), "i"),
                                   underline=underline is not None and underline.get("val") != "none",
                                   font=name.get("val") if name is not None else "Arial",
                                   size_points=float(size.get("val")) if size is not None else 10.0))
        cell_formats = root.find(S + "cellXfs")
        for cell_format in (cell_formats if cell_formats is not None else []):
            font_index = int(cell_format.get("fontId", 0))
            style = fonts[font_index] if font_index < len(fonts) else CellStyle()
            number_format = number_formats.get(int(cell_format.get("numFmtId", 0)), "General")
            alignment = cell_format.find(S + "alignment")
            horizontal = "general"
            wrap = False
            if alignment is not None:
                horizontal = alignment.get("horizontal", "general")
                if horizontal in ("centerContinuous", "distributed"):
                    horizontal = "center"
                wrap = alignment.get("wrapText") in ("1", "true")
            self.styles.append(style.changed(number_format=number_format, alignment=horizontal, wrap=wrap))

    def read(self):
        workbook_part = "xl/workbook.xml"
        package = self.relationships("")
        for target in package.values():
            if target.endswith("workbook.xml"):
                workbook_part = target
        root = self.xml(workbook_part)
        if root is None:
            raise ConversionError("not an Excel workbook (no xl/workbook.xml)")
        targets = self.relationships(workbook_part)
        for target in targets.values():
            if target.endswith("sharedStrings.xml"):
                self.read_shared_strings(target)
            elif target.endswith("styles.xml"):
                self.read_styles(target)
        workbook = Workbook()
        sheet_names = []
        for sheet_element in root.find(S + "sheets"):
            name = sheet_element.get("name")
            sheet_names.append(name)
            part = targets.get(sheet_element.get(R + "id"))
            sheet = Sheet(name)
            if part and part.endswith(".xml") and "worksheets" in part:
                self.read_sheet(part, sheet)
            else:
                self.report.lost(f"chart sheets and other non-worksheet sheets ({name})")
            workbook.sheets.append(sheet)
        names = root.find(S + "definedNames")
        for defined in (names if names is not None else []):
            name = defined.get("name")
            if name.startswith("_xlnm."):
                self.report.lost("print areas and other built-in names")
                continue
            local = defined.get("localSheetId")
            workbook.names.append(DefinedName(name, defined.text or "", int(local) if local is not None else None))
        if not workbook.sheets:
            workbook.sheets.append(Sheet("Sheet1"))
        return workbook

    def read_sheet(self, part, sheet):
        root = self.xml(part)
        if root is None:
            return
        format = root.find(S + "sheetFormatPr")
        if format is not None and format.get("defaultColWidth"):
            sheet.default_column_width = float(format.get("defaultColWidth")) - CHARACTER_WIDTH_PADDING
        columns = root.find(S + "cols")
        for column in (columns if columns is not None else []):
            hidden = column.get("hidden") in ("1", "true")
            width = 0.0 if hidden else max(0.0, float(column.get("width", sheet.default_column_width)) -
                                           CHARACTER_WIDTH_PADDING)
            for index in range(int(column.get("min")) - 1, min(int(column.get("max")), 256)):
                sheet.column_widths[index] = width
        shared_formulas = {}
        data = root.find(S + "sheetData")
        for row in (data if data is not None else []):
            if row.get("customHeight") in ("1", "true") and row.get("ht"):
                sheet.row_heights[int(row.get("r")) - 1] = float(row.get("ht"))
            for cell_element in row.findall(S + "c"):
                reference = CELL_REFERENCE.match(cell_element.get("r"))
                column = column_number(reference.group(1))
                row_index = int(reference.group(2)) - 1
                cell = self.read_cell(cell_element, row_index, column, shared_formulas)
                if cell is not None:
                    sheet.cells[(row_index, column)] = cell
        if root.find(S + "mergeCells") is not None:
            self.report.lost("merged cells")
        if root.find(S + "conditionalFormatting") is not None:
            self.report.lost("conditional formatting")

    def read_cell(self, element, row, column, shared_formulas):
        style_index = int(element.get("s", 0))
        style = self.styles[style_index] if style_index < len(self.styles) else CellStyle()
        cell_type = element.get("t", "n")
        value_element = element.find(S + "v")
        raw = value_element.text if value_element is not None else None
        value = None
        if cell_type == "s" and raw is not None:
            value = self.shared_strings[int(raw)]
        elif cell_type == "inlineStr":
            inline = element.find(S + "is")
            value = "".join(text.text or "" for text in inline.iter(S + "t")) if inline is not None else ""
        elif cell_type == "str":
            value = raw or ""
        elif cell_type == "b":
            value = raw == "1"
        elif cell_type == "e":
            value = CellError(raw or "#VALUE!")
        elif raw is not None:
            value = float(raw)
        formula = None
        formula_element = element.find(S + "f")
        if formula_element is not None:
            if formula_element.get("t") == "shared":
                identifier = formula_element.get("si")
                if formula_element.text:
                    shared_formulas[identifier] = (formula_element.text, row, column)
                    formula = formula_element.text
                elif identifier in shared_formulas:
                    text, base_row, base_column = shared_formulas[identifier]
                    try:
                        formula = shift_formula(text, row - base_row, column - base_column)
                    except ConversionError:
                        self.report.lost("shared formulas that could not be expanded")
            elif formula_element.get("t") == "array":
                self.report.lost("array formulas (their values are kept)")
            else:
                formula = formula_element.text
        if value is None and formula is None and style == CellStyle():
            return None
        return Cell(value, formula, style)


def read_xlsx(data, report):
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise ConversionError("not an XLSX file") from error
    with archive:
        return XlsxReader(archive, report).read()


def number_text(value):
    return repr(float(value)) if not float(value).is_integer() else str(int(value))


def cell_xml(reference, cell, style_index):
    style = f' s="{style_index}"' if style_index else ""
    value = cell.value
    formula = f"<f>{escape(cell.formula)}</f>" if cell.formula else ""
    if isinstance(value, bool):
        return f'<c r="{reference}"{style} t="b">{formula}<v>{int(value)}</v></c>'
    if isinstance(value, CellError):
        return f'<c r="{reference}"{style} t="e">{formula}<v>{escape(value.text)}</v></c>'
    if isinstance(value, (int, float)):
        return f'<c r="{reference}"{style}>{formula}<v>{number_text(value)}</v></c>'
    if isinstance(value, str) and value != "":
        if formula:
            return f'<c r="{reference}"{style} t="str">{formula}<v>{escape(value)}</v></c>'
        return f'<c r="{reference}"{style} t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>'
    if formula:
        return f'<c r="{reference}"{style}>{formula}</c>'
    return f'<c r="{reference}"{style}/>'


def sheet_xml(sheet, style_indexes):
    parts = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet xmlns="{SPREADSHEET_NAMESPACE}">',
             f'<sheetFormatPr defaultColWidth="{sheet.default_column_width + CHARACTER_WIDTH_PADDING:.2f}" '
             'defaultRowHeight="12.75"/>']
    if sheet.column_widths:
        columns = []
        for column, width in sorted(sheet.column_widths.items()):
            if width == 0:
                columns.append(f'<col min="{column + 1}" max="{column + 1}" width="0" hidden="1" customWidth="1"/>')
            else:
                columns.append(f'<col min="{column + 1}" max="{column + 1}" '
                               f'width="{width + CHARACTER_WIDTH_PADDING:.2f}" customWidth="1"/>')
        parts.append("<cols>" + "".join(columns) + "</cols>")
    parts.append("<sheetData>")
    rows = {}
    for (row, column), cell in sheet.cells.items():
        rows.setdefault(row, []).append((column, cell))
    for row in sorted(set(rows) | set(sheet.row_heights)):
        height = sheet.row_heights.get(row)
        height_attributes = f' ht="{height:g}" customHeight="1"' if height is not None else ""
        cells = "".join(cell_xml(f"{column_letters(column)}{row + 1}", cell, style_indexes[cell.style])
                        for column, cell in sorted(rows.get(row, [])))
        parts.append(f'<row r="{row + 1}"{height_attributes}>{cells}</row>')
    parts.append("</sheetData></worksheet>")
    return "".join(parts)


def styles_xml(styles):
    custom_formats = {}
    fonts = []
    cell_formats = []
    for style in styles:
        if style.number_format in BUILTIN_NUMBER_FORMAT_IDS:
            format_id = BUILTIN_NUMBER_FORMAT_IDS[style.number_format]
        else:
            format_id = custom_formats.setdefault(style.number_format,
                                                  FIRST_CUSTOM_NUMBER_FORMAT + len(custom_formats))
        font = (style.bold, style.italic, style.underline, style.font, style.size_points)
        if font not in fonts:
            fonts.append(font)
        alignment = ""
        if style.alignment != "general" or style.wrap:
            horizontal = f' horizontal="{style.alignment}"' if style.alignment != "general" else ""
            wrap = ' wrapText="1"' if style.wrap else ""
            alignment = f"<alignment{horizontal}{wrap}/>"
        apply = ' applyNumberFormat="1" applyFont="1"' + (' applyAlignment="1"' if alignment else "")
        cell_formats.append(f'<xf numFmtId="{format_id}" fontId="{fonts.index(font)}" fillId="0" borderId="0" '
                            f'xfId="0"{apply}>{alignment}</xf>')
    font_xml = []
    for bold, italic, underline, name, size in fonts:
        flags = ("<b/>" if bold else "") + ("<i/>" if italic else "") + ("<u/>" if underline else "")
        font_xml.append(f'<font>{flags}<sz val="{size:g}"/><name val="{escape(name, {chr(34): "&quot;"})}"/></font>')
    number_formats = "".join(f'<numFmt numFmtId="{identifier}" formatCode="{escape(code, {chr(34): "&quot;"})}"/>'
                             for code, identifier in custom_formats.items())
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<styleSheet xmlns="{SPREADSHEET_NAMESPACE}">'
            + (f'<numFmts count="{len(custom_formats)}">{number_formats}</numFmts>' if custom_formats else "")
            + f'<fonts count="{len(fonts)}">{"".join(font_xml)}</fonts>'
            '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            f'<cellXfs count="{len(cell_formats)}">{"".join(cell_formats)}</cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            "</styleSheet>")


def write_xlsx(workbook, report):
    styles = [CellStyle()]
    for sheet in workbook.sheets:
        for cell in sheet.cells.values():
            if cell.style not in styles:
                styles.append(cell.style)
    style_indexes = {style: index for index, style in enumerate(styles)}
    sheets = workbook.sheets or [Sheet("Sheet1")]
    sheet_entries = "".join(f'<sheet name="{escape(sheet.name, {chr(34): "&quot;"})}" sheetId="{index}" r:id="rId{index}"/>'
                            for index, sheet in enumerate(sheets, 1))
    defined_names = ""
    if workbook.names:
        entries = []
        for name in workbook.names:
            local = f' localSheetId="{name.sheet_index}"' if name.sheet_index is not None else ""
            entries.append(f'<definedName name="{escape(name.name)}"{local}>{escape(name.formula)}</definedName>')
        defined_names = "<definedNames>" + "".join(entries) + "</definedNames>"
    workbook_xml = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook xmlns="{SPREADSHEET_NAMESPACE}" '
                    f'xmlns:r="{RELATIONSHIP_NAMESPACE}"><sheets>{sheet_entries}</sheets>{defined_names}'
                    '<calcPr fullCalcOnLoad="1"/></workbook>')
    relationships = [f'<Relationship Id="rId{index}" Type="{RELATIONSHIP_NAMESPACE}/worksheet" '
                     f'Target="worksheets/sheet{index}.xml"/>' for index in range(1, len(sheets) + 1)]
    relationships.append(f'<Relationship Id="rIdStyles" Type="{RELATIONSHIP_NAMESPACE}/styles" Target="styles.xml"/>')
    workbook_relationships = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                              f'<Relationships xmlns="{PACKAGE_RELATIONSHIP_NAMESPACE}">{"".join(relationships)}</Relationships>')
    overrides = "".join(f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/'
                        'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                        for index in range(1, len(sheets) + 1))
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                     '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                     f"{overrides}</Types>")
    package_relationships = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                             f'<Relationships xmlns="{PACKAGE_RELATIONSHIP_NAMESPACE}"><Relationship Id="rId1" '
                             f'Type="{RELATIONSHIP_NAMESPACE}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", package_relationships)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_relationships)
        archive.writestr("xl/styles.xml", styles_xml(styles))
        for index, sheet in enumerate(sheets, 1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", sheet_xml(sheet, style_indexes))
    return output.getvalue()

