import struct

from .errors import ConversionError
from .formula import FormulaContext, decode_formula, encode_formula
from .workbook import ERROR_CODES, ERROR_VALUES, Cell, CellError, CellStyle, DefinedName, Sheet, Workbook

BOF = 0x09
EOF = 0x0A
BLANK = 0x01
NUMBER = 0x03
LABEL = 0x04
BOOLERR = 0x05
FORMULA = 0x06
STRING = 0x07
ROW = 0x08
NAME = 0x18
SELECTION = 0x1D
FORMAT = 0x1E
DEFAULTROWHEIGHT = 0x25
FILEPASS = 0x2F
FONT = 0x31
WINDOW1 = 0x3D
WINDOW2 = 0x3E
PANE = 0x41
CODEPAGE = 0x42
DEFCOLWIDTH = 0x55
COLINFO = 0x7D
BOUNDSHEET = 0x85
COUNTRY = 0x8C
XF = 0xE0
DIMENSIONS = 0x00
SCL = 0xA0
FIXED_SIZES = {BOF: 4, EOF: 0, DIMENSIONS: 6, BLANK: 5, NUMBER: 13, BOOLERR: 7, ROW: 8, SELECTION: 9,
               DEFAULTROWHEIGHT: 4, WINDOW1: 4, PANE: 9, DEFCOLWIDTH: 6, XF: 22, SCL: 4, COUNTRY: 4, CODEPAGE: 2}
SUBSTREAM_GLOBALS = 0x0005
SUBSTREAM_WORKSHEET = 0x0010
VERSION_1 = 0x0009
VERSION_2 = 0x010F
FIRST_CUSTOM_FORMAT = 233
FIRST_CUSTOM_FORMAT_VERSION_1 = 40
ALIGNMENTS = {0: "general", 1: "left", 2: "center", 3: "right", 4: "fill", 5: "justify"}
ALIGNMENT_CODES = {name: code for code, name in ALIGNMENTS.items()}
COLUMN_WIDTH_UNITS = 256
PIXELS_PER_CHARACTER_VERSION_1 = 63 / 9
TWIPS_PER_POINT = 20
BUILTIN_FORMATS = [
    "General", "0.00", "0.00_);(0.00)", "#,##0.00", "#,##0.00_);(#,##0.00)", "#,##0", "#,##0_);(#,##0)", "0",
    "0_);(0)", '"$"#,##0.00', '"$"#,##0.00_);("$"#,##0.00)', '"$"#,##0', '"$"#,##0_);("$"#,##0)',
    '_("$"* #,##0.00_);_("$"* (#,##0.00);_("$"* "-"??_);_(@_)', '_(* #,##0.00_);_(* (#,##0.00);_(* "-"??_);_(@_)',
    '_("$"* #,##0_);_("$"* (#,##0);_("$"* "-"??_);_(@_)', '_(* #,##0_);_(* (#,##0);_(* "-"??_);_(@_)',
    "m/d", "m/d/yy", "mm/dd/yy", "d-mmm", "d-mmm-yy", "dd\\-mmm\\-yy", "mmm-yy", "mmmm\\-yy",
    "mmmm\\ d\\,\\ yyyy", "m/d/yy\\ h:mm\\ AM/PM", "m/d/yy h:mm", "h:mm AM/PM", "h:mm", "h:mm:ss AM/PM", "h:mm:ss",
    "0.00%", "0%", "# ?/?", "# ??/??", "#\\ ???/???", "0.00E+00", "0.E+00", "@", "mm:ss.0", "[h]:mm:ss",
    "ge.m.d", 'ggge"年"m"月"d"日"', 'yyyy"年"m"月"d"日"', 'yyyy"年"m"月"', 'm"月"d"日"', "yyyy/m/d",
    "yyyy/m/d h:mm AM/PM", "yyyy/m/d h:mm", 'h"時"mm"分"', 'h"時"mm"分"ss"秒"', "yy-mm-dd", "d.m", "d.m.yy",
    "dd.mm.yy", "d. mmm", "d. mmm yy", "dd. mmm yy", "mmm yy", "mmmm yy", "d. mmmm yyyy", "d.m.yy h:mm AM/PM",
    "d.m.yy h:mm", "dd mm yy", "d/m", "d/m/yy", "dd/mm/yy", "d mmmm yyyy", "d/m/yy h:mm AM/PM", "d/m/yy h:mm",
    "d \\d\\e mmmm \\d\\e yyyy", '"$"#,##0.00', '"$"#,##0.00_);("$"#,##0.00)', '"$"#,##0', '"$"#,##0_);("$"#,##0)',
    '_("$"* #,##0.00_);_("$"* (#,##0.00);_("$"* "-"??_);_(@_)', '_(* #,##0.00_);_(* (#,##0.00);_(* "-"??_);_(@_)',
    '_("$"* #,##0_);_("$"* (#,##0);_("$"* "-"??_);_(@_)', '_(* #,##0_);_(* (#,##0);_(* "-"??_);_(@_)',
]
LATER_BUILTIN_FORMATS = {
    120: "d-m", 121: "d-mm-yy", 122: "dd-mm-yy", 123: "d-mm-yy h:mm AM/PM", 124: "d-mm-yy h:mm", 125: "yyyy-mm-dd",
    126: "yyyy.mm.dd", 127: "mmmm yyyy", 128: "d/m yyyy", 129: "dd-mm-yy hh:mm", 130: "dd-mm-yy hh:mm:ss",
    131: "yyyy-mm-dd hh:mm", 132: "yyyy-mm-dd hh:mm:ss", 133: "dd.mm.yyyy", 134: "d.m.yyyy", 135: "dd/mm yyyy",
    136: "dd/mm yy", 137: "d/m yy", 138: "hh:mm", 139: "hh:mm:ss", 140: "hh:mm AM/PM", 141: "hh:mm:ss AM/PM",
    142: "dd/mm", 143: "dd/mm/yyyy h:mm AM/PM", 144: "dd/mm/yy hh:mm", 145: "yy-mm-dd hh:mm", 154: "yyyy",
    155: "mmmm", 158: "d/m/yyyy", 160: "dd/mm/yyyy", 174: "yyyy/mm/dd", 189: "d/mm", 190: "d/mm/yy",
    191: "d mmmm, yyyy", 192: "d mmmm yy", 193: "dd mmmm yy", 195: "d mmm yy", 196: "dd mmm yy",
    197: "dd/mm/yy h:mm AM/PM", 198: "dd/mm/yy h:mm", 211: "dd. mmm", 212: "d/mmm", 213: "mmm/yy",
    214: "dd/mmm/yy", 215: "dd/mmm", 223: '"US$"#,##0.00_);("US$"#,##0.00)', 224: "$#,##0_);[Red]($#,##0)",
    225: "$#,##0.00_);[Red]($#,##0.00)", 226: "#,##0_);[Red](#,##0)", 227: "#,##0.00_);[Red](#,##0.00)",
    228: "mm:ss", 229: "##0.0E+0",
}
FORMAT_INDEXES = {}
for format_index, format_text in list(enumerate(BUILTIN_FORMATS)) + list(LATER_BUILTIN_FORMATS.items()):
    FORMAT_INDEXES.setdefault(format_text, format_index)
VERSION_1_FORMAT_INDEXES = {index: index + 0x3F if 9 <= index <= 16 else index
                            for index in range(FIRST_CUSTOM_FORMAT_VERSION_1)}


def builtin_format(index):
    if index < len(BUILTIN_FORMATS):
        return BUILTIN_FORMATS[index]
    return LATER_BUILTIN_FORMATS.get(index, "General")


def record_length(record_type, data, position, version):
    unicode_strings = version >= 0x108
    character_size = 2 if unicode_strings else 1
    if record_type == WINDOW2:
        return 3 if version <= 0x10A else 5
    if record_type == COLINFO:
        return 6 if version < 0x10C else 9
    if record_type in FIXED_SIZES:
        return FIXED_SIZES[record_type]
    if record_type == LABEL:
        return 7 + data[position + 5] * character_size
    if record_type == FORMULA:
        return 16 + struct.unpack_from("<H", data, position + 14)[0]
    if record_type == STRING:
        return 2 + struct.unpack_from("<H", data, position)[0] * character_size
    if record_type == FORMAT:
        return 1 + data[position] * character_size
    if record_type == FONT:
        return 15 + data[position + 14] * character_size
    if record_type == BOUNDSHEET:
        return 2 + data[position + 1] * character_size
    if record_type == NAME:
        if version < 10:
            return 5 + data[position] * character_size + struct.unpack_from("<H", data, position + 1)[0]
        return 7 + data[position + 2] * character_size + struct.unpack_from("<H", data, position + 3)[0]
    if record_type == FILEPASS:
        raise ConversionError("password-protected Pocket Excel workbooks are not supported")
    raise ConversionError(f"unknown Pocket Excel record 0x{record_type:02x} at offset {position - 1}")


def iterate_records(data):
    if len(data) < 5 or data[0] != BOF:
        raise ConversionError("not a Pocket Excel workbook")
    version = struct.unpack_from("<H", data, 1)[0]
    if not VERSION_1 <= version <= VERSION_2:
        raise ConversionError(f"unsupported Pocket Excel version 0x{version:x}")
    position = 0
    while position < len(data):
        record_type = data[position]
        position += 1
        length = record_length(record_type, data, position, version)
        if position + length > len(data):
            raise ConversionError("Pocket Excel workbook is truncated")
        yield version, record_type, data[position:position + length]
        position += length


class PocketExcelReader:
    def __init__(self, report):
        self.report = report
        self.fonts = []
        self.custom_formats = []
        self.styles = []
        self.sheet_names = []
        self.name_records = []
        self.workbook = Workbook()
        self.version = VERSION_1

    def text(self, data, offset, length):
        if self.version >= 0x108:
            return data[offset:offset + length * 2].decode("utf-16-le", errors="replace")
        return data[offset:offset + length].decode("cp1252", errors="replace")

    def number_format(self, index):
        if self.version < 0x107 and index > 0x27:
            index += 0xC1
        if self.version < 10 and 9 <= index <= 16:
            index += 0x3F
        if index >= FIRST_CUSTOM_FORMAT:
            custom = index - FIRST_CUSTOM_FORMAT
            return self.custom_formats[custom] if custom < len(self.custom_formats) else "General"
        return builtin_format(index)

    def style(self, xf_index):
        return self.styles[xf_index] if xf_index < len(self.styles) else CellStyle()

    def read(self, data):
        sheet = None
        sheet_index = -1
        pending_string_cell = None
        for version, record_type, record in iterate_records(data):
            self.version = version
            if record_type == BOF:
                substream = struct.unpack_from("<H", record, 2)[0]
                if substream == SUBSTREAM_WORKSHEET:
                    sheet_index += 1
                    name = self.sheet_names[sheet_index] if sheet_index < len(self.sheet_names) else f"Sheet{sheet_index + 1}"
                    sheet = Sheet(name)
                    self.workbook.sheets.append(sheet)
            elif record_type == FONT:
                self.read_font(record)
            elif record_type == FORMAT:
                self.custom_formats.append(self.text(record, 1, record[0]))
            elif record_type == XF:
                self.read_xf(record)
            elif record_type == BOUNDSHEET:
                self.sheet_names.append(self.text(record, 2, record[1]))
            elif record_type == NAME:
                self.read_name(record)
            elif sheet is None:
                continue
            elif record_type == COLINFO:
                self.read_column_info(sheet, record)
            elif record_type == DEFCOLWIDTH:
                width = struct.unpack_from("<H", record, 2)[0]
                if version < 0x107:
                    width = width * 0x900 // 0x3F
                sheet.default_column_width = width / COLUMN_WIDTH_UNITS
            elif record_type == ROW:
                row, height, flags = struct.unpack_from("<HHH", record)
                if version < 0x107:
                    height = height * 255 // 17
                if flags & 0x02 or version < 0x107:
                    sheet.row_heights[row] = height / TWIPS_PER_POINT
            elif record_type in (BLANK, NUMBER, LABEL, BOOLERR, FORMULA):
                row, column, xf_index = struct.unpack_from("<HBH", record)
                cell = Cell(style=self.style(xf_index))
                if record_type == NUMBER:
                    cell.value = struct.unpack_from("<d", record, 5)[0]
                elif record_type == LABEL:
                    cell.value = self.text(record, 7, record[5])
                elif record_type == BOOLERR:
                    cell.value = CellError(ERROR_CODES.get(record[5], "#VALUE!")) if record[6] else bool(record[5])
                elif record_type == FORMULA:
                    pending_string_cell = self.read_formula(cell, record)
                sheet.cells[(row, column)] = cell
            elif record_type == STRING and pending_string_cell is not None:
                pending_string_cell.value = self.text(record, 2, struct.unpack_from("<H", record)[0])
                pending_string_cell = None
        self.resolve_names()
        if not self.workbook.sheets:
            self.workbook.sheets.append(Sheet("Sheet1"))
        return self.workbook

    def read_font(self, record):
        height, flags, _, weight = struct.unpack_from("<HHHH", record)
        underline = record[10]
        name = self.text(record, 15, record[14])
        self.fonts.append(CellStyle(bold=weight >= 600, italic=bool(flags & 0x02), underline=bool(underline),
                                    font=name, size_points=height / TWIPS_PER_POINT))

    def read_xf(self, record):
        if self.version < 0x109:
            font_index, _, format_index = struct.unpack_from("<HHH", record)
            text_attributes = struct.unpack_from("<H", record, 12)[0]
        else:
            font_index, format_index = struct.unpack_from("<HH", record)
            text_attributes = struct.unpack_from("<H", record, 10)[0]
        font = self.fonts[font_index] if font_index < len(self.fonts) else CellStyle()
        self.styles.append(font.changed(number_format=self.number_format(format_index),
                                        alignment=ALIGNMENTS.get(text_attributes & 0x07, "general"),
                                        wrap=bool(text_attributes & 0x08)))

    def read_column_info(self, sheet, record):
        if self.version < 0x10C:
            first_column, packed, _ = struct.unpack_from("<HHH", record)
            last_column = first_column
            width = packed & 0x3FFF
            hidden = bool(packed & 0x4000)
            if self.version < 0x107:
                width = width * 0x900 // 0x3F
        else:
            first_column, last_column, width, _, flags = struct.unpack_from("<HHHHB", record)
            hidden = bool(flags & 0x01)
        for column in range(first_column, last_column + 1):
            sheet.column_widths[column] = 0.0 if hidden else width / COLUMN_WIDTH_UNITS

    def formula_context(self):
        return FormulaContext(self.version >= 0x10D, self.sheet_names, [name for name, _, _ in self.name_records])

    def read_formula(self, cell, record):
        result = record[5:13]
        rgce = record[16:16 + struct.unpack_from("<H", record, 14)[0]]
        pending_string = None
        if result[6:8] == b"\xff\xff":
            kind = result[0]
            if kind == 0:
                cell.value = ""
                pending_string = cell
            elif kind == 1:
                cell.value = bool(result[2])
            elif kind == 2:
                cell.value = CellError(ERROR_CODES.get(result[2], "#VALUE!"))
            else:
                cell.value = ""
        else:
            cell.value = struct.unpack("<d", result)[0]
        try:
            cell.formula = decode_formula(rgce, self.formula_context())
        except (ConversionError, IndexError, struct.error) as error:
            self.report.lost(f"formulas that could not be decoded ({error}); their values are kept")
        return pending_string

    def read_name(self, record):
        if self.version < 10:
            length, definition_length, sheet = struct.unpack_from("<BHH", record)
            offset = 5
        else:
            _, length, definition_length, sheet = struct.unpack_from("<HBHH", record)
            offset = 7
        name = self.text(record, offset, length)
        character_size = 2 if self.version >= 0x108 else 1
        definition = record[offset + length * character_size:offset + length * character_size + definition_length]
        self.name_records.append((name, definition, sheet))

    def resolve_names(self):
        context = self.formula_context()
        for name, definition, sheet in self.name_records:
            try:
                formula = decode_formula(definition, context)
            except (ConversionError, IndexError, struct.error):
                self.report.lost(f"the definition of name {name}")
                continue
            local_sheet = sheet - 1 if 0 < sheet < 0xFFFF else None
            self.workbook.names.append(DefinedName(name, formula, local_sheet))


def read_pocket_excel(data, report):
    return PocketExcelReader(report).read(data)


class PocketExcelWriter:
    def __init__(self, workbook, report, version):
        self.workbook = workbook
        self.report = report
        self.version = version
        self.legacy = version == 1
        self.fonts = []
        self.custom_formats = []
        self.styles = []
        self.output = bytearray()
        names = [name.name for name in workbook.names]
        self.context = FormulaContext(not self.legacy, [sheet.name for sheet in workbook.sheets], names)
        self.style_index(CellStyle())

    def text_bytes(self, text, limit=255):
        if len(text) > limit:
            self.report.lost(f"text longer than {limit} characters (truncated)")
            text = text[:limit]
        if self.legacy:
            encoded = text.encode("cp1252", errors="replace")
            if encoded.decode("cp1252") != text:
                self.report.lost("characters outside Windows-1252 (Pocket Excel 1.0)")
            return encoded
        return text.encode("utf-16-le")

    def record(self, record_type, payload=b""):
        self.output.append(record_type)
        self.output.extend(payload)

    def font_index(self, style):
        key = (style.bold, style.italic, style.underline, style.font, style.size_points)
        if key not in self.fonts:
            self.fonts.append(key)
        return self.fonts.index(key)

    def format_index(self, number_format):
        if self.legacy:
            for legacy_index, modern_index in VERSION_1_FORMAT_INDEXES.items():
                if builtin_format(modern_index) == number_format:
                    return legacy_index
        elif number_format in FORMAT_INDEXES:
            return FORMAT_INDEXES[number_format]
        if number_format not in self.custom_formats:
            self.custom_formats.append(number_format)
        first = FIRST_CUSTOM_FORMAT_VERSION_1 if self.legacy else FIRST_CUSTOM_FORMAT
        return first + self.custom_formats.index(number_format)

    def style_index(self, style):
        key = (self.font_index(style), self.format_index(style.number_format), style.alignment, style.wrap)
        if key not in self.styles:
            self.styles.append(key)
        return self.styles.index(key)

    def globals(self):
        version_word = VERSION_1 if self.legacy else VERSION_2
        self.record(BOF, struct.pack("<HH", version_word, SUBSTREAM_GLOBALS))
        if not self.legacy:
            self.record(CODEPAGE, struct.pack("<H", 1252))
            self.record(COUNTRY, struct.pack("<HH", 1, 1))
            self.record(WINDOW1, struct.pack("<HH", 0, 0))
        for bold, italic, underline, font, size in self.fonts:
            name = self.text_bytes(font, 31)
            colour = 0 if self.legacy else 0xFF
            self.record(FONT, struct.pack("<HHHHHBBBBB", round(size * TWIPS_PER_POINT), 0x02 if italic else 0, colour,
                                          700 if bold else 400, 0, 1 if underline else 0, 0, 0, 0,
                                          len(name) // (1 if self.legacy else 2)) + name)
        for number_format in self.custom_formats:
            encoded = self.text_bytes(number_format)
            self.record(FORMAT, bytes((len(encoded) // (1 if self.legacy else 2),)) + encoded)
        for font_index, format_index, alignment, wrap in self.styles:
            text_attributes = ALIGNMENT_CODES.get(alignment, 0) | (0x08 if wrap else 0) | 0x30
            if self.legacy:
                payload = struct.pack("<HHHIHHHHHBB", font_index, 0, format_index, 0xFFFFFFFF, 0x0002,
                                      text_attributes, 0, 0, 0, 0, 0)
            else:
                payload = struct.pack("<HHIHHHHIH", font_index, format_index, 0xFFFFFFFF, 0x0002, text_attributes,
                                      0xFF, 0xFF, 0xFFFFFFFF, 0)
            self.record(XF, payload)
        for name in self.workbook.names:
            self.name_record(name)
        for sheet in self.workbook.sheets:
            encoded = self.text_bytes(sheet.name, 31)
            self.record(BOUNDSHEET, bytes((0, len(encoded) // (1 if self.legacy else 2))) + encoded)
        self.record(EOF)

    def name_record(self, name):
        try:
            definition = encode_formula(name.formula, self.context, reference_class=True)
        except ConversionError as error:
            self.report.lost(f"the definition of name {name.name} ({error})")
            definition = bytes((0x1C, ERROR_VALUES["#REF!"]))
        encoded = self.text_bytes(name.name, 255)
        length = len(encoded) // (1 if self.legacy else 2)
        sheet = name.sheet_index + 1 if name.sheet_index is not None else 0xFFFF
        if self.legacy:
            self.record(NAME, struct.pack("<BHH", length, len(definition), sheet) + encoded + definition)
        else:
            self.record(NAME, struct.pack("<HBHH", 0, length, len(definition), sheet) + encoded + definition)

    def sheet_records(self, sheet, cell_styles):
        version_word = VERSION_1 if self.legacy else VERSION_2
        self.record(BOF, struct.pack("<HH", version_word, SUBSTREAM_WORKSHEET))
        if not self.legacy:
            width = round(sheet.default_column_width * COLUMN_WIDTH_UNITS)
            self.record(DEFCOLWIDTH, struct.pack("<HHH", 0, width, 0))
        for column, width in sorted(sheet.column_widths.items()):
            if column > 0xFF:
                continue
            hidden = width == 0
            if self.legacy:
                pixels = round(width * PIXELS_PER_CHARACTER_VERSION_1)
                self.record(COLINFO, struct.pack("<HHH", column, (pixels & 0x3FFF) | (0x4000 if hidden else 0), 0))
            else:
                units = min(0xFFFF, round(width * COLUMN_WIDTH_UNITS))
                self.record(COLINFO, struct.pack("<HHHHB", column, column, units, 0, 0x03 if hidden else 0x02))
        if not self.legacy:
            self.record(DEFAULTROWHEIGHT, struct.pack("<HH", 0, 0xFF))
        for row, height in sorted(sheet.row_heights.items()):
            if self.legacy:
                self.record(ROW, struct.pack("<HHHH", row, round(height * TWIPS_PER_POINT * 17 / 255), 0, 0))
            else:
                self.record(ROW, struct.pack("<HHHH", row, round(height * TWIPS_PER_POINT), 0x02, 0))
        for (row, column), cell in sorted(sheet.cells.items()):
            if row > 0x3FFF or column > 0xFF:
                self.report.lost("cells beyond row 16384 or column IV")
                continue
            self.cell_record(row, column, cell, cell_styles[(sheet.name, row, column)])
        self.record(WINDOW2, struct.pack("<HB", 0, 0) if self.version <= 1 else struct.pack("<HBH", 0, 0, 0))
        self.record(SELECTION, struct.pack("<HBHBHB", 0, 0, 0, 0, 0, 0))
        self.record(EOF)

    def cell_record(self, row, column, cell, xf_index):
        header = struct.pack("<HBH", row, column, xf_index)
        value = cell.value
        if cell.formula:
            try:
                rgce = encode_formula(cell.formula, self.context)
            except ConversionError as error:
                self.report.lost(f"formulas Pocket Excel cannot hold ({error}); their values are kept")
            else:
                self.formula_record(header, value, rgce)
                return
        if value is None or value == "":
            self.record(BLANK, header)
        elif isinstance(value, bool):
            self.record(BOOLERR, header + bytes((int(value), 0)))
        elif isinstance(value, CellError):
            self.record(BOOLERR, header + bytes((ERROR_VALUES.get(value.text, 0x0F), 1)))
        elif isinstance(value, (int, float)):
            self.record(NUMBER, header + struct.pack("<d", float(value)))
        else:
            encoded = self.text_bytes(str(value))
            self.record(LABEL, header + bytes((len(encoded) // (1 if self.legacy else 2), 0)) + encoded)

    def formula_record(self, header, value, rgce):
        string_value = None
        if isinstance(value, bool):
            result = bytes((1, 0, int(value), 0, 0, 0)) + b"\xff\xff"
        elif isinstance(value, CellError):
            result = bytes((2, 0, ERROR_VALUES.get(value.text, 0x0F), 0, 0, 0)) + b"\xff\xff"
        elif isinstance(value, (int, float)):
            result = struct.pack("<d", float(value))
        elif value:
            result = bytes(6) + b"\xff\xff"
            string_value = str(value)
        else:
            result = bytes((0 if self.legacy else 3, 0, 0, 0, 0, 0)) + b"\xff\xff"
            if self.legacy:
                string_value = ""
        self.record(FORMULA, header + result + bytes((0x01,)) + struct.pack("<H", len(rgce)) + rgce)
        if string_value is not None:
            encoded = self.text_bytes(string_value)
            self.record(STRING, struct.pack("<H", len(encoded) // (1 if self.legacy else 2)) + encoded)

    def write(self):
        if not self.workbook.sheets:
            self.workbook.sheets.append(Sheet("Sheet1"))
        cell_styles = {}
        for sheet in self.workbook.sheets:
            for (row, column), cell in sheet.cells.items():
                cell_styles[(sheet.name, row, column)] = self.style_index(cell.style)
        self.globals()
        for sheet in self.workbook.sheets:
            self.sheet_records(sheet, cell_styles)
        return bytes(self.output)


def write_pocket_excel(workbook, report, version=2):
    if version not in (1, 2):
        raise ValueError("Pocket Excel version must be 1 or 2")
    return PocketExcelWriter(workbook, report, version).write()
