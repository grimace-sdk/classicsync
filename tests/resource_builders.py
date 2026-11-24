import struct

from classicsync.backup.compound import Storage, write_compound_file
from classicsync.formats.msi import encode_stream_name

SECTION_RVA = 0x1000
SECTION_FILE_OFFSET = 0x200
OPTIONAL_HEADER_SIZE = 224


def utf16(text):
    return text.encode("utf-16-le") + b"\0\0"


def pad_dword(data):
    return data + bytes(-len(data) % 4)


def string_block(strings):
    data = b""
    for index in range(16):
        text = strings.get(index, "")
        data += struct.pack("<H", len(text)) + text.encode("utf-16-le")
    return data


def dialog(caption, controls, extended=False):
    style = 0x40
    if extended:
        data = struct.pack("<HHIIIHhhhh", 1, 0xFFFF, 0, 0, style, len(controls), 0, 0, 100, 50)
    else:
        data = struct.pack("<IIHhhhh", style, 0, len(controls), 0, 0, 100, 50)
    data += b"\0\0" + b"\0\0" + utf16(caption)
    data += (struct.pack("<HHBB", 8, 400, 0, 1) if extended else struct.pack("<H", 8)) + utf16("MS Shell Dlg")
    for control_id, text in controls:
        data = pad_dword(data)
        if extended:
            data += struct.pack("<IIIhhhhI", 0, 0, 0, 0, 0, 10, 10, control_id & 0xFFFFFFFF)
        else:
            data += struct.pack("<IIhhhhH", 0, 0, 0, 0, 10, 10, control_id & 0xFFFF)
        data += struct.pack("<HH", 0xFFFF, 0x0082) + utf16(text) + struct.pack("<H", 0)
    return data


def menu(items):
    def level(entries):
        data = b""
        for index, (text, value) in enumerate(entries):
            flags = 0x80 if index == len(entries) - 1 else 0
            if isinstance(value, list):
                data += struct.pack("<H", flags | 0x10) + utf16(text) + level(value)
            else:
                data += struct.pack("<HH", flags, value) + utf16(text)
        return data
    return struct.pack("<HH", 0, 0) + level(items)


def menu_ex(items):
    def level(entries):
        data = b""
        for index, (text, value) in enumerate(entries):
            flags = 0x80 if index == len(entries) - 1 else 0
            is_popup = isinstance(value, list)
            item_id = 0 if is_popup else value
            data += pad_dword(struct.pack("<IIIH", 0, 0, item_id, flags | (0x01 if is_popup else 0)) + utf16(text))
            if is_popup:
                data += struct.pack("<I", 0) + level(value)
        return data
    return struct.pack("<HHI", 1, 4, 0) + level(items)


def message_table(messages):
    entries = b""
    for text in messages.values():
        encoded = pad_dword(utf16(text))
        entries += struct.pack("<HH", 4 + len(encoded), 1) + encoded
    identifiers = sorted(messages)
    return struct.pack("<IIII", 1, identifiers[0], identifiers[-1], 16) + entries


def resource_section(resources):
    tree = {}
    for type_id, name, language, data in resources:
        tree.setdefault(type_id, {}).setdefault(name, {})[language] = data
    directories = []
    data_entries = []

    def directory(children, depth):
        index = len(directories)
        directories.append(None)
        entries = []
        for key in sorted(children):
            if depth == 2:
                data_entries.append(children[key])
                entries.append((key, ("data", len(data_entries) - 1)))
            else:
                entries.append((key, ("directory", directory(children[key], depth + 1))))
        directories[index] = entries
        return index

    directory(tree, 0)
    directory_offsets = []
    offset = 0
    for entries in directories:
        directory_offsets.append(offset)
        offset += 16 + 8 * len(entries)
    data_entry_start = offset
    data_start = data_entry_start + 16 * len(data_entries)
    data_offsets = []
    blob = b""
    for data in data_entries:
        data_offsets.append(data_start + len(blob))
        blob += pad_dword(data)
    section = b""
    for entries in directories:
        section += struct.pack("<IIHHHH", 0, 0, 0, 0, 0, len(entries))
        for key, (kind, target) in entries:
            if kind == "directory":
                section += struct.pack("<II", key, 0x80000000 | directory_offsets[target])
            else:
                section += struct.pack("<II", key, data_entry_start + 16 * target)
    for index, data in enumerate(data_entries):
        section += struct.pack("<IIII", SECTION_RVA + data_offsets[index], len(data), 0, 0)
    return section + blob


def build_pe(resources):
    section = resource_section(resources)
    raw_size = len(section) + (-len(section) % 0x200)
    dos_header = b"MZ" + bytes(0x3A) + struct.pack("<I", 0x40)
    file_header = b"PE\0\0" + struct.pack("<HHIIIHH", 0x14C, 1, 0, 0, 0, OPTIONAL_HEADER_SIZE, 0x0102)
    optional = bytearray(OPTIONAL_HEADER_SIZE)
    struct.pack_into("<H", optional, 0, 0x10B)
    struct.pack_into("<II", optional, 96 + 2 * 8, SECTION_RVA, len(section))
    section_header = b".rsrc\0\0\0" + struct.pack("<IIIIIIHHI", len(section), SECTION_RVA, raw_size,
                                                    SECTION_FILE_OFFSET, 0, 0, 0, 0, 0x40000040)
    headers = dos_header + file_header + bytes(optional) + section_header
    return headers.ljust(SECTION_FILE_OFFSET, b"\0") + section.ljust(raw_size, b"\0")


class MsiBuilder:
    def __init__(self, codepage=1252):
        self.codepage = codepage
        self.strings = [""]
        self.tables = {}
        self.streams = {}

    def string_id(self, text):
        if text is None:
            return 0
        if text not in self.strings:
            self.strings.append(text)
        return self.strings.index(text)

    def add_table(self, name, columns, rows):
        self.tables[name] = (columns, rows)

    def encoded_table(self, columns, rows):
        data = b""
        for index, (_, column_type) in enumerate(columns):
            for row in rows:
                value = row[index]
                if column_type & 0x0800:
                    data += struct.pack("<H", self.string_id(value))
                elif column_type & 0xFF == 4:
                    data += struct.pack("<I", 0 if value is None else value + 0x80000000)
                else:
                    data += struct.pack("<H", 0 if value is None else value + 0x8000)
        return data

    def build(self):
        root = Storage()
        column_rows = []
        for table, (columns, _) in self.tables.items():
            for number, (name, column_type) in enumerate(columns, 1):
                column_rows.append((table, number, name, column_type))
        streams = {name: self.encoded_table(columns, rows) for name, (columns, rows) in self.tables.items()}
        streams["_Tables"] = self.encoded_table([("Name", 0x0D00)], [(name,) for name in self.tables])
        streams["_Columns"] = self.encoded_table(
            [("Table", 0x0D00), ("Number", 0x0502), ("Name", 0x0D00), ("Type", 0x0502)], column_rows)
        pool = struct.pack("<I", self.codepage)
        string_data = b""
        for text in self.strings[1:]:
            encoded = text.encode(f"cp{self.codepage}")
            if len(encoded) > 0xFFFF:
                pool += struct.pack("<HHHH", 0, 1, len(encoded) & 0xFFFF, len(encoded) >> 16)
            else:
                pool += struct.pack("<HH", len(encoded), 1)
            string_data += encoded
        streams["_StringPool"] = pool
        streams["_StringData"] = string_data
        for name, data in streams.items():
            root.set_stream(encode_stream_name(name, is_table=True), data)
        for name, data in self.streams.items():
            root.set_stream(encode_stream_name(name), data)
        return write_compound_file(root)


STRING_COLUMN = 0x0D00
NULLABLE_STRING_COLUMN = 0x1D00
SHORT_COLUMN = 0x0502
LONG_COLUMN = 0x0104


def build_msi(files, product_name, version, language, cabinet, codepage=1252, long_text=None):
    builder = MsiBuilder(codepage)
    properties = [("ProductName", product_name), ("ProductVersion", version), ("ProductLanguage", str(language))]
    if long_text:
        properties.append(("LongText", long_text))
    builder.add_table("Property", [("Property", STRING_COLUMN), ("Value", STRING_COLUMN)], properties)
    builder.add_table("Directory", [("Directory", STRING_COLUMN), ("Directory_Parent", NULLABLE_STRING_COLUMN),
                                    ("DefaultDir", STRING_COLUMN)],
                      [("TARGETDIR", None, "SourceDir"), ("ProgramFilesFolder", "TARGETDIR", "."),
                       ("INSTALLDIR", "ProgramFilesFolder", "PROGRA~1|Example Product")])
    builder.add_table("Component", [("Component", STRING_COLUMN), ("Directory_", STRING_COLUMN)],
                      [("Main", "INSTALLDIR")])
    builder.add_table("File", [("File", STRING_COLUMN), ("Component_", STRING_COLUMN), ("FileName", STRING_COLUMN),
                               ("FileSize", LONG_COLUMN), ("Sequence", SHORT_COLUMN)],
                      [(key, "Main", name, len(data), index + 1) for index, (key, name, data) in enumerate(files)])
    builder.add_table("Media", [("DiskId", SHORT_COLUMN), ("LastSequence", SHORT_COLUMN),
                                ("Cabinet", NULLABLE_STRING_COLUMN)], [(1, len(files), "#product.cab")])
    builder.streams["product.cab"] = cabinet
    return builder.build()
