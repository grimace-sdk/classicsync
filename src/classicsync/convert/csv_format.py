import csv
import io
import re
from datetime import datetime

from .errors import ConversionError
from .formula import FormulaParser, tokenize_formula
from .text import decode_text
from .workbook import (EXCEL_EPOCH, ERROR_VALUES, Cell, CellError, CellStyle, Sheet, Workbook,
                       display_value)

NUMBER = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
DATE_FORMAT = "m/d/yy"
DATE_TIME_FORMAT = "m/d/yy h:mm"
TIME_FORMAT = "h:mm:ss"


def parse_moment(text):
    for pattern, number_format in (("%Y-%m-%d", DATE_FORMAT), ("%Y-%m-%d %H:%M:%S", DATE_TIME_FORMAT),
                                   ("%Y-%m-%d %H:%M", DATE_TIME_FORMAT), ("%H:%M:%S", TIME_FORMAT)):
        try:
            moment = datetime.strptime(text, pattern)
        except ValueError:
            continue
        if number_format == TIME_FORMAT:
            return (moment.hour * 3600 + moment.minute * 60 + moment.second) / 86400, number_format
        return (moment - EXCEL_EPOCH).total_seconds() / 86400, number_format
    return None


def parse_cell(text):
    stripped = text.strip()
    if NUMBER.match(stripped):
        return Cell(float(stripped))
    if stripped.endswith("%") and NUMBER.match(stripped[:-1]):
        return Cell(float(stripped[:-1]) / 100, style=CellStyle(number_format="0%"))
    moment = parse_moment(stripped)
    if moment:
        return Cell(moment[0], style=CellStyle(number_format=moment[1]))
    if text.upper() in ("TRUE", "FALSE"):
        return Cell(text.upper() == "TRUE")
    if text in ERROR_VALUES:
        return Cell(CellError(text))
    return Cell(text)


def is_formula(text):
    try:
        FormulaParser(tokenize_formula(text)).parse()
    except ConversionError:
        return False
    return True


def read_csv(data, report):
    text = decode_text(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    sheet = Sheet("Sheet1")
    for row_index, row in enumerate(csv.reader(io.StringIO(text), dialect)):
        for column_index, value in enumerate(row):
            if value == "":
                continue
            if value.startswith("=") and is_formula(value[1:]):
                sheet.cells[(row_index, column_index)] = Cell(value=None, formula=value[1:])
            else:
                sheet.cells[(row_index, column_index)] = parse_cell(value)
    return Workbook([sheet])


def write_csv(workbook, report, sheet_index=0):
    if len(workbook.sheets) > 1:
        populated = [sheet.name for sheet in workbook.sheets if sheet.cells]
        if len(populated) > 1 or (populated and populated[0] != workbook.sheets[sheet_index].name):
            report.lost(f"sheets other than {workbook.sheets[sheet_index].name!r} (CSV holds one sheet)")
    sheet = workbook.sheets[sheet_index]
    rows, columns = sheet.dimensions()
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\r\n")
    for row in range(rows):
        values = []
        for column in range(columns):
            cell = sheet.cells.get((row, column))
            values.append(display_value(cell) if cell else "")
        writer.writerow(values)
    if any(cell.formula for cell in sheet.cells.values()):
        report.lost("formulas (CSV keeps their last calculated values)")
    report.lost("cell formatting and column widths")
    return output.getvalue().encode("utf-8")
