from dataclasses import dataclass, field, replace

DEFAULT_FONT = "Times New Roman"
DEFAULT_SIZE_HALF_POINTS = 20
LINE_BREAK = "\n"


@dataclass(frozen=True)
class CharacterFormat:
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    superscript: bool = False
    subscript: bool = False
    font: str = ""
    size_half_points: int = 0
    colour: tuple = None

    def changed(self, **changes):
        return replace(self, **changes)


@dataclass
class Picture:
    bitmap: object
    width_twips: int = 0
    height_twips: int = 0


@dataclass
class Run:
    text: str = ""
    format: CharacterFormat = field(default_factory=CharacterFormat)
    picture: Picture = None


@dataclass
class Paragraph:
    runs: list = field(default_factory=list)
    alignment: str = "left"
    left_indent: int = 0
    right_indent: int = 0
    first_line_indent: int = 0
    space_before: int = 0
    space_after: int = 0
    tab_stops: list = field(default_factory=list)
    list_kind: str = ""
    heading_level: int = 0
    page_break_before: bool = False

    def text(self):
        return "".join(run.text for run in self.runs if run.picture is None)

    def append_text(self, text, character_format):
        if self.runs and self.runs[-1].picture is None and self.runs[-1].format == character_format:
            self.runs[-1].text += text
        else:
            self.runs.append(Run(text, character_format))


@dataclass
class Document:
    paragraphs: list = field(default_factory=list)
    default_font: str = DEFAULT_FONT
    default_size_half_points: int = DEFAULT_SIZE_HALF_POINTS
    title: str = ""

    def fonts(self):
        names = [self.default_font]
        for paragraph in self.paragraphs:
            for run in paragraph.runs:
                if run.format.font and run.format.font not in names:
                    names.append(run.format.font)
        return names

    def colours(self):
        colours = []
        for paragraph in self.paragraphs:
            for run in paragraph.runs:
                if run.format.colour is not None and run.format.colour not in colours:
                    colours.append(run.format.colour)
        return colours

    def plain_text(self):
        return "\n".join(paragraph.text() for paragraph in self.paragraphs)


def document_from_text(text):
    document = Document()
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        paragraph = Paragraph()
        if line:
            paragraph.append_text(line, CharacterFormat())
        document.paragraphs.append(paragraph)
    if len(document.paragraphs) > 1 and not document.paragraphs[-1].runs:
        document.paragraphs.pop()
    return document
