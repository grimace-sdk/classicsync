import struct

import pytest

from classicsync.formats.cab import CabArchive
from classicsync.formats.cab_lzx import LzxDecoder
from classicsync.formats.installshield3 import InstallShield3Archive, InstallShield3Error, explode, is_installshield3
from classicsync.formats.pe_resources import build_bitmap_file, build_icon_file, is_pe, media_extension
from classicsync.formats.sfx import find_cabinets

BLAST_EXAMPLE = bytes([0x00, 0x04, 0x82, 0x24, 0x25, 0x8F, 0x80, 0x7F])


def test_explode_reference_example():
    assert explode(BLAST_EXAMPLE) == b"AIAIAIAIAIAIA"


def test_explode_rejects_bad_header():
    with pytest.raises(InstallShield3Error):
        explode(bytes([0x02, 0x04, 0x00]))


def build_installshield3(directory, files):
    directory_name = directory.encode("latin-1")
    directory_record = struct.pack("<HHH", len(files), 6 + len(directory_name), len(directory_name)) + directory_name
    header_size = 0x33
    payload = b""
    file_records = b""
    for name, compressed, size in files:
        encoded_name = name.encode("latin-1")
        offset = header_size + len(payload)
        record_size = 30 + len(encoded_name)
        file_records += b"\x00" * 3 + struct.pack("<IIIIIHIB", size, len(compressed), offset, 0x2A2A2862, 0,
                                                  record_size, 0x20, len(encoded_name)) + encoded_name
        payload += compressed
    header = bytearray(header_size)
    struct.pack_into("<I", header, 0, 0x8C655D13)
    struct.pack_into("<H", header, 0x0C, len(files))
    struct.pack_into("<I", header, 0x29, header_size + len(payload))
    struct.pack_into("<H", header, 0x31, 1)
    return bytes(header) + payload + directory_record + file_records


def test_installshield3_archive_lists_and_reads():
    archive_bytes = build_installshield3("system", [("one.txt", BLAST_EXAMPLE, 13), ("two.txt", BLAST_EXAMPLE, 13)])
    assert is_installshield3(archive_bytes)
    archive = InstallShield3Archive(archive_bytes)
    assert archive.names() == ["system/one.txt", "system/two.txt"]
    assert archive.read("SYSTEM\\two.txt") == b"AIAIAIAIAIAIA"
    assert archive.entries[0].modified == "2000-03-02 05:17:20"


def test_installshield3_size_mismatch_raises():
    archive = InstallShield3Archive(build_installshield3("", [("bad.txt", BLAST_EXAMPLE, 99)]))
    assert archive.names() == ["bad.txt"]
    with pytest.raises(InstallShield3Error):
        archive.read("bad.txt")


def lzx_uncompressed_stream(payload):
    header_bits = (0 << 27) | (3 << 24) | len(payload)
    header = header_bits << 4
    words = struct.pack("<HH", header >> 16, header & 0xFFFF)
    padding = b"\x00" if len(payload) % 2 else b""
    return words + struct.pack("<III", 1, 1, 1) + payload + padding


def test_lzx_uncompressed_block():
    payload = b"classicsync LZX uncompressed block"
    decoder = LzxDecoder(16)
    assert decoder.decompress(lzx_uncompressed_stream(payload), len(payload)) == payload


def build_cabinet(name, content):
    encoded_name = name.encode("latin-1") + b"\x00"
    header_size = 36
    folder_size = 8
    file_size = 16 + len(encoded_name)
    data_offset = header_size + folder_size + file_size
    total_size = data_offset + 8 + len(content)
    header = b"MSCF" + struct.pack("<IIIIIBBHHHHH", 0, total_size, 0, header_size + folder_size, 0, 3, 1, 1, 1, 0, 0, 0)
    folder = struct.pack("<IHH", data_offset, 1, 0)
    file_entry = struct.pack("<IIHHHH", len(content), 0, 0, 0x2A2A, 0, 0x20) + encoded_name
    data_block = struct.pack("<IHH", 0, len(content), len(content)) + content
    return header + folder + file_entry + data_block


def test_find_cabinets_skips_false_signatures():
    cabinet = build_cabinet("hello.txt", b"hello world")
    container = b"MZ" + b"\x00" * 30 + b"MSCF not a header" + b"\x00" * 20 + cabinet + b"trailer"
    found = find_cabinets(container)
    assert len(found) == 1
    assert found[0].offset == container.index(cabinet)
    archive = CabArchive(found[0].slice(container))
    assert archive.names() == ["hello.txt"]
    assert archive.read("hello.txt") == b"hello world"


def test_bitmap_file_header_points_past_palette():
    info_header = struct.pack("<IiiHHIIiiII", 40, 2, 2, 1, 4, 0, 8, 0, 0, 0, 0)
    palette = b"\x00\x00\x00\x00" * 16
    pixels = b"\x01\x00\x00\x00\x10\x00\x00\x00"
    bitmap = build_bitmap_file(info_header + palette + pixels)
    signature, file_size, _, _, pixel_offset = struct.unpack_from("<2sIHHI", bitmap, 0)
    assert signature == b"BM"
    assert file_size == len(bitmap)
    assert bitmap[pixel_offset:] == pixels


def test_icon_file_from_group():
    images = {1: b"A" * 40, 2: b"B" * 20}
    group = struct.pack("<HHH", 0, 1, 3)
    group += struct.pack("<BBBBHHIH", 32, 32, 0, 0, 1, 8, 40, 1)
    group += struct.pack("<BBBBHHIH", 16, 16, 0, 0, 1, 8, 20, 2)
    group += struct.pack("<BBBBHHIH", 48, 48, 0, 0, 1, 8, 20, 9)
    icon = build_icon_file(group, images)
    assert struct.unpack_from("<HHH", icon, 0) == (0, 1, 2)
    width, _, _, _, _, _, size, offset = struct.unpack_from("<BBBBHHII", icon, 6)
    assert (width, size, offset) == (32, 40, 38)
    assert icon[offset:offset + size] == images[1]
    assert icon[38 + 40:] == images[2]


def test_media_and_pe_detection():
    assert media_extension(b"RIFF\x00\x00\x00\x00AVI LIST") == "avi"
    assert media_extension(b"RIFF\x00\x00\x00\x00WAVEfmt ") == "wav"
    assert media_extension(b"GIF89a") == "gif"
    assert media_extension(b"\x00" * 12) is None
    assert not is_pe(b"MZ" + b"\x00" * 100)
