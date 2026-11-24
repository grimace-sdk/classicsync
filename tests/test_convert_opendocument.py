import io
import zipfile

import pytest
from test_convert import sample_document, sample_workbook, summary, workbook_summary

from classicsync.convert import ConversionError, convert, sniff_format
from classicsync.convert.document import CharacterFormat, Document, Paragraph
from classicsync.convert.errors import Report
from classicsync.convert.ods import from_openformula, read_ods, to_openformula, write_ods
from classicsync.convert.odt import read_odt, write_odt
from classicsync.convert.pocket_excel import read_pocket_excel, write_pocket_excel
from classicsync.convert.rtf_reader import read_rtf
from classicsync.convert.rtf_writer import write_pocket_word
from classicsync.convert.workbook import Cell, CellStyle, Sheet, Workbook

LIBREOFFICE_TEXT = b"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
 xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0">
<office:automatic-styles>
<style:style style:name="P1" style:family="paragraph" style:parent-style-name="Standard">
<style:paragraph-properties fo:text-align="center" fo:margin-left="0.5in"/></style:style>
<style:style style:name="T1" style:family="text"><style:text-properties fo:font-weight="bold" fo:color="#ff0000"/></style:style>
<style:style style:name="T2" style:family="text"><style:text-properties style:text-position="33% 58%"/></style:style>
<text:list-style style:name="L1"><text:list-level-style-number text:level="1"/></text:list-style>
</office:automatic-styles>
<office:body><office:text>
<text:h text:outline-level="2">Title</text:h>
<text:p text:style-name="P1">Hello <text:span text:style-name="T1">red</text:span><text:s text:c="2"/>x<text:span text:style-name="T2">2</text:span></text:p>
<text:list text:style-name="L1"><text:list-item><text:p>First</text:p></text:list-item>
<text:list-item><text:p>Second</text:p></text:list-item></text:list>
</office:text></office:body></office:document-content>"""


def package(mimetype, content):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("mimetype", mimetype)
        archive.writestr("content.xml", content)
    return output.getvalue()


def test_odt_round_trip():
    report = Report()
    data = write_odt(sample_document(), report)
    assert report.warnings == []
    assert sniff_format(data) == "odt"
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        first = archive.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
    document = read_odt(data, Report())
    assert summary(document) == summary(sample_document())
    assert document.paragraphs[1].tab_stops == [720]
    assert document.paragraphs[0].runs[0].format.font == "Arial"


def test_odt_keeps_spacing_and_indents():
    paragraph = Paragraph(left_indent=720, first_line_indent=-360, space_after=120, page_break_before=True)
    paragraph.append_text("a  b\nc", CharacterFormat(strike=True, superscript=True, colour=(0, 0, 255), size_half_points=24))
    document = read_odt(write_odt(Document([paragraph], "Tahoma", 18), Report()), Report())
    read = document.paragraphs[0]
    assert (read.left_indent, read.first_line_indent, read.space_after, read.page_break_before) == (720, -360, 120, True)
    assert read.runs[0].text == "a  b\nc"
    character = read.runs[0].format
    assert (character.strike, character.superscript, character.colour, character.size_half_points) == (True, True, (0, 0, 255), 24)
    assert (document.default_font, document.default_size_half_points) == ("Tahoma", 18)


def test_odt_reads_libreoffice_style_markup():
    document = read_odt(package("application/vnd.oasis.opendocument.text", LIBREOFFICE_TEXT), Report())
    title, body, first, second = document.paragraphs
    assert title.heading_level == 2 and title.text() == "Title"
    assert body.alignment == "center" and body.left_indent == 720
    assert body.text() == "Hello red  x2"
    assert body.runs[1].format.bold and body.runs[1].format.colour == (255, 0, 0)
    assert body.runs[-1].format.superscript
    assert (first.list_kind, second.list_kind, second.text()) == ("number", "number", "Second")


def test_odt_through_pocket_word():
    source = write_pocket_word(sample_document(), Report(), 2)
    back = convert(convert(source, "pwd", "odt").data, "odt", "pwd")
    assert summary(read_rtf(back.data, Report())) == summary(sample_document())


def test_wrong_package_is_rejected():
    with pytest.raises(ConversionError):
        read_odt(package("application/vnd.oasis.opendocument.spreadsheet", LIBREOFFICE_TEXT), Report())
    with pytest.raises(ConversionError):
        read_ods(b"not a zip", Report())


@pytest.mark.parametrize("excel, openformula", [
    ("SUM(A1:$B$2)*2", "of:=SUM([.A1:.$B$2])*2"),
    ("Data!B3+Rate", "of:=[Data.B3]+Rate"),
    ("'My Sheet'!A1:B2", "of:=['My Sheet'.A1:.B2]"),
    ('IF(B3>1,"a;b",TRUE)', 'of:=IF([.B3]>1;"a;b";TRUE())'),
    ("-A1%&\"x\"", "of:=-[.A1]%&\"x\""),
])
def test_formula_translation(excel, openformula):
    assert to_openformula(excel) == openformula
    assert from_openformula(openformula).replace("TRUE()", "TRUE") == excel


def test_formula_from_libreoffice():
    assert from_openformula("of:=SUM([$Sheet2.A1:.B3];[.C1])") == "SUM(Sheet2!A1:B3,C1)"
    assert from_openformula("of:=[$'Other one'.$A$1]") == "'Other one'!$A$1"


def test_ods_round_trip():
    report = Report()
    data = write_ods(sample_workbook(), report)
    assert report.warnings == []
    assert sniff_format(data) == "ods"
    workbook = read_ods(data, Report())
    assert workbook_summary(workbook) == workbook_summary(sample_workbook())
    sheet = workbook.sheets[0]
    assert sheet.column_widths[2] == 0.0
    assert abs(sheet.column_widths[0] - 12.0) < 0.2
    assert sheet.row_heights == {1: 20.0}
    assert [(name.name, name.formula) for name in workbook.names] == [("Rate", "Data!$B$1")]


def test_ods_through_pocket_excel():
    ods = convert(write_pocket_excel(sample_workbook(), Report(), 2), "pxl", "ods").data
    back = convert(ods, "ods", "pxl")
    assert workbook_summary(read_pocket_excel(back.data, Report())) == workbook_summary(sample_workbook())


def test_ods_number_formats():
    formats = ["0", "#,##0.00", "0%", "m/d/yy", "d-mmm-yy", "h:mm:ss", "m/d/yy h:mm", "dddd mmmm d yyyy"]
    sheet = Sheet("Formats")
    for row, number_format in enumerate(formats):
        sheet.cells[(row, 0)] = Cell(45000.25 if "d" in number_format else 0.5, style=CellStyle(number_format=number_format))
    workbook = read_ods(write_ods(Workbook([sheet]), Report()), Report())
    assert [workbook.sheets[0].cells[(row, 0)].style.number_format for row in range(len(formats))] == [
        "0", "#,##0.00", "0%", "m/d/yy", "d-mmm-yy", "h:mm:ss", "m/d/yy h:mm", "dddd mmmm d yyyy"]
    assert workbook.sheets[0].cells[(3, 0)].value == 45000.25


def test_ods_unknown_number_format_is_reported():
    sheet = Sheet("Money", cells={(0, 0): Cell(3.0, style=CellStyle(number_format='"$"#,##0_);("$"#,##0)'))})
    report = Report()
    write_ods(Workbook([sheet]), report)
    assert any("number formats" in warning for warning in report.warnings)
