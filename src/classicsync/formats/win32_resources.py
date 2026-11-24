import struct
from dataclasses import dataclass

RESOURCE_MENU = 4
RESOURCE_DIALOG = 5
RESOURCE_STRING = 6
RESOURCE_MESSAGE_TABLE = 11

DIRECTORY_FLAG = 0x80000000
NAME_FLAG = 0x80000000
RESOURCE_DATA_DIRECTORY = 2
PE32_MAGIC = 0x10B
PE32_PLUS_MAGIC = 0x20B

DIALOG_STYLE_SET_FONT = 0x40
DIALOG_EX_SIGNATURE = 0xFFFF
UNUSED_CONTROL_ID = 0xFFFF

MENU_POPUP = 0x10
MENU_END = 0x80
MENU_SEPARATOR_TYPE = 0x800
MENU_EX_POPUP = 0x01
MENU_EX_END = 0x80

MESSAGE_UNICODE = 0x0001

ENGLISH_LANGUAGES = (0x0409, 0x0809, 0x0000, 0x0400, 0x0800)


class ResourceError(ValueError):
    pass


@dataclass
class Resource:
    type_id: object
    name: object
    language: int
    data: bytes


def is_pe(data):
    if len(data) < 0x40 or data[:2] != b"MZ":
        return False
    header_offset = struct.unpack_from("<I", data, 0x3C)[0]
    return data[header_offset:header_offset + 4] == b"PE\x00\x00"


def section_table(data):
    header_offset = struct.unpack_from("<I", data, 0x3C)[0]
    section_count, optional_size = struct.unpack_from("<H12xH", data, header_offset + 6)
    optional_offset = header_offset + 24
    magic = struct.unpack_from("<H", data, optional_offset)[0]
    if magic == PE32_MAGIC:
        directories_offset = optional_offset + 96
    elif magic == PE32_PLUS_MAGIC:
        directories_offset = optional_offset + 112
    else:
        raise ResourceError(f"unknown optional header magic {magic:#x}")
    resource_rva, resource_size = struct.unpack_from("<II", data, directories_offset + RESOURCE_DATA_DIRECTORY * 8)
    sections = []
    table_offset = optional_offset + optional_size
    for index in range(section_count):
        virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from("<IIII", data, table_offset + index * 40 + 8)
        sections.append((virtual_address, max(virtual_size, raw_size), raw_offset))
    return resource_rva, resource_size, sections


def rva_to_offset(rva, sections):
    for virtual_address, size, raw_offset in sections:
        if virtual_address <= rva < virtual_address + size:
            return raw_offset + rva - virtual_address
    raise ResourceError(f"address {rva:#x} is not in any section")


def read_resources(data):
    if not is_pe(data):
        raise ResourceError("not a PE executable")
    try:
        resource_rva, resource_size, sections = section_table(data)
        if not resource_rva:
            return []
        base = rva_to_offset(resource_rva, sections)
        resources = []
        for type_id, type_offset in directory_entries(data, base, 0):
            for name, name_offset in directory_entries(data, base, type_offset):
                for language, data_entry_offset in directory_entries(data, base, name_offset, leaf=True):
                    data_rva, size = struct.unpack_from("<II", data, base + data_entry_offset)
                    start = rva_to_offset(data_rva, sections)
                    resources.append(Resource(type_id, name, language, data[start:start + size]))
        return resources
    except struct.error as error:
        raise ResourceError(f"truncated resource directory: {error}") from error


def directory_entries(data, base, offset, leaf=False):
    named_count, id_count = struct.unpack_from("<HH", data, base + offset + 12)
    entries = []
    for index in range(named_count + id_count):
        name_field, target = struct.unpack_from("<II", data, base + offset + 16 + index * 8)
        if name_field & NAME_FLAG:
            name_offset = base + (name_field & ~NAME_FLAG)
            length = struct.unpack_from("<H", data, name_offset)[0]
            name = data[name_offset + 2:name_offset + 2 + length * 2].decode("utf-16-le", errors="replace")
        else:
            name = name_field
        is_directory = bool(target & DIRECTORY_FLAG)
        if is_directory == leaf:
            continue
        entries.append((name, target & ~DIRECTORY_FLAG))
    return entries


def read_string(data, offset):
    end = offset
    while end + 1 < len(data) and data[end:end + 2] != b"\0\0":
        end += 2
    return data[offset:end].decode("utf-16-le", errors="replace"), end + 2


def read_name_or_ordinal(data, offset):
    marker = struct.unpack_from("<H", data, offset)[0]
    if marker == 0xFFFF:
        return struct.unpack_from("<H", data, offset + 2)[0], offset + 4
    if marker == 0:
        return "", offset + 2
    return read_string(data, offset)


def align_dword(offset):
    return (offset + 3) & ~3


def parse_string_block(block_id, data):
    strings = {}
    offset = 0
    for index in range(16):
        if offset + 2 > len(data):
            break
        length = struct.unpack_from("<H", data, offset)[0]
        text = data[offset + 2:offset + 2 + length * 2].decode("utf-16-le", errors="replace")
        offset += 2 + length * 2
        if text:
            strings[(block_id - 1) * 16 + index] = text
    return strings


@dataclass
class DialogControl:
    control_id: int
    class_name: object
    text: object


@dataclass
class Dialog:
    caption: str
    font: str
    controls: list


def parse_dialog(data):
    extended = len(data) >= 4 and struct.unpack_from("<HH", data, 0) == (1, DIALOG_EX_SIGNATURE)
    if extended:
        _, _, _, _, style, control_count = struct.unpack_from("<HHIIIH", data, 0)
        offset = 26
    else:
        style, _, control_count = struct.unpack_from("<IIH", data, 0)
        offset = 18
    _, offset = read_name_or_ordinal(data, offset)
    _, offset = read_name_or_ordinal(data, offset)
    caption, offset = read_string(data, offset)
    font = ""
    if style & DIALOG_STYLE_SET_FONT:
        offset += 6 if extended else 2
        font, offset = read_string(data, offset)
    controls = []
    for _ in range(control_count):
        offset = align_dword(offset)
        if offset >= len(data):
            break
        if extended:
            control_id = struct.unpack_from("<I", data, offset + 20)[0]
            offset += 24
        else:
            control_id = struct.unpack_from("<H", data, offset + 16)[0]
            offset += 18
        class_name, offset = read_name_or_ordinal(data, offset)
        text, offset = read_name_or_ordinal(data, offset)
        extra_size = struct.unpack_from("<H", data, offset)[0]
        offset += 2 + extra_size
        controls.append(DialogControl(control_id, class_name, text))
    return Dialog(caption, font, controls)


@dataclass
class MenuItem:
    path: tuple
    item_id: int
    text: str
    is_popup: bool


def parse_menu(data):
    version, header_size = struct.unpack_from("<HH", data, 0)
    items = []
    if version == 1:
        parse_menu_ex_level(data, 4 + header_size, (), items)
    else:
        parse_menu_level(data, 4 + header_size, (), items)
    return items


def parse_menu_level(data, offset, parent_path, items):
    position = 0
    while offset + 2 <= len(data):
        flags = struct.unpack_from("<H", data, offset)[0]
        offset += 2
        item_id = 0
        if not flags & MENU_POPUP:
            item_id = struct.unpack_from("<H", data, offset)[0]
            offset += 2
        text, offset = read_string(data, offset)
        path = parent_path + (position,)
        items.append(MenuItem(path, item_id, text, bool(flags & MENU_POPUP)))
        if flags & MENU_POPUP:
            offset = parse_menu_level(data, offset, path, items)
        position += 1
        if flags & MENU_END:
            break
    return offset


def parse_menu_ex_level(data, offset, parent_path, items):
    position = 0
    while offset + 14 <= len(data):
        _, _, item_id, flags = struct.unpack_from("<IIIH", data, offset)
        text, offset = read_string(data, offset + 14)
        offset = align_dword(offset)
        path = parent_path + (position,)
        items.append(MenuItem(path, item_id, text, bool(flags & MENU_EX_POPUP)))
        if flags & MENU_EX_POPUP:
            offset = parse_menu_ex_level(data, offset + 4, path, items)
        position += 1
        if flags & MENU_EX_END:
            break
    return offset


def parse_message_table(data, codec="cp1252"):
    messages = {}
    block_count = struct.unpack_from("<I", data, 0)[0]
    for block in range(block_count):
        low_id, high_id, entries_offset = struct.unpack_from("<III", data, 4 + block * 12)
        offset = entries_offset
        for message_id in range(low_id, high_id + 1):
            length, flags = struct.unpack_from("<HH", data, offset)
            raw = data[offset + 4:offset + length]
            offset += length
            if flags & MESSAGE_UNICODE:
                text = raw.decode("utf-16-le", errors="replace")
            else:
                text = raw.decode(codec, errors="replace")
            text = text.rstrip("\0")
            if text:
                messages[message_id] = text
    return messages
