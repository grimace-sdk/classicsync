import os
from dataclasses import dataclass

from ..formats.fnt import FntError, FntFont, Glyph, read_fon, read_fnt, write_fnt
from ..i18n import N_

RESOLUTION = 96
FIRST_CHAR = 0x20
LAST_CHAR = 0xFF
DEFAULT_CHAR = 0x80
STANDARD_POINT_SIZES = (8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 36)
BOLD_WEIGHT = 700
NORMAL_WEIGHT = 400
TRUETYPE_EXTENSIONS = (".ttf", ".otf", ".ttc")
RASTER_EXTENSIONS = (".fon",)


@dataclass(frozen=True)
class CharacterSet:
    name: str
    charset: int
    encoding: str


CHARACTER_SETS = (
    CharacterSet(N_("Western"), 0, "cp1252"),
    CharacterSet(N_("Central European"), 238, "cp1250"),
    CharacterSet(N_("Cyrillic"), 204, "cp1251"),
    CharacterSet(N_("Greek"), 161, "cp1253"),
    CharacterSet(N_("Turkish"), 162, "cp1254"),
    CharacterSet(N_("Baltic"), 186, "cp1257"),
)


class FontConversionError(ValueError):
    pass


def is_font(name):
    return os.path.splitext(name)[1].lower() in TRUETYPE_EXTENSIONS + RASTER_EXTENSIONS


def freetype_module():
    try:
        import freetype
    except ImportError as error:
        raise FontConversionError("converting TrueType fonts needs freetype-py: pip install 'classicsync[gui]'") from error
    return freetype


def character(code, encoding):
    try:
        return bytes([code]).decode(encoding)
    except UnicodeDecodeError:
        return None


def mono_rows(bitmap):
    rows = []
    for row in range(bitmap.rows):
        start = row * bitmap.pitch
        value = 0
        for byte in bitmap.buffer[start:start + (bitmap.width + 7) // 8]:
            value = (value << 8) | byte
        rows.append(value >> (((bitmap.width + 7) // 8) * 8 - bitmap.width) if bitmap.width else 0)
    return rows


def rasterise(path, points, character_set=CHARACTER_SETS[0], face_index=0):
    freetype = freetype_module()
    try:
        face = freetype.Face(str(path), face_index)
    except freetype.FT_Exception as error:
        raise FontConversionError(f"cannot read {os.path.basename(str(path))}: {error}") from error
    face.set_char_size(points * 64, 0, RESOLUTION, RESOLUTION)
    ascent = face.size.ascender >> 6
    descent = -(face.size.descender >> 6)
    height = max(1, ascent + descent)
    em_pixels = round(points * RESOLUTION / 72)
    flags = freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_MONO
    glyphs = []
    for code in range(FIRST_CHAR, LAST_CHAR + 2):
        text = character(min(code, LAST_CHAR), character_set.encoding) if code <= LAST_CHAR else " "
        if text is None or face.get_char_index(text) == 0 and text != " ":
            text = character(DEFAULT_CHAR, character_set.encoding) or "?"
        face.load_char(text, flags)
        slot = face.glyph
        bitmap = slot.bitmap
        left = max(0, slot.bitmap_left)
        width = max(1, slot.advance.x >> 6, left + bitmap.width)
        rows = [0] * height
        top = ascent - slot.bitmap_top
        for index, value in enumerate(mono_rows(bitmap)):
            row = top + index
            if 0 <= row < height:
                rows[row] = value << max(0, width - left - bitmap.width)
        glyphs.append(Glyph(width, rows))
    family = face.family_name.decode("latin-1", "replace") if face.family_name else os.path.splitext(os.path.basename(str(path)))[0]
    style = face.style_flags
    return FntFont(
        face=family, points=points, pixel_height=height, ascent=ascent, glyphs=glyphs, first_char=FIRST_CHAR,
        default_char=DEFAULT_CHAR, break_char=FIRST_CHAR, charset=character_set.charset,
        weight=BOLD_WEIGHT if style & freetype.FT_STYLE_FLAG_BOLD else NORMAL_WEIGHT,
        italic=bool(style & freetype.FT_STYLE_FLAG_ITALIC), internal_leading=max(0, height - em_pixels), resolution=RESOLUTION)


def raster_fonts(data):
    if data[:2] == b"MZ":
        return read_fon(data)
    return [read_fnt(data)]


def converted_fonts(path, points=(), character_set=CHARACTER_SETS[0]):
    extension = os.path.splitext(str(path))[1].lower()
    if extension in RASTER_EXTENSIONS:
        with open(path, "rb") as handle:
            data = handle.read()
        try:
            fonts = raster_fonts(data)
        except FntError as error:
            raise FontConversionError(str(error)) from error
        return [font for font in fonts if not points or font.points in points]
    return [rasterise(path, size, character_set) for size in points]


def font_file_name(stem, font):
    return f"{stem}{font.points}.fnt"


def font_files(path, points=(), character_set=CHARACTER_SETS[0]):
    stem = os.path.splitext(os.path.basename(str(path)))[0].replace(" ", "")
    return [(font_file_name(stem, font), write_fnt(font)) for font in converted_fonts(path, points, character_set)]


def available_sizes(path):
    extension = os.path.splitext(str(path))[1].lower()
    if extension in RASTER_EXTENSIONS:
        return sorted({font.points for font in converted_fonts(path)})
    return list(STANDARD_POINT_SIZES)
