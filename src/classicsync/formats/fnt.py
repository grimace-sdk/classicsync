import struct
from dataclasses import dataclass, field

VERSION_2 = 0x0200
VERSION_3 = 0x0300
HEADER_FIELDS = "<HI60sHHHHHHHBBBHBHHBHHBBBBHIIIIB"
HEADER_SIZE_2 = 118
HEADER_SIZE_3 = 148
NAMES = ("version size copyright type points vertical_resolution horizontal_resolution ascent internal_leading external_leading "
         "italic underline strike_out weight charset pixel_width pixel_height pitch_and_family average_width maximum_width "
         "first_char last_char default_char break_char width_bytes device face_offset bits_pointer bits_offset reserved").split()
RT_FONT = 0x8008
MAX_VERSION_2_SIZE = 0x10000
FF_DONTCARE_VARIABLE_PITCH = 0x01


class FntError(ValueError):
    pass


@dataclass
class Glyph:
    width: int
    rows: list


@dataclass
class FntFont:
    face: str
    points: int
    pixel_height: int
    ascent: int
    glyphs: list
    first_char: int = 0x20
    default_char: int = 0x80
    break_char: int = 0x20
    charset: int = 0
    weight: int = 400
    italic: bool = False
    internal_leading: int = 0
    external_leading: int = 0
    pitch_and_family: int = FF_DONTCARE_VARIABLE_PITCH
    copyright: str = ""
    resolution: int = 96
    extra: dict = field(default_factory=dict)

    @property
    def last_char(self):
        return self.first_char + len(self.glyphs) - 2

    def glyph(self, code):
        index = code - self.first_char
        return self.glyphs[index] if 0 <= index < len(self.glyphs) - 1 else None


def glyph_from_columns(data, offset, width, height):
    columns = (width + 7) // 8
    rows = []
    for row in range(height):
        value = 0
        for column in range(columns):
            value = (value << 8) | data[offset + column * height + row]
        rows.append(value >> (columns * 8 - width) if width else 0)
    return Glyph(width, rows)


def glyph_columns(glyph, height):
    columns = (glyph.width + 7) // 8
    data = bytearray(columns * height)
    shift = columns * 8 - glyph.width
    for row, value in enumerate(glyph.rows[:height]):
        value <<= shift
        for column in range(columns):
            data[column * height + row] = (value >> (8 * (columns - 1 - column))) & 0xFF
    return bytes(data)


def read_fnt(data):
    if len(data) < HEADER_SIZE_2:
        raise FntError("file is too short for a font header")
    header = dict(zip(NAMES, struct.unpack_from(HEADER_FIELDS, data, 0)))
    version = header["version"]
    if version not in (VERSION_2, VERSION_3):
        raise FntError(f"unsupported font version {version:#06x}")
    if header["type"] & 1:
        raise FntError("vector fonts cannot be converted")
    count = header["last_char"] - header["first_char"] + 2
    table = HEADER_SIZE_2 if version == VERSION_2 else HEADER_SIZE_3
    entry_format, entry_size = ("<HH", 4) if version == VERSION_2 else ("<HI", 6)
    height = header["pixel_height"]
    glyphs = []
    for index in range(count):
        width, offset = struct.unpack_from(entry_format, data, table + index * entry_size)
        glyphs.append(glyph_from_columns(data, offset, width, height))
    face_offset = header["face_offset"]
    face = data[face_offset:data.index(b"\0", face_offset)].decode("latin-1") if 0 < face_offset < len(data) else ""
    return FntFont(
        face=face, points=header["points"], pixel_height=height, ascent=header["ascent"], glyphs=glyphs,
        first_char=header["first_char"], default_char=header["first_char"] + header["default_char"],
        break_char=header["first_char"] + header["break_char"], charset=header["charset"], weight=header["weight"],
        italic=bool(header["italic"]), internal_leading=header["internal_leading"], external_leading=header["external_leading"],
        pitch_and_family=header["pitch_and_family"], copyright=header["copyright"].split(b"\0", 1)[0].decode("latin-1"),
        resolution=header["vertical_resolution"])


def write_fnt(font):
    height = font.pixel_height
    count = len(font.glyphs)
    bits_offset = HEADER_SIZE_2 + count * 4
    table = bytearray()
    bitmaps = bytearray()
    for glyph in font.glyphs:
        table += struct.pack("<HH", glyph.width, bits_offset + len(bitmaps))
        bitmaps += glyph_columns(glyph, height)
    face_offset = bits_offset + len(bitmaps)
    face = font.face.encode("latin-1", "replace") + b"\0"
    size = face_offset + len(face)
    if size > MAX_VERSION_2_SIZE:
        raise FntError(f"{font.face} at {font.points} points is too large for a version 2.0 font file")
    widths = [glyph.width for glyph in font.glyphs[:-1]]
    fixed = len(set(widths)) == 1
    header = struct.pack(
        HEADER_FIELDS, VERSION_2, size, font.copyright.encode("latin-1", "replace")[:60], 0, font.points, font.resolution,
        font.resolution, font.ascent, font.internal_leading, font.external_leading, int(font.italic), 0, 0, font.weight,
        font.charset, widths[0] if fixed else 0, height, font.pitch_and_family & ~1 if fixed else font.pitch_and_family | 1,
        round(sum(widths) / len(widths)) if widths else 0, max(widths, default=0), font.first_char, font.last_char,
        max(0, font.default_char - font.first_char), max(0, font.break_char - font.first_char),
        sum((glyph.width + 7) // 8 for glyph in font.glyphs), 0, face_offset, 0, bits_offset, 0)
    return header + bytes(table) + bytes(bitmaps) + face


def ne_resources(data, resource_type):
    if data[:2] != b"MZ" or len(data) < 0x40:
        raise FntError("not a Windows font resource file")
    ne = struct.unpack_from("<I", data, 0x3C)[0]
    if data[ne:ne + 2] != b"NE":
        raise FntError("not a 16-bit Windows font resource file")
    position = ne + struct.unpack_from("<H", data, ne + 0x24)[0]
    shift = struct.unpack_from("<H", data, position)[0]
    position += 2
    found = []
    while True:
        type_id, count = struct.unpack_from("<HH", data, position)
        if type_id == 0:
            return found
        position += 8
        for _ in range(count):
            offset, length = struct.unpack_from("<HH", data, position)
            if type_id == resource_type:
                found.append(data[offset << shift:(offset + length) << shift])
            position += 12


def read_fon(data):
    fonts = []
    for resource in ne_resources(data, RT_FONT):
        try:
            fonts.append(read_fnt(resource))
        except (FntError, struct.error, ValueError):
            continue
    if not fonts:
        raise FntError("no raster fonts found")
    return fonts
