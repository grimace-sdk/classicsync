import struct
from dataclasses import dataclass

from .marshal import decode_wide, encode_wide

CEVT_I2 = 2
CEVT_I4 = 3
CEVT_R8 = 5
CEVT_BOOL = 11
CEVT_UI2 = 18
CEVT_UI4 = 19
CEVT_LPWSTR = 31
CEVT_FILETIME = 64
CEVT_BLOB = 65

CEDB_PROPNOTFOUND = 0x0100
CEDB_PROPDELETE = 0x0200

CEDB_ALLOWREALLOC = 0x0001

CEDB_AUTOINCREMENT = 0x00000001

CEDB_SEEK_CEOID = 0x00000001
CEDB_SEEK_BEGINNING = 0x00000002
CEDB_SEEK_END = 0x00000004
CEDB_SEEK_CURRENT = 0x00000008
CEDB_SEEK_VALUESMALLER = 0x00000010
CEDB_SEEK_VALUEFIRSTEQUAL = 0x00000020
CEDB_SEEK_VALUEGREATER = 0x00000040
CEDB_SEEK_VALUENEXTEQUAL = 0x00000080
VALUE_SEEK_TYPES = {CEDB_SEEK_VALUESMALLER, CEDB_SEEK_VALUEFIRSTEQUAL, CEDB_SEEK_VALUEGREATER, CEDB_SEEK_VALUENEXTEQUAL}

PROPVAL_SIZE = 16


def make_propid(identifier, value_type):
    return (identifier << 16) | value_type


@dataclass
class PropertyValue:
    identifier: int
    value_type: int
    value: object
    flags: int = 0

    @property
    def propid(self):
        return make_propid(self.identifier, self.value_type)

    @property
    def missing(self):
        return bool(self.flags & CEDB_PROPNOTFOUND)


def _inline_value(value_type, raw):
    if value_type == CEVT_I2:
        return struct.unpack("<h", raw[:2])[0]
    if value_type == CEVT_UI2:
        return struct.unpack("<H", raw[:2])[0]
    if value_type == CEVT_I4:
        return struct.unpack("<i", raw[:4])[0]
    if value_type == CEVT_UI4:
        return struct.unpack("<I", raw[:4])[0]
    if value_type == CEVT_BOOL:
        return struct.unpack("<I", raw[:4])[0] != 0
    if value_type == CEVT_R8:
        return struct.unpack("<d", raw)[0]
    if value_type == CEVT_FILETIME:
        return struct.unpack("<Q", raw)[0]
    return raw


def decode_properties(block, count):
    properties = []
    for index in range(count):
        entry = block[index * PROPVAL_SIZE:(index + 1) * PROPVAL_SIZE]
        propid, _, flags = struct.unpack("<IHH", entry[:8])
        raw = entry[8:16]
        value_type = propid & 0xFFFF
        identifier = propid >> 16
        if flags & CEDB_PROPNOTFOUND:
            value = None
        elif value_type == CEVT_LPWSTR:
            offset = struct.unpack("<I", raw[:4])[0]
            value = decode_wide(block[offset:])
        elif value_type == CEVT_BLOB:
            size, offset = struct.unpack("<II", raw)
            value = bytes(block[offset:offset + size])
        else:
            value = _inline_value(value_type, raw)
        properties.append(PropertyValue(identifier, value_type, value, flags))
    return properties


def _inline_bytes(value_type, value):
    if value_type == CEVT_I2:
        return struct.pack("<h", value).ljust(8, b"\0")
    if value_type == CEVT_UI2:
        return struct.pack("<H", value).ljust(8, b"\0")
    if value_type == CEVT_I4:
        return struct.pack("<i", value).ljust(8, b"\0")
    if value_type in (CEVT_UI4, CEVT_BOOL):
        return struct.pack("<I", int(value)).ljust(8, b"\0")
    if value_type == CEVT_R8:
        return struct.pack("<d", value)
    if value_type == CEVT_FILETIME:
        return struct.pack("<Q", value)
    raise ValueError(f"unsupported CEVT type {value_type}")


def encode_properties(properties):
    header = bytearray()
    data_area = bytearray()
    data_start = PROPVAL_SIZE * len(properties)
    for prop in properties:
        flags = prop.flags
        if flags & CEDB_PROPDELETE:
            raw = bytes(8)
        elif prop.value_type == CEVT_LPWSTR:
            raw = struct.pack("<I", data_start + len(data_area)).ljust(8, b"\0")
            data_area += encode_wide(prop.value)
        elif prop.value_type == CEVT_BLOB:
            blob = bytes(prop.value)
            raw = struct.pack("<II", len(blob), data_start + len(data_area))
            data_area += blob
            if len(blob) % 2:
                data_area += b"\0"
        else:
            raw = _inline_bytes(prop.value_type, prop.value)
        header += struct.pack("<IHH", prop.propid, 0, flags) + raw
    return bytes(header + data_area)
