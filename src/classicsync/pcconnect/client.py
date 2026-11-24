import struct
from dataclasses import dataclass
from enum import IntEnum

from ..rapi.client import RapiError
from ..rapi.structures import FindData

GENERIC_READ = 0x80000000
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
INVALID_HANDLE = 0xFFFFFFFF

PATH_CHARACTERS = 260
REGISTRY_NAME_CHARACTERS = 256
REGISTRY_DATA_MAX = 0x1000
FIND_DATA_FIXED_SIZE = 40
UUID_SIZE = 16
NAND_BASE_SECTOR = 7584
NAND_SECTOR_SIZE = 512


class WilCommand(IntEnum):
    PIM_CREATE_DATABASE = 0x0101
    PIM_OPEN_DATABASE = 0x0102
    PIM_CLOSE_DATABASE = 0x0103
    PIM_GET_DATABASE_INFO = 0x0104
    PIM_SEEK_DATABASE = 0x0105
    PIM_READ_RECORD_PROPS = 0x0106
    PIM_WRITE_RECORD_PROPS = 0x0107
    PIM_DELETE_RECORD = 0x0108
    PIM_BLOB_TO_TIME_ZONE = 0x0109
    PIM_TIME_ZONE_TO_BLOB = 0x010A
    PIM_BLOB_TO_RECURRENCE = 0x010B
    PIM_RECURRENCE_TO_BLOB = 0x010C
    PIM_SET_RECORD_TIME = 0x010D
    MAIL_ENUM_ACCOUNT = 0x0201
    MAIL_ENUM_GROUP = 0x0202
    MAIL_GET_ACCOUNT_SETTING = 0x0203
    MAIL_GET_GROUP_SETTING = 0x0204
    MAIL_OPEN_GROUP = 0x0205
    MAIL_GET_NEXT = 0x0206
    MAIL_SEEK_BEGIN = 0x0207
    MAIL_CLOSE_GROUP = 0x0208
    MAIL_READ_MAIL = 0x0209
    MAIL_WRITE_MAIL = 0x020A
    MAIL_MOVE_MAIL = 0x020B
    MAIL_DELETE_MAIL = 0x020C
    MAIL_GET_ATTACH_FOLDER_NAME = 0x020D
    MAIL_GET_HTML_FOLDER_NAME = 0x020E
    MAIL_DELETE_BUFFER = 0x020F
    MAIL_GET_LAST_ERROR = 0x0210
    MAIL_SET_LAST_ERROR = 0x0211
    MAIL_SET_LAST_MODIFY = 0x0212
    VERSION = 0x0301
    INIT = 0x0302
    INIT_EX = 0x0303
    UNINIT = 0x0304
    GET_ERROR = 0x0305
    FREE_BUFFER = 0x0306
    RAPI_INVOKE = 0x0307
    CHECK_PASSWORD = 0x0308
    CLOSE_HANDLE = 0x0309
    COPY_FILE = 0x030A
    CREATE_DIRECTORY = 0x030B
    CREATE_FILE = 0x030C
    CREATE_PROCESS = 0x030D
    DELETE_FILE = 0x030E
    FIND_ALL_FILES = 0x030F
    FIND_CLOSE = 0x0310
    FIND_FIRST_FILE = 0x0311
    FIND_NEXT_FILE = 0x0312
    GET_FILE_ATTRIBUTES = 0x0313
    GET_FILE_SIZE = 0x0314
    GET_FILE_TIME = 0x0315
    GET_LAST_ERROR = 0x0316
    GET_STORE_INFORMATION = 0x0317
    MOVE_FILE = 0x0318
    READ_FILE = 0x0319
    REMOVE_DIRECTORY = 0x031A
    SET_END_OF_FILE = 0x031B
    SET_FILE_ATTRIBUTES = 0x031C
    SET_FILE_POINTER = 0x031D
    SET_FILE_TIME = 0x031E
    WRITE_FILE = 0x031F
    REG_CLOSE_KEY = 0x0320
    REG_CREATE_KEY = 0x0321
    REG_DELETE_KEY = 0x0322
    REG_DELETE_VALUE = 0x0323
    REG_ENUM_KEY = 0x0324
    REG_ENUM_VALUE = 0x0325
    REG_OPEN_KEY = 0x0326
    REG_QUERY_INFO_KEY = 0x0327
    REG_QUERY_VALUE = 0x0328
    REG_SET_VALUE = 0x0329
    SOFT_RESET = 0x032A
    REBOOT_IN_SAFE_MODE = 0x032B
    REBOOT_IN_SAFE_MODE_EX = 0x032C
    IS_SAFE_MODE = 0x032D
    GET_SAFE_MODE_PARAMETER = 0x032E
    POWER_OFF = 0x032F
    AUTO_POWER_OFF_DISABLE = 0x0330
    AUTO_POWER_OFF_ENABLE = 0x0331
    AUTO_POWER_OFF_GET = 0x0332
    ENABLE_POWER_OFF = 0x0333
    DISABLE_POWER_OFF = 0x0334
    GET_POWER_OFF = 0x0335
    SET_OFF_MASK_TIME = 0x0336
    GET_OFF_MASK_TIME = 0x0337
    GET_SYSTEM_DISK = 0x0338
    GET_INNER_USER_DISK = 0x0339
    FLUSH_REGISTRY = 0x033A
    FLUSH_ALARM = 0x033B
    COSH_EXECUTE = 0x033C
    COSH_SET_NOP_MODE = 0x033D
    COSH_END_APP_CATEGORY = 0x033E
    NAND_OPEN = 0x033F
    NAND_CLOSE = 0x0340
    NAND_GET_INFO = 0x0341
    NAND_READ_SECTOR = 0x0342
    NAND_WRITE_SECTOR = 0x0343
    NAND_GET_ACCESS_FLAG = 0x0344
    NAND_CLEAR_ACCESS_FLAG = 0x0345
    GET_UUID = 0x0346
    GET_SYSTEM_TIME = 0x0347
    GET_LOCAL_TIME = 0x0348
    SET_SYSTEM_TIME = 0x0349
    SET_LOCAL_TIME = 0x034A
    FIND_WINDOW = 0x034B
    POST_MESSAGE = 0x034C
    GET_DISK_FREE_SPACE_EX = 0x034D
    DISPLAY_DIALOG = 0x034E
    DEBUG_LOG = 0x034F
    SET_KICKER = 0x0350
    SET_MONOPOLY = 0x0351
    CHECK_CONNECTION = 0x0352


NO_REPLY_COMMANDS = {WilCommand.SOFT_RESET, WilCommand.REBOOT_IN_SAFE_MODE, WilCommand.REBOOT_IN_SAFE_MODE_EX, WilCommand.POWER_OFF}


def be_u32(*values):
    return struct.pack(f">{len(values)}I", *(value & 0xFFFFFFFF for value in values))


def read_be_u32(data, offset=0):
    return struct.unpack(">I", data[offset:offset + 4])[0]


def encode_wstr(text):
    body = (text + "\0").encode("utf-16-be")
    return struct.pack(">H", len(body)) + body


def optional_wstr(text):
    if text is None:
        return be_u32(0)
    return be_u32(1) + encode_wstr(text)


def decode_wstr(data, offset=0):
    length = struct.unpack(">H", data[offset:offset + 2])[0]
    body = bytes(data[offset + 2:offset + 2 + length])
    text = body[:len(body) & ~1].decode("utf-16-be", errors="replace")
    end = text.find("\0")
    return (text if end < 0 else text[:end]), offset + 2 + length


def encode_filetime(value):
    value = value or 0
    return struct.pack(">II", value & 0xFFFFFFFF, (value >> 32) & 0xFFFFFFFF)


def decode_filetime(data, offset=0):
    low, high = struct.unpack(">II", data[offset:offset + 8])
    return (high << 32) | low


def encode_systemtime(fields):
    return struct.pack(">8H", *fields)


def decode_systemtime(data, offset=0):
    return struct.unpack(">8H", data[offset:offset + 16])


def decode_find_data(data, offset=0):
    attributes = read_be_u32(data, offset)
    creation = decode_filetime(data, offset + 4)
    access = decode_filetime(data, offset + 12)
    write = decode_filetime(data, offset + 20)
    size_high, size_low, oid = struct.unpack(">III", data[offset + 28:offset + 40])
    name, end = decode_wstr(data, offset + FIND_DATA_FIXED_SIZE)
    return FindData(name, attributes, creation, access, write, (size_high << 32) | size_low, oid), end


def format_uuid(data):
    text = bytes(data[:UUID_SIZE]).hex()
    return f"{text[0:8]}-{text[8:12]}-{text[12:16]}-{text[16:20]}-{text[20:32]}"


@dataclass
class NandGeometry:
    sectors: int
    sector_size: int
    raw: bytes


class WilClient:
    def __init__(self, link):
        self.link = link

    async def call(self, command, payload=b""):
        return await self.link.call(command, payload, expect_reply=command not in NO_REPLY_COMMANDS)

    async def version(self):
        return (await self.call(WilCommand.VERSION)).value

    async def uuid(self):
        reply = await self.call(WilCommand.GET_UUID)
        return bytes(reply.data[:UUID_SIZE]) if len(reply.data) >= UUID_SIZE else b""

    async def _disk_name(self, command):
        reply = await self.call(command, be_u32(1, PATH_CHARACTERS))
        return decode_wstr(reply.data)[0] if len(reply.data) >= 2 else ""

    async def system_disk(self):
        return await self._disk_name(WilCommand.GET_SYSTEM_DISK)

    async def inner_user_disk(self):
        return await self._disk_name(WilCommand.GET_INNER_USER_DISK)

    async def create_file(self, path, access=GENERIC_READ, share=0, creation=OPEN_EXISTING, flags=FILE_ATTRIBUTE_NORMAL):
        return await self.call(WilCommand.CREATE_FILE, encode_wstr(path) + be_u32(access, share, creation, flags))

    async def read_file(self, handle, size):
        reply = await self.call(WilCommand.READ_FILE, be_u32(handle, size))
        count = read_be_u32(reply.data) if len(reply.data) >= 4 else 0
        return reply, bytes(reply.data[4:4 + count])

    async def write_file(self, handle, data):
        reply = await self.call(WilCommand.WRITE_FILE, be_u32(handle, len(data)) + bytes(data))
        written = read_be_u32(reply.data) if len(reply.data) >= 4 else len(data)
        return reply, written

    async def close_handle(self, handle):
        return await self.call(WilCommand.CLOSE_HANDLE, be_u32(handle))

    async def find_all_files(self, pattern):
        reply = await self.call(WilCommand.FIND_ALL_FILES, encode_wstr(pattern) + be_u32(0))
        if len(reply.data) < 8:
            return reply, []
        count = read_be_u32(reply.data)
        entries = []
        offset = 8
        for entry_index in range(count):
            entry, offset = decode_find_data(reply.data, offset)
            entries.append(entry)
        return reply, entries

    async def find_first_file(self, pattern):
        reply = await self.call(WilCommand.FIND_FIRST_FILE, encode_wstr(pattern))
        if reply.value in (0, INVALID_HANDLE) or len(reply.data) < FIND_DATA_FIXED_SIZE + 2:
            return reply, None
        return reply, decode_find_data(reply.data)[0]

    async def find_next_file(self, handle):
        reply = await self.call(WilCommand.FIND_NEXT_FILE, be_u32(handle))
        if not reply.value or len(reply.data) < FIND_DATA_FIXED_SIZE + 2:
            return reply, None
        return reply, decode_find_data(reply.data)[0]

    async def find_close(self, handle):
        return await self.call(WilCommand.FIND_CLOSE, be_u32(handle))

    async def get_file_attributes(self, path):
        return await self.call(WilCommand.GET_FILE_ATTRIBUTES, encode_wstr(path))

    async def set_file_attributes(self, path, attributes):
        return await self.call(WilCommand.SET_FILE_ATTRIBUTES, encode_wstr(path) + be_u32(attributes))

    async def get_file_size(self, handle):
        reply = await self.call(WilCommand.GET_FILE_SIZE, be_u32(handle, 1))
        high = read_be_u32(reply.data) if len(reply.data) >= 4 else 0
        return reply, high

    async def get_file_times(self, handle):
        reply = await self.call(WilCommand.GET_FILE_TIME, be_u32(handle))
        if len(reply.data) < 24:
            return reply, (0, 0, 0)
        return reply, tuple(decode_filetime(reply.data, offset) for offset in (0, 8, 16))

    async def set_file_times(self, handle, creation, access, write):
        payload = be_u32(handle) + encode_filetime(creation) + encode_filetime(access) + encode_filetime(write)
        return await self.call(WilCommand.SET_FILE_TIME, payload)

    async def move_file(self, source, destination):
        return await self.call(WilCommand.MOVE_FILE, encode_wstr(source) + encode_wstr(destination))

    async def copy_file(self, source, destination, fail_if_exists=False):
        return await self.call(WilCommand.COPY_FILE, encode_wstr(source) + encode_wstr(destination) + be_u32(int(fail_if_exists)))

    async def delete_file(self, path):
        return await self.call(WilCommand.DELETE_FILE, encode_wstr(path))

    async def create_directory(self, path):
        return await self.call(WilCommand.CREATE_DIRECTORY, encode_wstr(path))

    async def remove_directory(self, path):
        return await self.call(WilCommand.REMOVE_DIRECTORY, encode_wstr(path))

    async def get_store_information(self):
        reply = await self.call(WilCommand.GET_STORE_INFORMATION)
        if len(reply.data) < 8:
            return reply, 0, 0
        store_size, free_size = struct.unpack(">II", reply.data[:8])
        return reply, store_size, free_size

    async def create_process(self, application, command_line=None, creation_flags=0):
        reply = await self.call(WilCommand.CREATE_PROCESS, encode_wstr(application) + optional_wstr(command_line) + be_u32(creation_flags))
        information = struct.unpack(">4I", reply.data[:16]) if len(reply.data) >= 16 else None
        return reply, information

    async def cosh_execute(self, application, command_line=None):
        return await self.call(WilCommand.COSH_EXECUTE, optional_wstr(application) + optional_wstr(command_line))

    async def reg_open_key(self, root, subkey):
        reply = await self.call(WilCommand.REG_OPEN_KEY, be_u32(root) + optional_wstr(subkey))
        handle = read_be_u32(reply.data) if len(reply.data) >= 4 else 0
        return reply, handle

    async def reg_create_key(self, root, subkey, class_name=None):
        reply = await self.call(WilCommand.REG_CREATE_KEY, be_u32(root) + optional_wstr(subkey) + optional_wstr(class_name or None))
        handle, disposition = struct.unpack(">II", reply.data[:8]) if len(reply.data) >= 8 else (0, 0)
        return reply, handle, disposition

    async def reg_close_key(self, handle):
        return await self.call(WilCommand.REG_CLOSE_KEY, be_u32(handle))

    async def reg_enum_key(self, handle, index, name_characters=REGISTRY_NAME_CHARACTERS):
        reply = await self.call(WilCommand.REG_ENUM_KEY, be_u32(handle, index, 1, name_characters, 0, 0, 0))
        if reply.value or len(reply.data) < 2:
            return reply, None
        return reply, decode_wstr(reply.data)[0]

    async def reg_enum_value(self, handle, index, name_characters=REGISTRY_NAME_CHARACTERS, data_size=REGISTRY_DATA_MAX):
        reply = await self.call(WilCommand.REG_ENUM_VALUE, be_u32(handle, index, 1, name_characters, 1, 1, 1, data_size))
        if reply.value or len(reply.data) < 2:
            return reply, None
        name, offset = decode_wstr(reply.data)
        name_length, value_type, size = struct.unpack(">III", reply.data[offset:offset + 12])
        offset += 12
        return reply, (name, value_type, bytes(reply.data[offset:offset + size]))

    async def reg_query_value(self, handle, name, data_size=REGISTRY_DATA_MAX):
        reply = await self.call(WilCommand.REG_QUERY_VALUE, be_u32(handle) + optional_wstr(name) + be_u32(1, 1, 1, data_size))
        if reply.value or len(reply.data) < 8:
            return reply, None
        value_type, size = struct.unpack(">II", reply.data[:8])
        return reply, (value_type, bytes(reply.data[8:8 + size]))

    async def reg_set_value(self, handle, name, value_type, data):
        data = bytes(data)
        payload = be_u32(handle) + optional_wstr(name) + be_u32(value_type, 1, len(data)) + data
        return await self.call(WilCommand.REG_SET_VALUE, payload)

    async def reg_delete_value(self, handle, name):
        return await self.call(WilCommand.REG_DELETE_VALUE, be_u32(handle) + optional_wstr(name))

    async def reg_delete_key(self, handle, subkey):
        return await self.call(WilCommand.REG_DELETE_KEY, be_u32(handle) + optional_wstr(subkey))

    async def get_system_time(self):
        reply = await self.call(WilCommand.GET_SYSTEM_TIME)
        return decode_systemtime(reply.data) if len(reply.data) >= 16 else None

    async def set_system_time(self, fields):
        return await self.call(WilCommand.SET_SYSTEM_TIME, encode_systemtime(fields))

    async def soft_reset(self):
        await self.call(WilCommand.SOFT_RESET)

    async def nand_open(self):
        reply = await self.call(WilCommand.NAND_OPEN)
        if not reply.value:
            raise RapiError("WilNANDOpen", reply.error)
        return reply.value

    async def nand_get_info(self, handle):
        reply = await self.call(WilCommand.NAND_GET_INFO, be_u32(handle))
        sectors, sector_size = struct.unpack(">II", reply.data[:8])
        return NandGeometry(sectors, sector_size, bytes(reply.data))

    async def nand_read_sectors(self, handle, physical_sector, count):
        logical_sector = physical_sector - NAND_BASE_SECTOR
        reply = await self.call(WilCommand.NAND_READ_SECTOR, be_u32(handle, logical_sector, count))
        if len(reply.data) != count * NAND_SECTOR_SIZE:
            raise RapiError(f"WilNANDReadSector {physical_sector}", reply.error)
        return bytes(reply.data)

    async def nand_close(self, handle):
        return await self.call(WilCommand.NAND_CLOSE, be_u32(handle))
