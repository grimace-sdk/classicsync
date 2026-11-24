import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .marshal import decode_wide

FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)

FILE_ATTRIBUTE_READONLY = 0x01
FILE_ATTRIBUTE_HIDDEN = 0x02
FILE_ATTRIBUTE_SYSTEM = 0x04
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_ARCHIVE = 0x20
FILE_ATTRIBUTE_INROM = 0x40
FILE_ATTRIBUTE_NORMAL = 0x80
FILE_ATTRIBUTE_TEMPORARY = 0x100
FILE_ATTRIBUTE_ROMMODULE = 0x2000

FAF_ATTRIBUTES = 0x01
FAF_CREATION_TIME = 0x02
FAF_LASTACCESS_TIME = 0x04
FAF_LASTWRITE_TIME = 0x08
FAF_SIZE_HIGH = 0x10
FAF_SIZE_LOW = 0x20
FAF_OID = 0x40
FAF_NAME = 0x80

PROCESSOR_NAMES = {
    386: "Intel 386", 486: "Intel 486", 586: "Pentium",
    2000: "MIPS R2000", 3000: "MIPS R3000", 4000: "MIPS R4000",
    10003: "Hitachi SH3", 10004: "Hitachi SH3E", 10005: "Hitachi SH4",
    821: "Motorola 821", 103: "SHx SH3", 104: "SHx SH4",
    2577: "StrongARM", 1824: "ARM 720", 2080: "ARM 820", 2336: "ARM 920", 70001: "ARM 7TDMI",
}

PLATFORM_NAMES = {0: "Win32s", 1: "Windows 9x", 2: "Windows NT", 3: "Windows CE"}


def filetime_to_datetime(value):
    if not value:
        return None
    return FILETIME_EPOCH + timedelta(microseconds=value // 10)


def datetime_to_filetime(moment):
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    delta = moment - FILETIME_EPOCH
    return (delta.days * 86400 + delta.seconds) * 10_000_000 + delta.microseconds * 10


@dataclass
class VersionInfo:
    major: int
    minor: int
    build: int
    platform: int
    service_pack: str

    @classmethod
    def parse(cls, data):
        _, major, minor, build, platform = struct.unpack("<5I", data[:20])
        return cls(major, minor, build, platform, decode_wide(data[20:]) if len(data) > 20 else "")

    def __str__(self):
        return f"{self.major}.{self.minor:02d} build {self.build}"


@dataclass
class SystemInfo:
    processor_architecture: int
    page_size: int
    minimum_address: int
    maximum_address: int
    active_processor_mask: int
    processor_count: int
    processor_type: int
    allocation_granularity: int
    processor_level: int
    processor_revision: int

    @classmethod
    def parse(cls, data):
        fields = struct.unpack("<HHIIIIIIIHH", data[:0x24])
        return cls(fields[0], *fields[2:])

    @property
    def processor_name(self):
        return PROCESSOR_NAMES.get(self.processor_type, f"type {self.processor_type}")


@dataclass
class StoreInformation:
    store_size: int
    free_size: int


@dataclass
class MemoryStatus:
    memory_load: int
    total_physical: int
    available_physical: int
    total_page_file: int
    available_page_file: int
    total_virtual: int
    available_virtual: int

    @classmethod
    def parse(cls, data):
        return cls(*struct.unpack("<8I", data[:32])[1:])


@dataclass
class PowerStatus:
    ac_line_status: int
    battery_flag: int
    battery_life_percent: int
    battery_life_time: int
    battery_full_life_time: int
    backup_battery_flag: int
    backup_battery_life_percent: int
    backup_battery_life_time: int
    backup_battery_full_life_time: int

    @classmethod
    def parse(cls, data):
        ac, flag, percent, _, life, full, _, backup_flag, backup_percent, _, backup_life, backup_full = struct.unpack("<BBBBIIBBBBII", data[:24])
        return cls(ac, flag, percent, life, full, backup_flag, backup_percent, backup_life, backup_full)


@dataclass
class FindData:
    name: str
    attributes: int = 0
    creation_time: int = 0
    last_access_time: int = 0
    last_write_time: int = 0
    size: int = 0
    oid: int = 0

    @property
    def is_directory(self):
        return bool(self.attributes & FILE_ATTRIBUTE_DIRECTORY)

    @property
    def modified(self):
        return filetime_to_datetime(self.last_write_time)

    @classmethod
    def parse_find_data(cls, data):
        attributes, creation, access, write, size_high, size_low, oid = struct.unpack("<IQQQIII", data[:0x28])
        return cls(decode_wide(data[0x28:]), attributes, creation, access, write, (size_high << 32) | size_low, oid)


@dataclass
class ProcessInformation:
    process: int
    thread: int
    process_id: int
    thread_id: int
