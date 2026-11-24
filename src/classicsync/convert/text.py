import codecs

from .document import document_from_text


def decode_text(data):
    if data.startswith(codecs.BOM_UTF8):
        return data[len(codecs.BOM_UTF8):].decode("utf-8")
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def read_text(data, report):
    return document_from_text(decode_text(data))


def write_text(document, report):
    lines = []
    for paragraph in document.paragraphs:
        if any(run.picture is not None for run in paragraph.runs):
            report.lost("pictures")
        prefix = "* " if paragraph.list_kind == "bullet" else ""
        lines.append(prefix + paragraph.text())
    report.lost("all formatting")
    return ("\n".join(lines) + "\n").encode("utf-8")
