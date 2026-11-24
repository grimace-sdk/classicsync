import re

from ....convert.document import LINE_BREAK, CharacterFormat, Document, Paragraph

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
ESCAPED_CHARACTERS = "\\*_`#"
MARKERS = (("***", True, True), ("___", True, True), ("**", True, False), ("__", True, False), ("*", False, True),
           ("_", False, True))


def escape_markdown(text):
    escaped = "".join("\\" + character if character in ESCAPED_CHARACTERS else character for character in text)
    return re.sub(r"^(\s*)([-+]|\d+[.)])(\s)", r"\1\\\2\3", escaped)


def unescape_markdown(text):
    return re.sub(r"\\(.)", r"\1", text)


def styled_text(text, bold, italic):
    stripped = text.strip()
    if not stripped or not (bold or italic):
        return text
    marker = "***" if bold and italic else "**" if bold else "*"
    leading = text[:len(text) - len(text.lstrip())]
    trailing = text[len(text.rstrip()):]
    return f"{leading}{marker}{stripped}{marker}{trailing}"


def paragraph_lines(paragraph):
    groups = []
    for run in paragraph.runs:
        if run.picture is not None:
            continue
        style = (run.format.bold, run.format.italic)
        if groups and groups[-1][0] == style:
            groups[-1][1].append(run.text)
        else:
            groups.append((style, [run.text]))
    lines = [""]
    for (bold, italic), texts in groups:
        pieces = "".join(texts).split(LINE_BREAK)
        for index, piece in enumerate(pieces):
            if index:
                lines.append("")
            lines[-1] += styled_text(escape_markdown(piece), bold, italic)
    return lines


def markdown_from_document(document):
    output = []
    number = 0
    for paragraph in document.paragraphs:
        lines = paragraph_lines(paragraph)
        number = number + 1 if paragraph.list_kind == "number" else 0
        if paragraph.heading_level:
            prefix = "#" * min(paragraph.heading_level, 6) + " "
        elif paragraph.list_kind == "bullet":
            prefix = "- "
        elif paragraph.list_kind == "number":
            prefix = f"{number}. "
        else:
            prefix = ""
        output.append(prefix + lines[0] if lines[0] or not prefix else prefix.rstrip())
        output.extend(lines[1:])
    while output and not output[-1]:
        output.pop()
    return "\n".join(output) + "\n" if output else ""


def markdown_from_text(text):
    lines = [escape_markdown(line) for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n" if lines else ""


def find_closing(text, marker, start):
    index = start
    while True:
        index = text.find(marker, index)
        if index < 0:
            return -1
        if text[index - 1] != "\\" and index > start:
            return index
        index += 1


def inline_runs(text, bold=False, italic=False):
    runs = []
    buffer = []
    index = 0

    def flush():
        if buffer:
            runs.append(("".join(buffer), bold, italic))
            buffer.clear()

    while index < len(text):
        character = text[index]
        if character == "\\" and index + 1 < len(text):
            buffer.append(text[index + 1])
            index += 2
            continue
        for marker, marker_bold, marker_italic in MARKERS:
            if text.startswith(marker, index) and index + len(marker) < len(text) and not text[index + len(marker)].isspace():
                closing = find_closing(text, marker, index + len(marker))
                if closing > 0:
                    flush()
                    runs.extend(inline_runs(text[index + len(marker):closing], bold or marker_bold, italic or marker_italic))
                    index = closing + len(marker)
                    break
        else:
            buffer.append(character)
            index += 1
    flush()
    return runs


def paragraph_from_line(line):
    paragraph = Paragraph()
    heading = HEADING.match(line)
    bullet = BULLET.match(line)
    numbered = NUMBERED.match(line)
    if heading:
        paragraph.heading_level = len(heading.group(1))
        line = heading.group(2)
    elif bullet:
        paragraph.list_kind = "bullet"
        line = bullet.group(1)
    elif numbered:
        paragraph.list_kind = "number"
        line = numbered.group(1)
    for text, bold, italic in inline_runs(line.rstrip()):
        paragraph.append_text(text, CharacterFormat(bold=bold, italic=italic))
    return paragraph


def document_from_markdown(text):
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    document = Document(default_font="Tahoma")
    document.paragraphs = [paragraph_from_line(line) for line in lines] or [Paragraph()]
    return document


def plain_text(markdown):
    return "\n".join(paragraph.text() for paragraph in document_from_markdown(markdown).paragraphs)
