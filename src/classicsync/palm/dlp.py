import struct
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum

from ..sync.device import DeviceSourceError

FIRST_ARGUMENT = 0x20
ARGUMENT_ID_MASK = 0x3F
SHORT_ARGUMENT = 0x80
LONG_ARGUMENT = 0x40
TINY_MAX = 0xFF
SHORT_MAX = 0xFFFF
RESPONSE_FLAG = 0x80

HOST_DLP_VERSION = (1, 3)
DATE = struct.Struct(">HBBBBBx")
DB_INFO_FIXED = struct.Struct(">BBH4s4sHI8s8s8sH")

LIST_RAM = 0x80
LIST_ROM = 0x40
LIST_MULTIPLE = 0x20
LIST_MORE = 0x80

DB_ATTRIBUTE_RESOURCE = 0x0001
DB_ATTRIBUTE_READ_ONLY = 0x0002
DB_ATTRIBUTE_BACKUP = 0x0008
DB_ATTRIBUTE_HIDDEN = 0x0100
DB_ATTRIBUTE_OPEN = 0x8000
DB_MISC_EXCLUDE_FROM_SYNC = 0x80
DB_MISC_RAM_BASED = 0x40

END_OF_SYNC_NORMAL = 0
END_OF_SYNC_OUT_OF_MEMORY = 1
END_OF_SYNC_CANCELLED = 2
END_OF_SYNC_OTHER = 3

OPEN_READ = 0x80
OPEN_WRITE = 0x40
OPEN_EXCLUSIVE = 0x20
OPEN_SECRET = 0x10
CLOSE_UPDATE_BACKUP_DATE = 0x80
READ_ALL = 0xFFFF
RECORD_HEADER = struct.Struct(">IHHBB")
RESOURCE_HEADER = struct.Struct(">4sHHH")
USER_MODIFY_ALL = 0xFF
WRITE_RECORD_FLAGS = 0x80
DB_ATTRIBUTE_OPEN_MASK = 0x8000


class DlpCommand(IntEnum):
    READ_USER_INFO = 0x10
    WRITE_USER_INFO = 0x11
    READ_SYS_INFO = 0x12
    GET_SYS_DATE_TIME = 0x13
    SET_SYS_DATE_TIME = 0x14
    READ_STORAGE_INFO = 0x15
    READ_DB_LIST = 0x16
    OPEN_DB = 0x17
    CREATE_DB = 0x18
    CLOSE_DB = 0x19
    DELETE_DB = 0x1A
    READ_APP_BLOCK = 0x1B
    WRITE_APP_BLOCK = 0x1C
    READ_SORT_BLOCK = 0x1D
    WRITE_SORT_BLOCK = 0x1E
    READ_NEXT_MODIFIED_RECORD = 0x1F
    READ_RECORD = 0x20
    WRITE_RECORD = 0x21
    DELETE_RECORD = 0x22
    READ_RESOURCE = 0x23
    WRITE_RESOURCE = 0x24
    DELETE_RESOURCE = 0x25
    CLEAN_UP_DATABASE = 0x26
    RESET_SYNC_FLAGS = 0x27
    CALL_APPLICATION = 0x28
    RESET_SYSTEM = 0x29
    ADD_SYNC_LOG_ENTRY = 0x2A
    READ_OPEN_DB_INFO = 0x2B
    MOVE_CATEGORY = 0x2C
    OPEN_CONDUIT = 0x2E
    END_OF_SYNC = 0x2F
    RESET_RECORD_INDEX = 0x30
    READ_RECORD_ID_LIST = 0x31
    READ_APP_PREFERENCE = 0x34
    WRITE_APP_PREFERENCE = 0x35
    READ_NET_SYNC_INFO = 0x36
    WRITE_NET_SYNC_INFO = 0x37
    READ_FEATURE = 0x38
    FIND_DB = 0x39


class DlpStatus(IntEnum):
    NONE = 0x00
    SYSTEM = 0x01
    ILLEGAL_REQUEST = 0x02
    OUT_OF_MEMORY = 0x03
    INVALID_PARAMETER = 0x04
    NOT_FOUND = 0x05
    NONE_OPEN = 0x06
    ALREADY_OPEN = 0x07
    TOO_MANY_OPEN = 0x08
    ALREADY_EXISTS = 0x09
    CANT_OPEN = 0x0A
    RECORD_DELETED = 0x0B
    RECORD_BUSY = 0x0C
    NOT_SUPPORTED = 0x0D
    UNUSED = 0x0E
    READ_ONLY = 0x0F
    NOT_ENOUGH_SPACE = 0x10
    LIMIT_EXCEEDED = 0x11
    CANCEL_SYNC = 0x12
    BAD_WRAPPER = 0x13
    ARGUMENT_MISSING = 0x14
    ARGUMENT_SIZE = 0x15


class DlpError(DeviceSourceError):
    def __init__(self, command, status):
        self.command = command
        self.status = status
        try:
            name = DlpStatus(status).name.lower().replace("_", " ")
        except ValueError:
            name = f"error {status:#x}"
        super().__init__(f"{DlpCommand(command).name.lower()}: {name}")


def encode_argument(index, data, short=False):
    identifier = FIRST_ARGUMENT + index
    if len(data) <= TINY_MAX and not short:
        return bytes([identifier, len(data)]) + data
    if len(data) <= SHORT_MAX:
        return struct.pack(">BBH", identifier | SHORT_ARGUMENT, 0, len(data)) + data
    return struct.pack(">BBI", identifier | LONG_ARGUMENT, 0, len(data)) + data


def encode_request(command, arguments, first=0, short=False):
    encoded = b"".join(encode_argument(first + index, data, short) for index, data in enumerate(arguments))
    return bytes([command, len(arguments)]) + encoded


def decode_response(command, payload):
    reply_command, count, status = struct.unpack_from(">BBH", payload)
    if reply_command != command | RESPONSE_FLAG:
        raise ValueError(f"reply {reply_command:#x} to command {command:#x}")
    if status:
        raise DlpError(command, status)
    arguments = {}
    offset = 4
    for _ in range(count):
        identifier = payload[offset]
        if identifier & SHORT_ARGUMENT:
            length = struct.unpack_from(">H", payload, offset + 2)[0]
            offset += 4
        elif identifier & LONG_ARGUMENT:
            length = struct.unpack_from(">I", payload, offset + 2)[0]
            offset += 6
        else:
            length = payload[offset + 1]
            offset += 2
        arguments[identifier & ARGUMENT_ID_MASK] = payload[offset:offset + length]
        offset += length
    return arguments


def encode_date(moment):
    if moment is None:
        return DATE.pack(0, 0, 0, 0, 0, 0)
    return DATE.pack(moment.year, moment.month, moment.day, moment.hour, moment.minute, moment.second)


def decode_date(raw):
    year, month, day, hour, minute, second = DATE.unpack(raw[:DATE.size])
    if year == 0:
        return None
    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


def rom_version_text(rom_version):
    major = rom_version >> 24 & 0xFF
    minor = rom_version >> 20 & 0x0F
    fix = rom_version >> 16 & 0x0F
    return f"{major}.{minor}.{fix}" if fix else f"{major}.{minor}"


@dataclass
class SysInfo:
    rom_version: int
    locale: int
    product_id: bytes
    dlp_version: tuple
    compatibility_version: tuple
    max_record_size: int

    @property
    def os_version(self):
        return rom_version_text(self.rom_version)


@dataclass
class UserInfo:
    user_id: int
    viewer_id: int
    last_sync_pc: int
    successful_sync: datetime
    last_sync: datetime
    name: str
    password_set: bool

    @property
    def synced(self):
        return self.user_id != 0 or bool(self.name)


@dataclass
class DatabaseInfo:
    name: str
    type: str
    creator: str
    attributes: int
    misc_flags: int
    version: int
    modification_number: int
    created: datetime
    modified: datetime
    backed_up: datetime
    index: int

    @property
    def is_resource(self):
        return bool(self.attributes & DB_ATTRIBUTE_RESOURCE)

    @property
    def in_ram(self):
        return bool(self.misc_flags & DB_MISC_RAM_BASED)


def parse_sys_info(arguments):
    first = arguments[FIRST_ARGUMENT]
    rom_version, locale, _pad, product_length = struct.unpack_from(">IIBB", first)
    product_id = first[10:10 + product_length]
    dlp_version = compatibility = (1, 0)
    max_record_size = SHORT_MAX
    second = arguments.get(FIRST_ARGUMENT + 1)
    if second and len(second) >= 12:
        dlp_major, dlp_minor, compatibility_major, compatibility_minor, max_record_size = struct.unpack_from(">HHHHI", second)
        dlp_version = (dlp_major, dlp_minor)
        compatibility = (compatibility_major, compatibility_minor)
    return SysInfo(rom_version, locale, product_id, dlp_version, compatibility, max_record_size)


def parse_user_info(arguments):
    data = arguments[FIRST_ARGUMENT]
    user_id, viewer_id, last_sync_pc = struct.unpack_from(">III", data)
    name_length, password_length = data[28], data[29]
    name = data[30:30 + name_length].split(b"\0")[0].decode("latin-1")
    return UserInfo(user_id, viewer_id, last_sync_pc, decode_date(data[12:20]), decode_date(data[20:28]), name, password_length > 0)


def parse_database_info(entry):
    (_size, misc_flags, attributes, kind, creator, version, modification_number, created, modified, backed_up,
     index) = DB_INFO_FIXED.unpack_from(entry)
    name = entry[DB_INFO_FIXED.size:].split(b"\0")[0].decode("latin-1")
    return DatabaseInfo(name, kind.decode("latin-1"), creator.decode("latin-1"), attributes, misc_flags, version,
                        modification_number, decode_date(created), decode_date(modified), decode_date(backed_up), index)


def parse_database_list(arguments):
    block = arguments[FIRST_ARGUMENT]
    last_index, flags, count = struct.unpack_from(">HBB", block)
    entries = []
    offset = 4
    for _ in range(count):
        size = block[offset]
        entries.append(parse_database_info(block[offset:offset + size]))
        offset += size
    return entries, last_index, bool(flags & LIST_MORE)


class DlpClient:
    def __init__(self, link):
        self.link = link

    async def call(self, command, *arguments, first=0, short=False):
        payload = await self.link.request(encode_request(command, arguments, first, short))
        return decode_response(command, payload)

    async def read_sys_info(self, host_version=HOST_DLP_VERSION):
        return parse_sys_info(await self.call(DlpCommand.READ_SYS_INFO, struct.pack(">HH", *host_version)))

    async def read_user_info(self):
        return parse_user_info(await self.call(DlpCommand.READ_USER_INFO))

    async def read_database_list(self, ram=True, rom=False, card=0):
        flags = (LIST_RAM if ram else 0) | (LIST_ROM if rom else 0) | LIST_MULTIPLE
        databases = []
        start = 0
        while True:
            try:
                arguments = await self.call(DlpCommand.READ_DB_LIST, struct.pack(">BBH", flags, card, start))
            except DlpError as error:
                if error.status == DlpStatus.NOT_FOUND:
                    break
                raise
            entries, last_index, more = parse_database_list(arguments)
            databases.extend(entries)
            if not more or not entries:
                break
            start = last_index + 1
        return databases

    async def end_of_sync(self, status=END_OF_SYNC_NORMAL):
        await self.call(DlpCommand.END_OF_SYNC, struct.pack(">H", status))

    async def open_database(self, name, mode=OPEN_READ | OPEN_SECRET, card=0):
        arguments = await self.call(DlpCommand.OPEN_DB, struct.pack(">BB", card, mode) + name.encode("latin-1") + b"\0")
        return arguments[FIRST_ARGUMENT][0]

    async def close_database(self, handle, update_backup_date=False):
        if update_backup_date:
            await self.call(DlpCommand.CLOSE_DB, struct.pack(">BB", handle, CLOSE_UPDATE_BACKUP_DATE), first=2)
        else:
            await self.call(DlpCommand.CLOSE_DB, bytes([handle]))

    async def record_count(self, handle):
        return struct.unpack_from(">H", (await self.call(DlpCommand.READ_OPEN_DB_INFO, bytes([handle])))[FIRST_ARGUMENT])[0]

    async def _read_block(self, command, handle):
        try:
            arguments = await self.call(command, struct.pack(">BBHH", handle, 0, 0, READ_ALL))
        except DlpError as error:
            if error.status == DlpStatus.NOT_FOUND:
                return b""
            raise
        data = arguments[FIRST_ARGUMENT]
        size = struct.unpack_from(">H", data)[0]
        return data[2:2 + size]

    async def read_app_block(self, handle):
        return await self._read_block(DlpCommand.READ_APP_BLOCK, handle)

    async def read_sort_block(self, handle):
        return await self._read_block(DlpCommand.READ_SORT_BLOCK, handle)

    async def read_record_by_index(self, handle, index):
        arguments = await self.call(DlpCommand.READ_RECORD, struct.pack(">BBHHH", handle, 0, index, 0, READ_ALL), first=1)
        data = arguments[FIRST_ARGUMENT]
        record_id, _index, size, attributes, category = RECORD_HEADER.unpack_from(data)
        return record_id, attributes, category, data[RECORD_HEADER.size:RECORD_HEADER.size + size]

    async def read_resource_by_index(self, handle, index):
        arguments = await self.call(DlpCommand.READ_RESOURCE, struct.pack(">BBHHH", handle, 0, index, 0, READ_ALL))
        data = arguments[FIRST_ARGUMENT]
        kind, resource_id, _index, size = RESOURCE_HEADER.unpack_from(data)
        return kind.decode("latin-1"), resource_id, data[RESOURCE_HEADER.size:RESOURCE_HEADER.size + size]

    async def write_user_info(self, user_id, viewer_id, last_sync_pc, last_sync, name):
        encoded = name.encode("latin-1") + b"\0"
        await self.call(DlpCommand.WRITE_USER_INFO, struct.pack(">III", user_id, viewer_id, last_sync_pc) + encode_date(last_sync)
                        + struct.pack(">BB", USER_MODIFY_ALL, len(encoded)) + encoded)

    async def delete_database(self, name, card=0):
        try:
            await self.call(DlpCommand.DELETE_DB, struct.pack(">BB", card, 0) + name.encode("latin-1") + b"\0")
        except DlpError as error:
            if error.status != DlpStatus.NOT_FOUND:
                raise
            return False
        return True

    async def create_database(self, name, creator, kind, attributes, version, card=0):
        request = (struct.pack(">4s4sBBHH", creator.encode("latin-1"), kind.encode("latin-1"), card, 0,
                               attributes & ~DB_ATTRIBUTE_OPEN_MASK, version) + name.encode("latin-1") + b"\0")
        return (await self.call(DlpCommand.CREATE_DB, request))[FIRST_ARGUMENT][0]

    async def _write_block(self, command, handle, data):
        await self.call(command, struct.pack(">BBH", handle, 0, len(data)) + data, short=True)

    async def write_app_block(self, handle, data):
        await self._write_block(DlpCommand.WRITE_APP_BLOCK, handle, data)

    async def write_sort_block(self, handle, data):
        await self._write_block(DlpCommand.WRITE_SORT_BLOCK, handle, data)

    async def write_record(self, handle, record_id, attributes, category, data):
        request = struct.pack(">BBIBB", handle, WRITE_RECORD_FLAGS, record_id, attributes, category) + data
        return struct.unpack(">I", (await self.call(DlpCommand.WRITE_RECORD, request, short=True))[FIRST_ARGUMENT][:4])[0]

    async def write_resource(self, handle, kind, resource_id, data):
        request = struct.pack(">BB4sHH", handle, 0, kind.encode("latin-1"), resource_id, len(data)) + data
        await self.call(DlpCommand.WRITE_RESOURCE, request, short=True)

    async def reset_system(self):
        await self.call(DlpCommand.RESET_SYSTEM)

    async def delete_record(self, handle, record_id):
        await self.call(DlpCommand.DELETE_RECORD, struct.pack(">BBI", handle, 0, record_id))

    async def clean_up_database(self, handle):
        await self.call(DlpCommand.CLEAN_UP_DATABASE, bytes([handle]))

    async def reset_sync_flags(self, handle):
        await self.call(DlpCommand.RESET_SYNC_FLAGS, bytes([handle]))
