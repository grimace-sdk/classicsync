import codecs
import struct
from dataclasses import dataclass

from ..backup.compound import SIGNATURE, CompoundFileError, CompoundFileReader, Stream
from .cab import CabArchive

TABLE_PREFIX = "!"
ENCODED_TABLE_PREFIX = 0x4840
ENCODED_PAIR_START = 0x3800
ENCODED_SINGLE_START = 0x4800
STREAM_NAME_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz._"

LONG_STRING_REFERENCES = 0x80000000

COLUMN_TYPE_STRING = 0x0800
COLUMN_TYPE_NON_BINARY = 0x0400
COLUMN_TYPE_VALID = 0x0100
COLUMN_TYPE_NULLABLE = 0x1000
COLUMN_TYPE_SIZE_MASK = 0x00FF

INTEGER16_BIAS = 0x8000
INTEGER32_BIAS = 0x80000000

SYSTEM_STRING_COLUMN = COLUMN_TYPE_STRING | COLUMN_TYPE_NON_BINARY | COLUMN_TYPE_VALID
SYSTEM_TABLE_COLUMNS = {
    "_Tables": [("Name", SYSTEM_STRING_COLUMN)],
    "_Columns": [("Table", SYSTEM_STRING_COLUMN), ("Number", COLUMN_TYPE_VALID | 2),
                 ("Name", SYSTEM_STRING_COLUMN), ("Type", COLUMN_TYPE_VALID | 2)],
}


class MsiError(ValueError):
    pass


def is_msi(data):
    return data[:len(SIGNATURE)] == SIGNATURE


def decode_stream_name(name):
    decoded = []
    for character in name:
        value = ord(character)
        if value == ENCODED_TABLE_PREFIX:
            decoded.append(TABLE_PREFIX)
        elif ENCODED_SINGLE_START <= value < ENCODED_TABLE_PREFIX:
            decoded.append(STREAM_NAME_ALPHABET[value - ENCODED_SINGLE_START])
        elif ENCODED_PAIR_START <= value < ENCODED_SINGLE_START:
            value -= ENCODED_PAIR_START
            decoded.append(STREAM_NAME_ALPHABET[value & 0x3F])
            decoded.append(STREAM_NAME_ALPHABET[(value >> 6) & 0x3F])
        else:
            decoded.append(character)
    return "".join(decoded)


def encode_stream_name(name, is_table=False):
    encoded = [chr(ENCODED_TABLE_PREFIX)] if is_table else []
    position = 0
    while position < len(name):
        first = STREAM_NAME_ALPHABET.find(name[position])
        if first < 0:
            encoded.append(name[position])
            position += 1
            continue
        second = STREAM_NAME_ALPHABET.find(name[position + 1]) if position + 1 < len(name) else -1
        if second < 0:
            encoded.append(chr(ENCODED_SINGLE_START + first))
            position += 1
        else:
            encoded.append(chr(ENCODED_PAIR_START + first + (second << 6)))
            position += 2
    return "".join(encoded)


def python_codec(codepage):
    if codepage in (0, 65001):
        return "utf-8" if codepage else "cp1252"
    name = f"cp{codepage}"
    try:
        codecs.lookup(name)
    except LookupError:
        return "cp1252"
    return name


def parse_string_pool(pool, data):
    if len(pool) < 4:
        raise MsiError("string pool is too short")
    header = struct.unpack_from("<I", pool, 0)[0]
    codec = python_codec(header & ~LONG_STRING_REFERENCES & 0xFFFFFF)
    reference_size = 3 if header & LONG_STRING_REFERENCES else 2
    words = struct.unpack_from(f"<{(len(pool) - 4) // 2}H", pool, 4)
    strings = [None]
    data_offset = 0
    index = 0
    while index + 1 < len(words):
        length, reference_count = words[index], words[index + 1]
        if length == 0 and reference_count == 0:
            strings.append(None)
            index += 2
            continue
        if length == 0:
            length = (words[index + 3] << 16) | words[index + 2]
            index += 4
        else:
            index += 2
        raw = data[data_offset:data_offset + length]
        data_offset += length
        strings.append(raw.decode(codec, errors="replace"))
    return strings, reference_size, codec


def column_size(column_type, reference_size):
    if column_type & ~COLUMN_TYPE_NULLABLE == COLUMN_TYPE_STRING | COLUMN_TYPE_VALID:
        return 2
    if column_type & COLUMN_TYPE_STRING:
        return reference_size
    if column_type & COLUMN_TYPE_SIZE_MASK <= 2:
        return 2
    return 4


@dataclass
class MsiFile:
    key: str
    component: str
    name: str
    directory: str
    size: int
    sequence: int


class MsiDatabase:
    def __init__(self, data):
        try:
            root = CompoundFileReader(data).root()
        except CompoundFileError as error:
            raise MsiError(str(error)) from error
        self.tables_streams = {}
        self.streams = {}
        for entry in root:
            if not isinstance(entry, Stream):
                continue
            decoded = decode_stream_name(entry.name)
            if decoded.startswith(TABLE_PREFIX):
                self.tables_streams[decoded[1:]] = entry.data
            else:
                self.streams[decoded] = entry.data
        if "_StringPool" not in self.tables_streams or "_StringData" not in self.tables_streams:
            raise MsiError("no MSI string pool")
        self.strings, self.reference_size, self.codec = parse_string_pool(
            self.tables_streams["_StringPool"], self.tables_streams["_StringData"])
        self.columns = dict(SYSTEM_TABLE_COLUMNS)
        definitions = {}
        for row in self.read_rows("_Columns"):
            definitions.setdefault(row["Table"], []).append((row["Number"], row["Name"], row["Type"]))
        for table, columns in definitions.items():
            self.columns[table] = [(name, column_type) for _, name, column_type in sorted(columns)]
        self.table_names = [row["Name"] for row in self.read_rows("_Tables")]

    def string(self, reference):
        if 0 < reference < len(self.strings):
            return self.strings[reference]
        return None

    def read_rows(self, table):
        columns = self.columns.get(table)
        if columns is None:
            raise MsiError(f"no table {table}")
        data = self.tables_streams.get(table, b"")
        sizes = [column_size(column_type, self.reference_size) for _, column_type in columns]
        row_size = sum(sizes)
        row_count = len(data) // row_size if row_size else 0
        values = []
        offset = 0
        for (_, column_type), size in zip(columns, sizes):
            column_values = []
            for _ in range(row_count):
                raw = int.from_bytes(data[offset:offset + size], "little")
                offset += size
                if column_type & COLUMN_TYPE_STRING:
                    column_values.append(self.string(raw))
                elif raw == 0:
                    column_values.append(None)
                elif size == 2:
                    column_values.append(raw - INTEGER16_BIAS)
                else:
                    column_values.append(raw - INTEGER32_BIAS)
            values.append(column_values)
        names = [name for name, _ in columns]
        return [dict(zip(names, row)) for row in zip(*values)]

    def directory_paths(self):
        if "Directory" not in self.columns:
            return {}
        rows = {row["Directory"]: row for row in self.read_rows("Directory")}
        paths = {}

        def resolve(key, depth=0):
            if key in paths:
                return paths[key]
            row = rows.get(key)
            if row is None or depth > 64:
                return ""
            parent_key = row["Directory_Parent"]
            target = long_name((row["DefaultDir"] or "").split(":")[0])
            if not parent_key or parent_key == key:
                path = ""
            else:
                parent = resolve(parent_key, depth + 1)
                if target in ("", "."):
                    path = parent or key.split(".")[0]
                else:
                    path = f"{parent}/{target}" if parent else target
            paths[key] = path
            return path

        for key in rows:
            resolve(key)
        return paths

    def files(self):
        if "File" not in self.columns:
            return []
        components = {}
        if "Component" in self.columns:
            components = {row["Component"]: row["Directory_"] for row in self.read_rows("Component")}
        directories = self.directory_paths()
        files = []
        for row in self.read_rows("File"):
            directory = directories.get(components.get(row["Component_"]), "")
            files.append(MsiFile(row["File"], row["Component_"], long_name(row["FileName"] or row["File"]),
                                 directory, row["FileSize"] or 0, row["Sequence"] or 0))
        return files

    def cabinets(self):
        if "Media" not in self.columns:
            return []
        cabinets = []
        for row in self.read_rows("Media"):
            name = row["Cabinet"]
            if name and name.startswith("#") and name[1:] in self.streams:
                cabinets.append(self.streams[name[1:]])
        return cabinets

    def members(self):
        by_key = {file.key: file for file in self.files()}
        for cabinet_data in self.cabinets():
            archive = CabArchive(cabinet_data)
            for entry in archive.files:
                file = by_key.get(entry.name)
                if file is None:
                    continue
                path = f"{file.directory}/{file.name}" if file.directory else file.name
                yield path, archive.read(entry)


def long_name(name):
    return name.split("|")[-1]


def read_msi(source):
    if isinstance(source, (bytes, bytearray, memoryview)):
        return MsiDatabase(bytes(source))
    with open(source, "rb") as handle:
        return MsiDatabase(handle.read())
