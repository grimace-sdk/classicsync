import io
import struct
import zipfile
from pathlib import Path

import pytest

from classicsync.cli import main
from classicsync.convert import ConversionError, convert, formats_for, sniff_format
from classicsync.convert.bitmap import Bitmap, gray_level, read_bmp, read_png, write_2bp, write_bmp, write_png
from classicsync.convert.document import CharacterFormat, Document, Paragraph, Picture, Run
from classicsync.convert.errors import Report
from classicsync.convert.formula import FormulaContext, decode_formula, encode_formula, shift_formula
from classicsync.convert.pocket_excel import read_pocket_excel, write_pocket_excel
from classicsync.convert.rtf_reader import read_rtf
from classicsync.convert.rtf_writer import write_pocket_word
from classicsync.convert.workbook import Cell, CellError, CellStyle, DefinedName, Sheet, Workbook

MISC = Path(__file__).resolve().parents[2]
SAMPLE_FOLDERS = [MISC / "velo-emu-ce-2.0" / "build" / "donor" / "files", MISC / "velo-emu" / "rom" / "HC-4600" / "files"]
SAMPLE_WORD = [path for folder in SAMPLE_FOLDERS if folder.exists() for path in folder.glob("*.pwt")]
SAMPLE_EXCEL = [path for folder in SAMPLE_FOLDERS if folder.exists() for path in folder.glob("*.pxt")]

POCKET_WORD_1 = (
    b"{\\pwd1\\ansi\\deff0\\deftab720\\wrapw{\\fonttbl{\\f0\\fnil MS Sans Serif;}{\\f1\\fnil\\fcharset2 Symbol;}"
    b"{\\f2\\fswiss Arial;}}\r\n{\\colortbl\\red0\\green0\\blue0;}\r\n"
    b"{\\stylesheet{\\s1 \\b\\f2\\fs28 Heading 1;}}\r\n"
    b"\\pard\\s1\\plain\\f2\\fs28\\b Title\r\n\\par \\pard\\qc\\tx720\\plain\\f0\\fs20 Centred \\plain\\f0\\fs20\\i "
    b"slanted\\plain\\f0\\fs20 \\tab end\r\n"
    b"\\par \\pard\\li360\\fi-360 {\\pntext\\f1\\'b7\\tab}{\\*\\pn\\pnlvlblt\\pnf1{\\pntxtb\\'b7}}\\plain\\f0\\fs20 "
    b"Item caf\\'e9\r\n\\par }"
)


def picture_bitmap():
    rows = [[(0, 0, 0), (0x80, 0x80, 0x80), (0xC0, 0xC0, 0xC0), (255, 255, 255), (0, 0, 0)] for _ in range(3)]
    return Bitmap(5, 3, rows)


def sample_document():
    document = Document()
    heading = Paragraph(heading_level=1)
    heading.append_text("Heading", CharacterFormat(bold=True, size_half_points=28, font="Arial"))
    body = Paragraph(alignment="center", tab_stops=[720])
    body.append_text("Plain ", CharacterFormat())
    body.append_text("bold", CharacterFormat(bold=True))
    body.append_text(" and\ttabbed ", CharacterFormat())
    body.append_text("under", CharacterFormat(underline=True, italic=True))
    bullet = Paragraph(list_kind="bullet")
    bullet.append_text("Bullet é", CharacterFormat())
    picture = Paragraph(runs=[Run("", CharacterFormat(), Picture(picture_bitmap(), 75, 45))])
    document.paragraphs = [heading, body, bullet, picture]
    return document


def summary(document):
    lines = []
    for paragraph in document.paragraphs:
        runs = [(run.text, run.format.bold, run.format.italic, run.format.underline) for run in paragraph.runs
                if run.picture is None and run.text]
        pictures = [(run.picture.bitmap.width, run.picture.bitmap.height) for run in paragraph.runs if run.picture]
        lines.append((paragraph.alignment, paragraph.list_kind, paragraph.heading_level, runs, pictures))
    return lines


def test_reads_pocket_word_1():
    report = Report()
    document = read_rtf(POCKET_WORD_1, report)
    title, centred, item = document.paragraphs
    assert title.heading_level == 1 and title.runs[0].format.bold and title.runs[0].format.font == "Arial"
    assert centred.alignment == "center" and centred.tab_stops == [720]
    assert [(run.text, run.format.italic) for run in centred.runs] == [("Centred ", False), ("slanted", True),
                                                                        ("\tend", False)]
    assert item.list_kind == "bullet" and item.text() == "Item café" and item.left_indent == 360
    assert report.warnings == []


@pytest.mark.parametrize("version", [1, 2])
def test_pocket_word_round_trip(version):
    data = write_pocket_word(sample_document(), Report(), version)
    assert data.startswith(b"{\\pwd%d" % version)
    assert b"\\dibitmap0" in data and b"\\wbmbitspixel2" in data
    assert summary(read_rtf(data, Report())) == summary(sample_document())


@pytest.mark.parametrize("target", ["rtf", "html", "docx"])
def test_document_round_trip_through_desktop_formats(target):
    source = write_pocket_word(sample_document(), Report(), 2)
    desktop = convert(source, "pwd", target)
    back = convert(desktop.data, target, "pwd")
    assert summary(read_rtf(back.data, Report())) == summary(sample_document())


def test_text_conversion_keeps_paragraphs():
    result = convert("one\r\ntwo\r\n".encode(), "txt", "pwd", version=1)
    assert [paragraph.text() for paragraph in read_rtf(result.data, Report()).paragraphs] == ["one", "two"]
    assert convert(result.data, "pwd", "txt").data == b"one\ntwo\n"


def test_pocket_word_1_reports_losses():
    document = sample_document()
    document.paragraphs[1].runs[0].format = CharacterFormat(colour=(255, 0, 0))
    report = Report()
    write_pocket_word(document, report, 1)
    assert any("colour" in warning for warning in report.warnings)


@pytest.mark.parametrize("path", SAMPLE_WORD, ids=lambda path: path.name)
def test_sample_pocket_word_templates(path):
    document = read_rtf(path.read_bytes(), Report())
    assert any(paragraph.text().strip() for paragraph in document.paragraphs)
    docx = convert(path, target_format="docx").data
    assert "word/document.xml" in zipfile.ZipFile(io.BytesIO(docx)).namelist()


def formula_context(version):
    return FormulaContext(version == 2, ["Data", "Other Sheet"], ["Rate"])


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("text", [
    'IF(ISBLANK(B4),"",SUM(D4:L4))', "SUM(A1:A3)", "-A1^2+$B$2*3.5%", 'IF(A1>0,"yes")', "ROUND(PMT(Rate/12,360,-B4),2)",
    "'Other Sheet'!$C$3+Data!A1:B2", "AND(TRUE,NOT(FALSE))", "(A1+B1)/2", "CHOOSE(2,A1,B1,C1)", "#DIV/0!",
])
def test_formula_round_trip(text, version):
    context = formula_context(version)
    assert decode_formula(encode_formula(text, context), context) == text


def test_formula_encoding_matches_pocket_excel():
    context = FormulaContext(False)
    assert encode_formula("SUM(D5:L5)", context) == bytes.fromhex("2504c004c0030b19100000")
    encoded = encode_formula('IF(ISBLANK(B5),"",1)', context)
    assert encoded.startswith(bytes.fromhex("4404c001418100190206001700"))
    assert encoded.endswith(bytes.fromhex("42030100"))


def test_unsupported_function_is_reported():
    with pytest.raises(ConversionError):
        encode_formula("XLOOKUP(A1,B1:B3,C1:C3)", FormulaContext(True))


def test_shift_formula():
    assert shift_formula("SUM(A1:$B2)*C$3", 2, 1) == "SUM(B3:$B4)*D$3"


def sample_workbook():
    sheet = Sheet("Data", column_widths={0: 12.0, 2: 0.0}, row_heights={1: 20.0})
    sheet.cells = {
        (0, 0): Cell("Name", style=CellStyle(bold=True, alignment="center")),
        (0, 1): Cell(2.5, style=CellStyle(number_format="0.00%")),
        (1, 0): Cell(True),
        (1, 1): Cell(CellError("#N/A")),
        (2, 0): Cell(45000.0, style=CellStyle(number_format="m/d/yy")),
        (2, 1): Cell(5.0, formula="B1*2"),
        (3, 1): Cell("big", formula='IF(B3>1,"big","small")'),
        (4, 1): Cell(1.5, style=CellStyle(number_format="0.000", italic=True, font="Courier New", size_points=12)),
    }
    other = Sheet("Second")
    other.cells[(0, 0)] = Cell(7.0, formula="Data!B3+Rate")
    return Workbook([sheet, other], [DefinedName("Rate", "Data!$B$1")])


def workbook_summary(workbook):
    return [(sheet.name, sorted((key, cell.value, cell.formula, cell.style) for key, cell in sheet.cells.items()))
            for sheet in workbook.sheets]


@pytest.mark.parametrize("version", [1, 2])
def test_pocket_excel_round_trip(version):
    report = Report()
    data = write_pocket_excel(sample_workbook(), report, version)
    assert report.warnings == []
    workbook = read_pocket_excel(data, Report())
    assert workbook_summary(workbook) == workbook_summary(sample_workbook())
    assert workbook.names[0].formula == "Data!$B$1"
    assert workbook.sheets[0].column_widths[2] == 0.0
    assert abs(workbook.sheets[0].column_widths[0] - 12.0) < 0.2


def test_pocket_excel_version_markers():
    assert write_pocket_excel(sample_workbook(), Report(), 1)[:5] == bytes.fromhex("0909000500")
    assert write_pocket_excel(sample_workbook(), Report(), 2)[:5] == bytes.fromhex("090f010500")


def test_xlsx_round_trip():
    xlsx = convert(write_pocket_excel(sample_workbook(), Report(), 2), "pxl", "xlsx").data
    back = convert(xlsx, "xlsx", "pxl")
    assert workbook_summary(read_pocket_excel(back.data, Report())) == workbook_summary(sample_workbook())


def test_csv_conversion():
    result = convert(b"a,b\r\n1,=A2*2\r\n2026-01-02,50%\r\n==>,x\r\n", "csv", "pxl", version=1)
    sheet = read_pocket_excel(result.data, Report()).sheets[0]
    assert sheet.cells[(1, 1)].formula == "A2*2"
    assert sheet.cells[(2, 0)].style.number_format == "m/d/yy" and sheet.cells[(2, 1)].value == 0.5
    assert sheet.cells[(3, 0)].value == "==>"
    csv_back = convert(result.data, "pxl", "csv")
    assert csv_back.data.splitlines()[2] == b"2026-01-02,50%"
    assert any("formulas" in warning for warning in csv_back.warnings)


@pytest.mark.parametrize("path", SAMPLE_EXCEL, ids=lambda path: path.name)
def test_sample_pocket_excel_templates(path):
    workbook = read_pocket_excel(path.read_bytes(), Report())
    assert any(cell.formula for sheet in workbook.sheets for cell in sheet.cells.values())
    for version in (1, 2):
        again = read_pocket_excel(write_pocket_excel(workbook, Report(), version), Report())
        assert [(sheet.name, {key: cell.formula for key, cell in sheet.cells.items()}) for sheet in again.sheets] == \
            [(sheet.name, {key: cell.formula for key, cell in sheet.cells.items()}) for sheet in workbook.sheets]


def test_gray_levels_follow_2bp_dll():
    assert [gray_level(*colour) for colour in [(0, 0, 0), (0x80,) * 3, (0x55,) * 3, (0xAA,) * 3, (255,) * 3]] == \
        [0, 1, 1, 2, 3]
    assert gray_level(255, 0, 0) == 1 and gray_level(0, 255, 0) == 2 and gray_level(0xC0, 0xC0, 0xC0) == 2


def test_two_bit_bitmap_round_trip():
    bitmap = picture_bitmap()
    data = write_2bp(bitmap)
    assert struct.unpack_from("<H", data, 28)[0] == 2
    assert read_bmp(data).pixels == bitmap.pixels
    assert read_png(write_png(bitmap)).pixels == bitmap.pixels
    assert read_bmp(write_bmp(bitmap)).pixels == bitmap.pixels
    png = convert(data, "2bp", "png").data
    assert convert(png, "png", "2bp").data == data


def test_colour_png_is_reduced_to_two_bits():
    bitmap = Bitmap(2, 1, [[(255, 0, 0), (0, 255, 0)]])
    result = convert(write_png(bitmap), "png", "2bp")
    assert read_bmp(result.data).pixels == [[(0x80, 0x80, 0x80), (0xC0, 0xC0, 0xC0)]]
    assert result.warnings


def test_sniffing_and_targets():
    assert sniff_format(POCKET_WORD_1) == "pwd"
    assert sniff_format(write_pocket_excel(sample_workbook(), Report(), 1)) == "pxl"
    assert sniff_format(write_2bp(picture_bitmap())) == "2bp"
    assert set(formats_for(".pwt")) == {"rtf", "txt", "html", "docx"}
    assert set(formats_for("pxl")) == {"csv", "xlsx"}
    with pytest.raises(ConversionError):
        convert(b"plain", "txt", "xlsx")


def test_cli_convert(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("hello\nworld\n")
    assert main(["convert", str(source), str(tmp_path / "notes.pwd"), "--format-version", "1"]) == 0
    assert (tmp_path / "notes.pwd").read_bytes().startswith(b"{\\pwd1")
    assert main(["convert", str(tmp_path / "notes.pwd"), str(tmp_path / "notes.docx")]) == 0
    assert main(["convert", str(source), str(tmp_path / "notes.unknown")]) == 1
