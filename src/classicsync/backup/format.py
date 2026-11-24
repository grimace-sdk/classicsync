import struct
from dataclasses import dataclass, field
from datetime import datetime

BACKUP_SET_INFORMATION = "Backup Set Information"
PEGASUS_DATABASES = "Pegasus Databases"
DIRECTORY_ATTRIBUTES = "Directory Attributes"
DATABASE_INFO = "PegDbaseInfo"
RECORD_PREFIX = "Record_"
TEMPORARY_STREAM = "<#$Temporary_@_Stream$#>"
REGISTRY_FILE = "Restore.fdf"
REGISTRY_DEVICE_PATH = "\\Windows\\Restore.fdf"
RESERVED_NAMES = {name.upper() for name in (BACKUP_SET_INFORMATION, PEGASUS_DATABASES, DIRECTORY_ATTRIBUTES, TEMPORARY_STREAM)}

VERSION_HPC_EXPLORER = 5
VERSION_ACTIVESYNC = 6
READABLE_VERSIONS = (4, 5, 6)

BASE_INFORMATION_SIZE = 0x30
LANGUAGE_BLOCK_SIZE = 8
DEVICE_BLOCK_SIZE = 0x148
OEM_INFO_SIZE = 0x104
DEFAULT_LANGUAGE = 0x409

FILE_HEADER_SIZE = 0x10
DATABASE_INFO_SIZE = 0x78
DATABASE_NAME_CHARS = 32
SORT_ORDER_COUNT = 4
CEDB_VALIDMODTIME = 0x0008

LONG_NAME_THRESHOLD = 32
LONG_NAME_PREFIX = 29

FILE_NAME_ESCAPES = (("!", "?"),)
DATABASE_NAME_ESCAPES = (("\\", "?"),)

ACTIVESYNC_EXCLUDED_DATABASES = ("DB_notify_queue", "DB_notify_events", "\\Cookies", "\\DesktopPositions",
                                 "\\RecycleInfo", "\\SmartFil", "\\URL Cache", "\\UserNotifications")
CE_SERVICES_EXCLUDED_DATABASES = ("\\Cookies", "\\DesktopPositions", "\\RecycleInfo", "\\SmartFil", "\\URL Cache",
                                  "\\UserNotifications")
HPC_EXPLORER_EXCLUDED_DATABASES = ("\\UserNotifications", "\\RecycleInfo")
PIM_DATABASES = ("Appointments Database", "Contacts Database", "Tasks Database", "Categories Database")
EXCLUDED_FILES = ("pegreg.reg", "cereg.reg")
EXECUTABLE_EXTENSIONS = (".exe", ".dll", ".cpl", ".fdf")
SHORTCUT_EXTENSIONS = (".lnk",)
RECYCLE_FOLDER = "Recycled"


class BackupFormatError(Exception):
    pass


def systemtime_to_datetime(fields):
    year, month, _, day, hour, minute, second, millisecond = fields
    try:
        return datetime(year, month, day, hour, minute, second, millisecond * 1000)
    except ValueError:
        return None


def datetime_to_systemtime(moment):
    return (moment.year, moment.month, (moment.weekday() + 1) % 7, moment.day, moment.hour, moment.minute,
            moment.second, moment.microsecond // 1000)


@dataclass
class BackupSetInformation:
    partnership_id: int = 0
    processor_type: int = 0
    store_pages: int = 0
    ram_pages: int = 0
    page_size: int = 0
    store_used: int = 0
    backup_time: tuple = (0,) * 8
    version: int = VERSION_ACTIVESYNC
    os_version: int = 0
    language: int = DEFAULT_LANGUAGE
    not_handheld_pc: int = 0
    processor_level: int = 0
    processor_revision: int = 0
    oem_info: str = ""

    @property
    def os_major(self):
        return self.os_version >> 16 if self.version >= VERSION_ACTIVESYNC else None

    @property
    def os_minor(self):
        return self.os_version & 0xFFFF if self.version >= VERSION_ACTIVESYNC else None

    @property
    def os_build(self):
        return self.os_version if self.version < VERSION_ACTIVESYNC else None

    @property
    def created(self):
        return systemtime_to_datetime(self.backup_time)

    def pack(self):
        base = struct.pack("<6I8H2I", self.partnership_id, self.processor_type, self.store_pages, self.ram_pages,
                           self.page_size, self.store_used, *self.backup_time, self.version, self.os_version)
        if self.version < 5:
            return base
        language_block = struct.pack("<II", self.language, self.not_handheld_pc if self.version >= VERSION_ACTIVESYNC else 0)
        if self.version < VERSION_ACTIVESYNC:
            return base + language_block
        oem = self.oem_info.encode("latin-1", errors="replace")[:OEM_INFO_SIZE - 1]
        device_block = struct.pack("<HH", self.processor_level, self.processor_revision) + oem.ljust(OEM_INFO_SIZE, b"\0")
        return base + language_block + device_block.ljust(DEVICE_BLOCK_SIZE, b"\0")

    @classmethod
    def unpack(cls, data):
        if len(data) < BASE_INFORMATION_SIZE:
            raise BackupFormatError(f"{BACKUP_SET_INFORMATION} is {len(data)} bytes, expected at least {BASE_INFORMATION_SIZE}")
        fields = struct.unpack_from("<6I8H2I", data, 0)
        information = cls(*fields[:6], tuple(fields[6:14]), fields[14], fields[15])
        if information.version not in READABLE_VERSIONS:
            raise BackupFormatError(f"backup set version {information.version} is not one of {READABLE_VERSIONS}")
        if information.version < 5:
            information.language = DEFAULT_LANGUAGE
            return information
        if len(data) < BASE_INFORMATION_SIZE + LANGUAGE_BLOCK_SIZE:
            raise BackupFormatError(f"{BACKUP_SET_INFORMATION} is missing the language block")
        information.language, information.not_handheld_pc = struct.unpack_from("<II", data, BASE_INFORMATION_SIZE)
        if information.version < VERSION_ACTIVESYNC:
            return information
        device_offset = BASE_INFORMATION_SIZE + LANGUAGE_BLOCK_SIZE
        if len(data) < device_offset + DEVICE_BLOCK_SIZE:
            raise BackupFormatError(f"{BACKUP_SET_INFORMATION} is missing the device block")
        information.processor_level, information.processor_revision = struct.unpack_from("<HH", data, device_offset)
        oem = data[device_offset + 4:device_offset + 4 + OEM_INFO_SIZE]
        information.oem_info = oem.split(b"\0")[0].decode("latin-1")
        return information


@dataclass
class FileHeader:
    modified: int
    attributes: int
    name: str

    def pack(self):
        encoded = self.name.encode("utf-16-le")
        return struct.pack("<QIHH", self.modified, self.attributes, len(encoded) // 2, 0) + encoded

    @classmethod
    def unpack(cls, data):
        if len(data) < FILE_HEADER_SIZE:
            raise BackupFormatError(f"file header is {len(data)} bytes, expected at least {FILE_HEADER_SIZE}")
        modified, attributes, name_chars, _ = struct.unpack_from("<QIHH", data, 0)
        end = FILE_HEADER_SIZE + name_chars * 2
        if len(data) < end:
            raise BackupFormatError("file header name is truncated")
        return cls(modified, attributes, data[FILE_HEADER_SIZE:end].decode("utf-16-le", errors="replace"))

    @property
    def size(self):
        return FILE_HEADER_SIZE + len(self.name.encode("utf-16-le"))


def pack_file_stream(header, contents):
    return header.pack() + bytes(contents)


def unpack_file_stream(data):
    header = FileHeader.unpack(data)
    return header, data[header.size:]


@dataclass
class DatabaseInfo:
    name: str
    database_type: int = 0
    flags: int = 0
    record_count: int = 0
    sort_count: int = 0
    size: int = 0
    modified: int = 0
    sort_orders: list = field(default_factory=list)

    def pack(self):
        name = self.name.encode("utf-16-le")[:(DATABASE_NAME_CHARS - 1) * 2].ljust(DATABASE_NAME_CHARS * 2, b"\0")
        sorts = list(self.sort_orders)[:SORT_ORDER_COUNT]
        sorts += [(0, 0)] * (SORT_ORDER_COUNT - len(sorts))
        sort_bytes = b"".join(struct.pack("<II", propid, flags) for propid, flags in sorts)
        return (struct.pack("<I", self.flags) + name
                + struct.pack("<IHHIQ", self.database_type, self.record_count, self.sort_count, self.size, self.modified)
                + sort_bytes)

    @classmethod
    def unpack(cls, data):
        if len(data) < DATABASE_INFO_SIZE:
            raise BackupFormatError(f"{DATABASE_INFO} is {len(data)} bytes, expected {DATABASE_INFO_SIZE}")
        flags = struct.unpack_from("<I", data, 0)[0]
        name = data[4:4 + DATABASE_NAME_CHARS * 2].decode("utf-16-le", errors="replace").split("\0")[0]
        database_type, record_count, sort_count, size, modified = struct.unpack_from("<IHHIQ", data, 0x44)
        sort_orders = [struct.unpack_from("<II", data, 0x58 + index * 8) for index in range(SORT_ORDER_COUNT)]
        return cls(name, database_type, flags, record_count, sort_count, size, modified, sort_orders[:sort_count])


@dataclass
class RecordBlock:
    property_count: int
    block: bytes

    def pack(self):
        return struct.pack("<IH", len(self.block), self.property_count) + self.block

    @classmethod
    def unpack(cls, data):
        if len(data) < 6:
            raise BackupFormatError("record stream is shorter than its header")
        size, property_count = struct.unpack_from("<IH", data, 0)
        if len(data) < 6 + size:
            raise BackupFormatError(f"record stream holds {len(data) - 6} bytes, header says {size}")
        return cls(property_count, bytes(data[6:6 + size]))


def record_stream_name(oid):
    return f"{RECORD_PREFIX}{oid:X}"


def escape_name(name, escapes):
    for original, replacement in escapes:
        name = name.replace(original, replacement)
    return name


def unescape_name(name, escapes):
    for original, replacement in escapes:
        name = name.replace(replacement, original)
    return name


def database_element_name(database_name):
    return escape_name(database_name, DATABASE_NAME_ESCAPES)[:DATABASE_NAME_CHARS]


def database_name_from_element(element_name):
    return unescape_name(element_name, DATABASE_NAME_ESCAPES)


def is_long_element_name(element_name):
    return len(element_name) >= LONG_NAME_PREFIX + 2 and element_name[LONG_NAME_PREFIX] == "~"


def element_name_for(device_name, storage, is_directory, full_name_of):
    escaped = escape_name(device_name, FILE_NAME_ESCAPES)
    if len(device_name) < LONG_NAME_THRESHOLD:
        return escaped
    prefix = escaped[:LONG_NAME_PREFIX] + "~"
    used_letters = set()
    for entry in storage:
        if len(entry.name) != len(prefix) + 1 or entry.name[:len(prefix)].upper() != prefix.upper():
            continue
        used_letters.add(entry.name[-1].upper())
        if full_name_of(entry) is not None and full_name_of(entry).upper() == device_name.upper():
            return entry.name
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if letter not in used_letters:
            return prefix + letter
    raise BackupFormatError(f"too many long names starting {device_name[:LONG_NAME_PREFIX]!r}")


def has_extension(name, extensions):
    return name.lower().endswith(extensions)
