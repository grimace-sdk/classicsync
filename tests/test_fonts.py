import struct
from pathlib import Path

import pytest

from classicsync.convert.fonts import CHARACTER_SETS, converted_fonts, font_files, rasterise
from classicsync.convert.rules import device_conversion
from classicsync.formats.fnt import RT_FONT, FntFont, Glyph, read_fnt, read_fon, write_fnt

MISC = Path(__file__).resolve().parents[2]
RUSCE = MISC / "velo-apps" / "apps" / "RusCE-for-Windows-CE-1-0"
SYSTEM_FONTS = [Path("/System/Library/Fonts/Supplemental/Arial.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                Path("C:/Windows/Fonts/arial.ttf")]


def sample_font():
    glyphs = [Glyph(width, [(1 << width) - 1 if row % 2 else 0 for row in range(10)]) for width in range(1, 6)]
    return FntFont(face="Test", points=8, pixel_height=10, ascent=8, glyphs=glyphs, first_char=0x41, default_char=0x41,
                   break_char=0x41)


def fon_file(fnt):
    ne_offset = 0x40
    resource_table = 0x40
    shift = 4
    data_offset = 0x100
    header = bytearray(b"MZ" + bytes(0x3A) + struct.pack("<I", ne_offset))
    ne = bytearray(b"NE" + bytes(0x22) + struct.pack("<H", resource_table) + bytes(resource_table - 0x26))
    length = (len(fnt) + (1 << shift) - 1) >> shift
    resources = struct.pack("<H", shift) + struct.pack("<HHI", RT_FONT, 1, 0) + struct.pack("<HHHHI", data_offset >> shift, length, 0, 0x8001, 0)
    resources += struct.pack("<H", 0)
    body = bytes(header) + bytes(ne) + resources
    return body + bytes(data_offset - len(body)) + fnt + bytes((length << shift) - len(fnt))


def test_written_fonts_read_back_unchanged():
    font = sample_font()
    again = read_fnt(write_fnt(font))
    assert (again.face, again.points, again.pixel_height, again.first_char, again.last_char) == ("Test", 8, 10, 0x41, 0x44)
    assert again.glyphs == font.glyphs


def test_fonts_are_extracted_from_fon_files():
    [font] = read_fon(fon_file(write_fnt(sample_font())))
    assert font.face == "Test" and font.glyphs == sample_font().glyphs


@pytest.mark.skipif(not RUSCE.exists(), reason="RusCE font samples not present")
def test_real_ce_fonts_round_trip_outside_the_copyright_padding():
    for path in sorted(RUSCE.glob("*.fnt")):
        data = path.read_bytes()
        again = write_fnt(read_fnt(data))
        assert len(again) == len(data)
        assert read_fnt(again).glyphs == read_fnt(data).glyphs


@pytest.mark.skipif(not any(path.exists() for path in SYSTEM_FONTS), reason="no TrueType font to rasterise")
def test_truetype_fonts_rasterise_to_ce_raster_fonts():
    pytest.importorskip("freetype")
    path = next(path for path in SYSTEM_FONTS if path.exists())
    font = rasterise(path, 10, CHARACTER_SETS[2])
    assert font.charset == 204 and font.first_char == 0x20 and font.last_char == 0xFF
    assert any(font.glyph(ord("A")).rows) and not any(font.glyph(ord(" ")).rows)
    [(name, data)] = font_files(path, (10,))
    assert name.endswith("10.fnt") and read_fnt(data).points == 10
    assert [font.points for font in converted_fonts(path, (8, 12))] == [8, 12]


def test_fonts_convert_to_raster_fonts_only_for_ce_1():
    assert device_conversion("Arial.ttf", version=1) == ("ttf", "fnt", "Arial.fnt")
    assert device_conversion("SSERIF.FON", version=1) == ("fon", "fnt", "SSERIF.fnt")
    assert device_conversion("Arial.ttf", version=2) is None
