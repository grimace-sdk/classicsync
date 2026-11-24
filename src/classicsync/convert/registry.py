import io
import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .bitmap import PNG_SIGNATURE, read_bmp, read_png, write_2bp, write_bmp, write_png
from .csv_format import read_csv, write_csv
from .docx import read_docx, write_docx
from .errors import ConversionError, Report
from .html import read_html, write_html
from .ods import read_ods, write_ods
from .odt import read_odt, write_odt
from .pocket_excel import read_pocket_excel, write_pocket_excel
from .rtf_reader import read_rtf
from .rtf_writer import write_pocket_word, write_rtf
from .text import read_text, write_text
from .xlsx import read_xlsx, write_xlsx

DOCUMENT = "document"
SPREADSHEET = "spreadsheet"
IMAGE = "image"


@dataclass(frozen=True)
class Format:
    name: str
    kind: str
    extensions: tuple
    description: str
    device: bool
    reader: object
    writer: object
    writer_options: tuple = field(default=())


@dataclass
class Conversion:
    data: bytes
    source_format: str
    target_format: str
    warnings: list


def reader_only(function):
    return lambda data, report, **options: function(data, report)


def image_reader(function):
    return lambda data, report, **options: function(data)


def write_2bp_reporting(bitmap, report):
    if not bitmap.is_grayscale() or len({colour for row in bitmap.pixels for colour in row}) > 4:
        report.lost("colour and shades beyond 4 grays (2bp holds 2 bits per pixel)")
    return write_2bp(bitmap)


FORMATS = {
    "pwd": Format("pwd", DOCUMENT, (".pwd", ".pwt"), "Pocket Word document or template", True,
                  reader_only(read_rtf),
                  lambda document, report, version=2, **options: write_pocket_word(document, report, version),
                  ("version",)),
    "rtf": Format("rtf", DOCUMENT, (".rtf",), "Rich Text Format", False, reader_only(read_rtf),
                  lambda document, report, **options: write_rtf(document, report)),
    "txt": Format("txt", DOCUMENT, (".txt",), "Plain text (UTF-8)", False, reader_only(read_text),
                  lambda document, report, **options: write_text(document, report)),
    "html": Format("html", DOCUMENT, (".html", ".htm"), "HTML", False, reader_only(read_html),
                   lambda document, report, **options: write_html(document, report)),
    "docx": Format("docx", DOCUMENT, (".docx",), "Word document (Office Open XML)", False, reader_only(read_docx),
                   lambda document, report, **options: write_docx(document, report)),
    "odt": Format("odt", DOCUMENT, (".odt",), "OpenDocument text", False, reader_only(read_odt),
                  lambda document, report, **options: write_odt(document, report)),
    "pxl": Format("pxl", SPREADSHEET, (".pxl", ".pxt"), "Pocket Excel workbook or template", True,
                  reader_only(read_pocket_excel),
                  lambda workbook, report, version=2, **options: write_pocket_excel(workbook, report, version),
                  ("version",)),
    "csv": Format("csv", SPREADSHEET, (".csv",), "Comma-separated values (one sheet)", False, reader_only(read_csv),
                  lambda workbook, report, sheet=0, **options: write_csv(workbook, report, sheet), ("sheet",)),
    "xlsx": Format("xlsx", SPREADSHEET, (".xlsx",), "Excel workbook (Office Open XML)", False, reader_only(read_xlsx),
                   lambda workbook, report, **options: write_xlsx(workbook, report)),
    "ods": Format("ods", SPREADSHEET, (".ods",), "OpenDocument spreadsheet", False, reader_only(read_ods),
                  lambda workbook, report, **options: write_ods(workbook, report)),
    "2bp": Format("2bp", IMAGE, (".2bp",), "Windows CE 2-bit grayscale bitmap", True, image_reader(read_bmp),
                  lambda bitmap, report, **options: write_2bp_reporting(bitmap, report)),
    "bmp": Format("bmp", IMAGE, (".bmp", ".dib"), "Windows bitmap", False, image_reader(read_bmp),
                  lambda bitmap, report, **options: write_bmp(bitmap)),
    "png": Format("png", IMAGE, (".png",), "PNG image", False, image_reader(read_png),
                  lambda bitmap, report, **options: write_png(bitmap)),
}
EXTENSIONS = {extension: name for name, format in FORMATS.items() for extension in format.extensions}
DESKTOP_DEFAULTS = {"pwd": "docx", "pxl": "xlsx", "2bp": "png"}
DEVICE_DEFAULTS = {"rtf": "pwd", "txt": "pwd", "html": "pwd", "docx": "pwd", "odt": "pwd", "csv": "pxl", "xlsx": "pxl", "ods": "pxl",
                   "bmp": "2bp", "png": "2bp"}


def format_for_extension(extension):
    extension = extension.lower()
    if not extension.startswith("."):
        extension = "." + extension
    return EXTENSIONS.get(extension)


def formats_for(extension):
    source = FORMATS.get(extension.lower().lstrip(".")) or FORMATS.get(format_for_extension(extension) or "")
    if source is None:
        return []
    return [name for name, format in FORMATS.items() if format.kind == source.kind and name != source.name]


def default_target(source_format):
    return DESKTOP_DEFAULTS.get(source_format) or DEVICE_DEFAULTS.get(source_format)


def sniff_format(data):
    stripped = data.lstrip()
    if stripped.startswith(b"{\\pwd"):
        return "pwd"
    if stripped.startswith(b"{\\rtf"):
        return "rtf"
    if data.startswith(PNG_SIGNATURE):
        return "png"
    if data.startswith(b"BM") and len(data) >= 30:
        return "2bp" if struct.unpack_from("<H", data, 28)[0] == 2 else "bmp"
    if data.startswith(b"PK"):
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            return None
        if "word/document.xml" in names:
            return "docx"
        if "xl/workbook.xml" in names:
            return "xlsx"
        if "mimetype" in names:
            mimetype = zipfile.ZipFile(io.BytesIO(data)).read("mimetype").strip()
            return {b"application/vnd.oasis.opendocument.text": "odt",
                    b"application/vnd.oasis.opendocument.spreadsheet": "ods"}.get(mimetype)
        return None
    if len(data) >= 5 and data[0] == 0x09 and data[3:5] == b"\x05\x00":
        return "pxl"
    head = data[:512].lower()
    if b"<html" in head or b"<!doctype html" in head:
        return "html"
    return None


def resolve_source(path_or_bytes, source_format):
    if isinstance(path_or_bytes, (bytes, bytearray, memoryview)):
        data = bytes(path_or_bytes)
        name = None
    else:
        path = Path(path_or_bytes)
        data = path.read_bytes()
        name = format_for_extension(path.suffix)
    source_format = source_format or name or sniff_format(data)
    if source_format is None:
        raise ConversionError("cannot tell the source format; give it explicitly")
    return data, normalise_name(source_format)


def normalise_name(name):
    name = name.lower().lstrip(".")
    if name in FORMATS:
        return name
    by_extension = format_for_extension(name)
    if by_extension:
        return by_extension
    raise ConversionError(f"unknown format {name!r} (known: {', '.join(FORMATS)})")


def converter(source_format, target_format):
    source = FORMATS[normalise_name(source_format)]
    target = FORMATS[normalise_name(target_format)]
    if source.kind != target.kind:
        raise ConversionError(f"cannot convert {source.description} to {target.description}")

    def run(data, **options):
        report = Report()
        model = source.reader(data, report, **options)
        output = target.writer(model, report, **options)
        return Conversion(output, source.name, target.name, report.warnings)

    return run


def convert(path_or_bytes, source_format=None, target_format=None, **options):
    data, source_name = resolve_source(path_or_bytes, source_format)
    target_name = normalise_name(target_format) if target_format else default_target(source_name)
    if target_name is None:
        raise ConversionError(f"no default conversion for {source_name}; give a target format")
    return converter(source_name, target_name)(data, **options)
