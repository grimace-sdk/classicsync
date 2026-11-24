import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

ERROR_CODES = {0x00: "#NULL!", 0x07: "#DIV/0!", 0x0F: "#VALUE!", 0x17: "#REF!", 0x1D: "#NAME?", 0x24: "#NUM!",
               0x2A: "#N/A"}
ERROR_VALUES = {text: code for code, text in ERROR_CODES.items()}
EXCEL_EPOCH = datetime(1899, 12, 30)
QUOTED_OR_ESCAPED = re.compile(r'"[^"]*"|\\.|\[[^\]]*\]')
DEFAULT_COLUMN_WIDTH = 9.0


@dataclass(frozen=True)
class CellError:
    text: str


@dataclass(frozen=True)
class CellStyle:
    number_format: str = "General"
    bold: bool = False
    italic: bool = False
    underline: bool = False
    font: str = "Arial"
    size_points: float = 10.0
    alignment: str = "general"
    wrap: bool = False

    def changed(self, **changes):
        return replace(self, **changes)


@dataclass
class Cell:
    value: object = None
    formula: str = None
    style: CellStyle = field(default_factory=CellStyle)


@dataclass
class Sheet:
    name: str
    cells: dict = field(default_factory=dict)
    column_widths: dict = field(default_factory=dict)
    row_heights: dict = field(default_factory=dict)
    default_column_width: float = DEFAULT_COLUMN_WIDTH

    def dimensions(self):
        if not self.cells:
            return 0, 0
        return max(row for row, _ in self.cells) + 1, max(column for _, column in self.cells) + 1


@dataclass
class DefinedName:
    name: str
    formula: str
    sheet_index: int = None


@dataclass
class Workbook:
    sheets: list = field(default_factory=list)
    names: list = field(default_factory=list)


def column_letters(column):
    letters = ""
    column += 1
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def column_number(letters):
    number = 0
    for letter in letters.upper():
        number = number * 26 + ord(letter) - 64
    return number - 1


def is_date_format(number_format):
    stripped = QUOTED_OR_ESCAPED.sub("", number_format.split(";")[0]).lower()
    return any(token in stripped for token in ("d", "m", "y", "h", "s")) and "general" not in stripped


def serial_to_datetime(serial):
    return EXCEL_EPOCH + timedelta(days=serial)


def display_value(cell):
    value = cell.value
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, CellError):
        return value.text
    if isinstance(value, float):
        if is_date_format(cell.style.number_format) and 0 <= value < 2958466:
            moment = serial_to_datetime(value)
            if value < 1:
                return moment.strftime("%H:%M:%S")
            if moment.hour or moment.minute or moment.second:
                return moment.strftime("%Y-%m-%d %H:%M:%S")
            return moment.strftime("%Y-%m-%d")
        if "%" in cell.style.number_format:
            return f"{value * 100:g}%"
        return f"{int(value)}" if value.is_integer() and abs(value) < 1e15 else repr(value)
    return "" if value is None else str(value)
