import struct

import pytest

from classicsync.connection.dccm import FLAG_PLATFORM_VERSIONS, DeviceInfo, encode_password


def wide(text):
    return (text + "\0").encode("utf-16-le")


def build_block(name="Handheld_PC", platforms=("HPC",), oem="Philips Velo", flags=0, versions=()):
    strings = bytearray()
    name_offset = 0x24 + len(strings)
    strings += wide(name)
    platform_offset = 0x24 + len(strings)
    for platform in platforms:
        strings += wide(platform)
    if flags & FLAG_PLATFORM_VERSIONS:
        strings += wide("")
    oem_offset = 0x24 + len(strings)
    strings += wide(oem)
    for major, minor in versions:
        strings += struct.pack("<II", major, minor)
    header = struct.pack("<IBBHIIIIIII", 0x24, 2, 0, 0, 4000, flags, 0x1234, 0, name_offset, platform_offset, oem_offset)
    return header + bytes(strings)


def test_parses_ce2_info_block():
    info = DeviceInfo.parse(build_block())
    assert (info.name, info.platform, info.oem_info, info.os_major) == ("Handheld_PC", "HPC", "Philips Velo", 2)
    assert info.partner_ids == (0x1234, 0)
    assert info.platforms == []


def test_parses_extended_platform_list():
    block = build_block(name="Pocket_PC", platforms=("PocketPC", "Palm PC2"), oem="Compaq iPAQ H3600",
                        flags=FLAG_PLATFORM_VERSIONS, versions=((3, 0), (2, 1)))
    info = DeviceInfo.parse(block)
    assert info.platform == "PocketPC"
    assert info.platforms == [("PocketPC", 3, 0), ("Palm PC2", 2, 1)]


def test_rejects_out_of_range_blocks():
    with pytest.raises(ValueError):
        DeviceInfo.parse(build_block()[:0x24])
    with pytest.raises(ValueError):
        DeviceInfo.parse(build_block(oem="x" * 0x800))


def test_rejects_unterminated_string():
    block = bytearray(build_block())
    block[-2:] = b"AA"
    with pytest.raises(ValueError):
        DeviceInfo.parse(bytes(block))


def test_password_lowercased_except_for_pocket_pc():
    key = 0x5A
    handheld = encode_password("Secret", key, "HPC")
    pocket = encode_password("Secret", key, "PocketPC")
    assert struct.unpack("<H", handheld[:2])[0] == len(wide("secret"))
    assert bytes(byte ^ key for byte in handheld[2:]) == wide("secret")
    assert bytes(byte ^ key for byte in pocket[2:]) == wide("Secret")
