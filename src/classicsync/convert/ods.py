import re
from datetime import datetime, timedelta

from .errors import ConversionError
from .formula import quote_sheet, tokenize_formula
from .odt import (FO, NAMESPACE_DECLARATIONS, NUMBER_NAMESPACE, OFFICE, SPREADSHEET_MIMETYPE, STYLE, TABLE, TEXT, StyleSheet,
                  length_twips, open_package, package, quoted, read_part)
from .workbook import EXCEL_EPOCH, ERROR_VALUES, Cell, CellError, CellStyle, DefinedName, Sheet, Workbook, is_date_format

NUMBER = "{%s}" % NUMBER_NAMESPACE
CALCEXT_VALUE_TYPE = "{urn:org:documentfoundation:names:experimental:calc:xmlns:calcext:1.0}value-type"
NUMERIC_FORMAT = re.compile(r"^(#,##)?0(?:\.(0+))?(%)?$")
DATE_TOKENS = re.compile(r'yyyy|yy|mmmm|mmm|mm|m|dddd|ddd|dd|d|hh|h|ss|s|AM/PM|am/pm|"[^"]*"|\\.|.', re.IGNORECASE)
TIME_VALUE = re.compile(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?")
PIXELS_PER_CHARACTER = 7
CHARACTER_PADDING_PIXELS = 5
PIXELS_PER_INCH = 96
MAXIMUM_COLUMNS = 256
MAXIMUM_ROWS = 65536
ALIGNMENT_VALUES = {"left": "start", "center": "center", "right": "end", "justify": "justify", "fill": "start"}
ALIGNMENT_NAMES = {"start": "left", "left": "left", "center": "center", "end": "right", "right": "right",
                   "justify": "justify"}


def width_inches(characters):
    return (characters * PIXELS_PER_CHARACTER + CHARACTER_PADDING_PIXELS) / PIXELS_PER_INCH


def width_characters(inches):
    return round(max(0.0, (inches * PIXELS_PER_INCH - CHARACTER_PADDING_PIXELS) / PIXELS_PER_CHARACTER), 2)


def to_openformula(text):
    pieces = []
    for kind, value in tokenize_formula(text):
        if kind == "reference":
            sheet, _, cells = value.rpartition("!")
            parts = cells.split(":")
            first = f"{sheet}.{parts[0]}" if sheet else f".{parts[0]}"
            pieces.append("[" + ":".join([first] + [f".{part}" for part in parts[1:]]) + "]")
        elif kind == "function":
            pieces.append(value + "(")
        elif (kind, value) == ("operator", ","):
            pieces.append(";")
        elif kind == "name" and value.upper() in ("TRUE", "FALSE"):
            pieces.append(value.upper() + "()")
        else:
            pieces.append(value)
    return "of:=" + "".join(pieces)


def split_unquoted(text, separator):
    parts = []
    current = []
    quoted_text = False
    for character in text:
        if character == "'":
            quoted_text = not quoted_text
        if character == separator and not quoted_text:
            parts.append("".join(current))
            current = []
        else:
            current.append(character)
    parts.append("".join(current))
    return parts


def excel_reference(body):
    sheet = ""
    cells = []
    for part in split_unquoted(body, ":"):
        part_sheet, _, cell = part.rpartition(".") if not part.startswith("'") else (
            part[:part.rindex("'") + 1], ".", part[part.rindex("'") + 2:])
        part_sheet = part_sheet.lstrip("$")
        if part_sheet and not sheet:
            sheet = part_sheet if part_sheet.startswith("'") else quote_sheet(part_sheet)
        cells.append(cell)
    reference = ":".join(cells)
    return f"{sheet}!{reference}" if sheet else reference


def from_openformula(text):
    text = re.sub(r"^[A-Za-z]+:(?==)", "", text.strip())
    if text.startswith("="):
        text = text[1:]
    pieces = []
    position = 0
    while position < len(text):
        character = text[position]
        if character == '"':
            end = position + 1
            while end < len(text):
                if text[end] == '"' and text[end + 1:end + 2] == '"':
                    end += 2
                    continue
                if text[end] == '"':
                    break
                end += 1
            pieces.append(text[position:end + 1])
            position = end + 1
        elif character == "[":
            end = text.find("]", position)
            if end < 0:
                raise ConversionError(f"bad reference in formula {text!r}")
            pieces.append(excel_reference(text[position + 1:end]))
            position = end + 1
        elif character == ";":
            pieces.append(",")
            position += 1
        else:
            pieces.append(character)
            position += 1
    return "".join(pieces)


def date_tokens(code):
    tokens = [match.group(0) for match in DATE_TOKENS.finditer(code.split(";")[0])]
    parts = []
    for index, token in enumerate(tokens):
        lower = token.lower()
        if lower in ("m", "mm"):
            previous = next((parts[position][0] for position in range(len(parts) - 1, -1, -1) if parts[position][0] != "text"), "")
            following = next((other.lower() for other in tokens[index + 1:] if other.lower()[0] in "dmyhs"), "")
            if previous == "hours" or following.startswith("s"):
                parts.append(("minutes", lower == "mm"))
                continue
            parts.append(("month", lower == "mm"))
        elif lower in ("mmm", "mmmm"):
            parts.append(("month-textual", lower == "mmmm"))
        elif lower in ("d", "dd"):
            parts.append(("day", lower == "dd"))
        elif lower in ("ddd", "dddd"):
            parts.append(("day-of-week", lower == "dddd"))
        elif lower in ("yy", "yyyy"):
            parts.append(("year", lower == "yyyy"))
        elif lower in ("h", "hh"):
            parts.append(("hours", lower == "hh"))
        elif lower in ("s", "ss"):
            parts.append(("seconds", lower == "ss"))
        elif lower == "am/pm":
            parts.append(("am-pm", False))
        else:
            literal = token[1:-1] if token.startswith('"') else token[1:] if token.startswith("\\") else token
            if parts and parts[-1][0] == "text":
                parts[-1] = ("text", parts[-1][1] + literal)
            else:
                parts.append(("text", literal))
    return parts


def data_style_xml(name, code):
    match = NUMERIC_FORMAT.match(code)
    if match:
        grouping, decimals, percent = match.groups()
        places = len(decimals or "")
        number = (f'<number:number number:decimal-places="{places}" number:min-decimal-places="{places}" '
                  f'number:min-integer-digits="1"{" number:grouping=" + chr(34) + "true" + chr(34) if grouping else ""}/>')
        if percent:
            return f'<number:percentage-style style:name="{name}">{number}<number:text>%</number:text></number:percentage-style>'
        return f'<number:number-style style:name="{name}">{number}</number:number-style>'
    if not is_date_format(code):
        return None
    parts = date_tokens(code)
    elements = []
    for kind, value in parts:
        if kind == "text":
            elements.append(f"<number:text>{quoted(value)}</number:text>")
        elif kind == "month-textual":
            elements.append(f'<number:month number:textual="true"{" number:style=" + chr(34) + "long" + chr(34) if value else ""}/>')
        elif kind == "am-pm":
            elements.append("<number:am-pm/>")
        else:
            elements.append(f'<number:{kind}{" number:style=" + chr(34) + "long" + chr(34) if value else ""}/>')
    is_date = any(kind in ("day", "month", "month-textual", "year", "day-of-week") for kind, _ in parts)
    tag = "number:date-style" if is_date else "number:time-style"
    return f'<{tag} style:name="{name}">{"".join(elements)}</{tag}>'


def data_style_code(element):
    if element.tag in (NUMBER + "number-style", NUMBER + "percentage-style"):
        number = element.find(NUMBER + "number")
        if number is None:
            return "General"
        places = int(number.get(NUMBER + "decimal-places") or 0)
        code = ("#,##0" if number.get(NUMBER + "grouping") == "true" else "0") + ("." + "0" * places if places else "")
        return code + ("%" if element.tag == NUMBER + "percentage-style" else "")
    if element.tag not in (NUMBER + "date-style", NUMBER + "time-style"):
        return None
    pieces = []
    for child in element:
        long_style = child.get(NUMBER + "style") == "long"
        name = child.tag.replace(NUMBER, "")
        if name == "text":
            text = child.text or ""
            pieces.append(text if re.fullmatch(r"[-/:., ]*", text) else '"' + text.replace('"', "") + '"')
        elif name == "month":
            textual = child.get(NUMBER + "textual") == "true"
            pieces.append(("mmmm" if long_style else "mmm") if textual else ("mm" if long_style else "m"))
        elif name in ("day", "year", "hours", "minutes", "seconds"):
            short, long = {"day": ("d", "dd"), "year": ("yy", "yyyy"), "hours": ("h", "hh"), "minutes": ("mm", "mm"),
                           "seconds": ("ss", "ss")}[name]
            pieces.append(long if long_style else short)
        elif name == "day-of-week":
            pieces.append("dddd" if long_style else "ddd")
        elif name == "am-pm":
            pieces.append("AM/PM")
    return "".join(pieces) or "General"


def serial_from_date(text):
    text = text.strip()
    for pattern in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            moment = datetime.strptime(text, pattern)
        except ValueError:
            continue
        return (moment - EXCEL_EPOCH).total_seconds() / 86400
    raise ConversionError(f"bad date value {text!r}")


def serial_from_time(text):
    match = TIME_VALUE.fullmatch(text.strip().lstrip("-"))
    if not match:
        raise ConversionError(f"bad time value {text!r}")
    days, hours, minutes, seconds = match.groups()
    total = int(days or 0) * 86400 + int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds or 0)
    return total / 86400


def date_value(serial):
    moment = EXCEL_EPOCH + timedelta(days=serial)
    moment = moment.replace(microsecond=0) + timedelta(seconds=round(moment.microsecond / 1e6))
    return moment.strftime("%Y-%m-%dT%H:%M:%S")


def time_value(serial):
    seconds = round(serial * 86400)
    return f"PT{seconds // 3600:02d}H{seconds % 3600 // 60:02d}M{seconds % 60:02d}S"


def number_text(value):
    return repr(float(value)) if not float(value).is_integer() else str(int(value))


class OdsReader:
    def __init__(self, archive, report):
        self.archive = archive
        self.report = report
        self.styles = StyleSheet()
        self.data_styles = {}
        self.cell_styles = {}
        self.fonts = {}

    def read_data_styles(self, root):
        if root is None:
            return
        for container_name in ("styles", "automatic-styles"):
            for container in root.iter(OFFICE + container_name):
                for element in container:
                    code = data_style_code(element) if element.tag.startswith(NUMBER) else None
                    if code:
                        self.data_styles[element.get(STYLE + "name")] = code
        for face in root.iter(STYLE + "font-face"):
            family = face.get("{urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0}font-family")
            if family:
                self.fonts[face.get(STYLE + "name")] = family.strip("'\"")

    def cell_style(self, name):
        if name in self.cell_styles:
            return self.cell_styles[name]
        text = self.styles.properties("table-cell", name, "text-properties")
        paragraph = self.styles.properties("table-cell", name, "paragraph-properties")
        cell = self.styles.properties("table-cell", name, "table-cell-properties")
        style = CellStyle()
        if text.get(FO + "font-weight"):
            style = style.changed(bold=text[FO + "font-weight"] == "bold")
        if text.get(FO + "font-style"):
            style = style.changed(italic=text[FO + "font-style"] == "italic")
        if text.get(STYLE + "text-underline-style"):
            style = style.changed(underline=text[STYLE + "text-underline-style"] != "none")
        font = text.get(STYLE + "font-name")
        font = self.fonts.get(font, font) if font else text.get(FO + "font-family")
        if font:
            style = style.changed(font=font.strip("'\""))
        size = text.get(FO + "font-size")
        if size and not size.endswith("%"):
            style = style.changed(size_points=length_twips(size) / 20)
        alignment = paragraph.get(FO + "text-align")
        if alignment and self.styles.properties("table-cell", name, "table-cell-properties").get(
                STYLE + "text-align-source") != "value-type":
            style = style.changed(alignment=ALIGNMENT_NAMES.get(alignment, "general"))
        if cell.get(FO + "wrap-option") == "wrap":
            style = style.changed(wrap=True)
        data_style = self.styles.style_attribute("table-cell", name, STYLE + "data-style-name")
        if data_style in self.data_styles:
            style = style.changed(number_format=self.data_styles[data_style])
        elif data_style:
            self.report.lost("number formats other than plain numbers, percentages, dates and times")
        self.cell_styles[name] = style
        return style

    def read(self):
        content = read_part(self.archive, "content.xml")
        if content is None:
            raise ConversionError("not an OpenDocument spreadsheet (no content.xml)")
        styles = read_part(self.archive, "styles.xml")
        for root in (styles, content):
            self.styles.add_from(root)
            self.read_data_styles(root)
        spreadsheet = content.find(f"{OFFICE}body/{OFFICE}spreadsheet")
        if spreadsheet is None:
            raise ConversionError("not an OpenDocument spreadsheet (no office:spreadsheet)")
        workbook = Workbook()
        for table in spreadsheet.findall(TABLE + "table"):
            workbook.sheets.append(self.read_sheet(table, workbook, len(workbook.sheets)))
        names = spreadsheet.find(TABLE + "named-expressions")
        if names is not None:
            self.read_names(names, workbook, None)
        if not workbook.sheets:
            workbook.sheets.append(Sheet("Sheet1"))
        return workbook

    def read_names(self, container, workbook, sheet_index):
        for element in container:
            name = element.get(TABLE + "name")
            if element.tag == TABLE + "named-range":
                address = element.get(TABLE + "cell-range-address") or ""
                workbook.names.append(DefinedName(name, excel_reference(address), sheet_index))
            elif element.tag == TABLE + "named-expression":
                try:
                    formula = from_openformula(element.get(TABLE + "expression") or "")
                except ConversionError:
                    self.report.lost("named expressions that could not be translated")
                    continue
                workbook.names.append(DefinedName(name, formula, sheet_index))

    def column_elements(self, table):
        for element in table:
            if element.tag == TABLE + "table-column":
                yield element
            elif element.tag in (TABLE + "table-column-group", TABLE + "table-header-columns", TABLE + "table-columns"):
                yield from self.column_elements(element)

    def row_elements(self, table):
        for element in table:
            if element.tag == TABLE + "table-row":
                yield element
            elif element.tag in (TABLE + "table-row-group", TABLE + "table-header-rows", TABLE + "table-rows"):
                yield from self.row_elements(element)

    def read_sheet(self, table, workbook, sheet_index):
        sheet = Sheet(table.get(TABLE + "name") or f"Sheet{sheet_index + 1}")
        widths = []
        column_default_styles = []
        for column in self.column_elements(table):
            repeat = int(column.get(TABLE + "number-columns-repeated") or 1)
            repeat = min(repeat, MAXIMUM_COLUMNS - len(widths))
            if repeat <= 0:
                break
            hidden = column.get(TABLE + "visibility") in ("collapse", "filter")
            width = self.styles.properties("table-column", column.get(TABLE + "style-name"), "table-column-properties").get(
                STYLE + "column-width")
            value = 0.0 if hidden else (width_characters(length_twips(width) / 1440) if width else None)
            widths.extend([value] * repeat)
            column_default_styles.extend([column.get(TABLE + "default-cell-style-name")] * repeat)
        counted = {}
        for value in widths:
            if value is not None:
                counted[value] = counted.get(value, 0) + 1
        if counted:
            default = max(counted, key=counted.get)
            if default:
                sheet.default_column_width = default
            for index, value in enumerate(widths):
                if value is not None and value != default:
                    sheet.column_widths[index] = value
        row_index = 0
        for row in self.row_elements(table):
            repeat = int(row.get(TABLE + "number-rows-repeated") or 1)
            row_properties = self.styles.properties("table-row", row.get(TABLE + "style-name"), "table-row-properties")
            height = None
            if row_properties.get(STYLE + "use-optimal-row-height") == "false" and row_properties.get(STYLE + "row-height"):
                height = length_twips(row_properties[STYLE + "row-height"]) / 20
            cells = self.read_row(row, column_default_styles)
            if not cells and height is None:
                row_index += repeat
                continue
            for _ in range(min(repeat, MAXIMUM_ROWS - row_index)):
                if height is not None:
                    sheet.row_heights[row_index] = height
                for column, cell in cells.items():
                    sheet.cells[(row_index, column)] = cell
                row_index += 1
            if row_index >= MAXIMUM_ROWS:
                break
        local_names = table.find(TABLE + "named-expressions")
        if local_names is not None:
            self.read_names(local_names, workbook, sheet_index)
        return sheet

    def read_row(self, row, column_default_styles):
        cells = {}
        column = 0
        for element in row:
            if element.tag not in (TABLE + "table-cell", TABLE + "covered-table-cell"):
                continue
            repeat = int(element.get(TABLE + "number-columns-repeated") or 1)
            if element.get(TABLE + "number-columns-spanned", "1") != "1" or element.get(TABLE + "number-rows-spanned", "1") != "1":
                self.report.lost("merged cells")
            cell = None
            if element.tag == TABLE + "table-cell":
                default_style = column_default_styles[column] if column < len(column_default_styles) else None
                cell = self.read_cell(element, default_style)
            if cell is not None:
                for _ in range(min(repeat, MAXIMUM_COLUMNS - column)):
                    cells[column] = cell
                    column += 1
            else:
                column += repeat
            if column >= MAXIMUM_COLUMNS:
                break
        return cells

    def read_cell(self, element, default_style):
        style_name = element.get(TABLE + "style-name") or default_style
        style = self.cell_style(style_name) if style_name else CellStyle()
        value_type = element.get(OFFICE + "value-type")
        text = "\n".join("".join(paragraph.itertext()) for paragraph in element.findall(TEXT + "p"))
        formula = None
        if element.get(TABLE + "formula"):
            try:
                formula = from_openformula(element.get(TABLE + "formula"))
            except ConversionError:
                self.report.lost("formulas that could not be translated (their values are kept)")
        value = None
        error_result = element.get(CALCEXT_VALUE_TYPE) == "error" or formula or element.get(OFFICE + "string-value") == ""
        if text in ERROR_VALUES and error_result:
            value = CellError(text if text in ERROR_VALUES else "#VALUE!")
        elif value_type in ("float", "percentage", "currency"):
            value = float(element.get(OFFICE + "value") or 0)
        elif value_type == "date":
            value = serial_from_date(element.get(OFFICE + "date-value") or "")
        elif value_type == "time":
            value = serial_from_time(element.get(OFFICE + "time-value") or "")
        elif value_type == "boolean":
            value = (element.get(OFFICE + "boolean-value") or "").lower() == "true"
        elif value_type == "string":
            value = element.get(OFFICE + "string-value", text)
        elif text:
            value = text
        if value_type == "date" and not is_date_format(style.number_format):
            style = style.changed(number_format="m/d/yy" if value == int(value) else "m/d/yy h:mm")
        elif value_type == "time" and not is_date_format(style.number_format):
            style = style.changed(number_format="h:mm:ss")
        elif value_type == "percentage" and "%" not in style.number_format:
            style = style.changed(number_format="0%")
        if element.find(OFFICE + "annotation") is not None:
            self.report.lost("cell comments")
        if value is None and formula is None and style == CellStyle():
            return None
        return Cell(value, formula, style)


def read_ods(data, report):
    archive = open_package(data, SPREADSHEET_MIMETYPE, "ODS")
    with archive:
        return OdsReader(archive, report).read()


def cell_xml(cell, style_name):
    style = f' table:style-name="{style_name}"' if style_name else ""
    value = cell.value
    formula = ""
    if cell.formula:
        formula = f' table:formula="{quoted(to_openformula(cell.formula))}"'
    if isinstance(value, bool):
        return (f'<table:table-cell{style}{formula} office:value-type="boolean" office:boolean-value="{str(value).lower()}">'
                f"<text:p>{'TRUE' if value else 'FALSE'}</text:p></table:table-cell>")
    if isinstance(value, CellError):
        return (f'<table:table-cell{style}{formula} office:value-type="string" office:string-value="">'
                f"<text:p>{quoted(value.text)}</text:p></table:table-cell>")
    if isinstance(value, (int, float)):
        number_format = cell.style.number_format
        if is_date_format(number_format) and 0 <= value < 2958466:
            if value < 1 and not any(part in number_format.lower() for part in ("d", "y")):
                return f'<table:table-cell{style}{formula} office:value-type="time" office:time-value="{time_value(value)}"/>'
            return f'<table:table-cell{style}{formula} office:value-type="date" office:date-value="{date_value(value)}"/>'
        value_type = "percentage" if "%" in number_format else "float"
        return (f'<table:table-cell{style}{formula} office:value-type="{value_type}" office:value="{number_text(value)}">'
                f"<text:p>{number_text(value)}</text:p></table:table-cell>")
    if isinstance(value, str) and value != "":
        paragraphs = "".join(f"<text:p>{quoted(line)}</text:p>" for line in value.split("\n"))
        return f'<table:table-cell{style}{formula} office:value-type="string">{paragraphs}</table:table-cell>'
    return f"<table:table-cell{style}{formula}/>"


class OdsWriter:
    def __init__(self, workbook, report):
        self.workbook = workbook
        self.report = report
        self.cell_styles = {}
        self.data_styles = {}
        self.column_styles = {}
        self.row_styles = {}
        self.fonts = {}

    def font_name(self, font):
        if font not in self.fonts:
            self.fonts[font] = f"F{len(self.fonts) + 1}"
        return self.fonts[font]

    def data_style_name(self, number_format):
        if number_format == "General":
            return None
        if number_format not in self.data_styles:
            name = f"N{len(self.data_styles) + 1}"
            xml = data_style_xml(name, number_format)
            if xml is None:
                self.report.lost("number formats other than plain numbers, percentages, dates and times")
            self.data_styles[number_format] = (name, xml)
        name, xml = self.data_styles[number_format]
        return name if xml else None

    def cell_style_name(self, style):
        if style == CellStyle():
            return None
        if style not in self.cell_styles:
            self.cell_styles[style] = f"ce{len(self.cell_styles) + 1}"
        return self.cell_styles[style]

    def cell_style_xml(self, style, name):
        data_style = self.data_style_name(style.number_format)
        data = f' style:data-style-name="{data_style}"' if data_style else ""
        text = [f'style:font-name="{self.font_name(style.font)}"', f'fo:font-size="{style.size_points:g}pt"']
        if style.bold:
            text.append('fo:font-weight="bold"')
        if style.italic:
            text.append('fo:font-style="italic"')
        if style.underline:
            text.append('style:text-underline-style="solid" style:text-underline-width="auto" style:text-underline-color="font-color"')
        cell_properties = []
        if style.wrap:
            cell_properties.append('fo:wrap-option="wrap"')
        if style.alignment != "general":
            cell_properties.append('style:text-align-source="fix"')
        properties = f'<style:table-cell-properties {" ".join(cell_properties)}/>' if cell_properties else ""
        if style.alignment != "general":
            properties += f'<style:paragraph-properties fo:text-align="{ALIGNMENT_VALUES.get(style.alignment, "start")}"/>'
        return (f'<style:style style:name="{name}" style:family="table-cell" style:parent-style-name="Default"{data}>'
                f'{properties}<style:text-properties {" ".join(text)}/></style:style>')

    def column_style_name(self, width):
        key = round(width_inches(width), 4)
        if key not in self.column_styles:
            self.column_styles[key] = f"co{len(self.column_styles) + 1}"
        return self.column_styles[key]

    def row_style_name(self, height):
        if height not in self.row_styles:
            self.row_styles[height] = f"ro{len(self.row_styles) + 1}"
        return self.row_styles[height]

    def sheet_xml(self, sheet, sheet_index):
        parts = [f'<table:table table:name="{quoted(sheet.name)}">']
        rows, columns = sheet.dimensions()
        last_column = max([columns - 1, *sheet.column_widths]) if sheet.column_widths or columns else -1
        default_style = self.column_style_name(sheet.default_column_width)
        for column in range(last_column + 1):
            width = sheet.column_widths.get(column)
            if width == 0:
                parts.append(f'<table:table-column table:style-name="{default_style}" table:visibility="collapse"/>')
            else:
                style = self.column_style_name(width) if width is not None else default_style
                parts.append(f'<table:table-column table:style-name="{style}"/>')
        remaining = MAXIMUM_COLUMNS - (last_column + 1)
        if remaining > 0:
            parts.append(f'<table:table-column table:style-name="{default_style}" table:number-columns-repeated="{remaining}"/>')
        by_row = {}
        for (row, column), cell in sheet.cells.items():
            by_row.setdefault(row, {})[column] = cell
        next_row = 0
        for row in sorted(set(by_row) | set(sheet.row_heights)):
            if row > next_row:
                parts.append(f'<table:table-row table:number-rows-repeated="{row - next_row}"><table:table-cell/></table:table-row>')
            height = sheet.row_heights.get(row)
            row_style = f' table:style-name="{self.row_style_name(height)}"' if height is not None else ""
            cells = []
            next_column = 0
            for column, cell in sorted(by_row.get(row, {}).items()):
                if column > next_column:
                    cells.append(f'<table:table-cell table:number-columns-repeated="{column - next_column}"/>')
                cells.append(cell_xml(cell, self.cell_style_name(cell.style)))
                next_column = column + 1
            if not cells:
                cells.append("<table:table-cell/>")
            parts.append(f"<table:table-row{row_style}>{''.join(cells)}</table:table-row>")
            next_row = row + 1
        if not by_row and not sheet.row_heights:
            parts.append("<table:table-row><table:table-cell/></table:table-row>")
        local_names = [name for name in self.workbook.names if name.sheet_index == sheet_index]
        if local_names:
            parts.append(self.names_xml(local_names, sheet.name))
        parts.append("</table:table>")
        return "".join(parts)

    def names_xml(self, names, sheet_name):
        entries = []
        for name in names:
            try:
                expression = to_openformula(name.formula.lstrip("="))
            except ConversionError:
                self.report.lost(f"the name {name.name} (its formula could not be translated)")
                continue
            base = f"${quote_sheet(sheet_name)}.$A$1"
            entries.append(f'<table:named-expression table:name="{quoted(name.name)}" table:base-cell-address="{quoted(base)}" '
                           f'table:expression="{quoted(expression)}"/>')
        return f"<table:named-expressions>{''.join(entries)}</table:named-expressions>"

    def write(self):
        sheets = self.workbook.sheets or [Sheet("Sheet1")]
        self.font_name(CellStyle().font)
        tables = "".join(self.sheet_xml(sheet, index) for index, sheet in enumerate(sheets))
        global_names = [name for name in self.workbook.names if name.sheet_index is None]
        if global_names:
            tables += self.names_xml(global_names, sheets[0].name)
        automatic = []
        for width, name in self.column_styles.items():
            automatic.append(f'<style:style style:name="{name}" style:family="table-column">'
                             f'<style:table-column-properties style:column-width="{width:.4f}in"/></style:style>')
        for height, name in self.row_styles.items():
            automatic.append(f'<style:style style:name="{name}" style:family="table-row"><style:table-row-properties '
                             f'style:row-height="{height:g}pt" style:use-optimal-row-height="false"/></style:style>')
        cell_styles = [self.cell_style_xml(style, name) for style, name in self.cell_styles.items()]
        data_styles = [xml for _, xml in self.data_styles.values() if xml]
        automatic.extend(data_styles)
        automatic.extend(cell_styles)
        faces = "".join(f'<style:font-face style:name="{name}" svg:font-family="{quoted(font)}"/>' for font, name in self.fonts.items())
        default = CellStyle()
        content_xml = (f'<?xml version="1.0" encoding="UTF-8"?>\n<office:document-content {NAMESPACE_DECLARATIONS}>'
                       f"<office:font-face-decls>{faces}</office:font-face-decls>"
                       f'<office:automatic-styles>{"".join(automatic)}</office:automatic-styles>'
                       f"<office:body><office:spreadsheet>{tables}</office:spreadsheet></office:body></office:document-content>")
        styles_xml = (f'<?xml version="1.0" encoding="UTF-8"?>\n<office:document-styles {NAMESPACE_DECLARATIONS}>'
                      f"<office:font-face-decls>{faces}</office:font-face-decls><office:styles>"
                      '<style:default-style style:family="table-cell">'
                      f'<style:text-properties style:font-name="{self.fonts[default.font]}" fo:font-size="{default.size_points:g}pt"/>'
                      '</style:default-style><style:style style:name="Default" style:family="table-cell"/>'
                      "</office:styles></office:document-styles>")
        return package(SPREADSHEET_MIMETYPE, {"content.xml": (content_xml, "text/xml"), "styles.xml": (styles_xml, "text/xml")})


def write_ods(workbook, report):
    return OdsWriter(workbook, report).write()

