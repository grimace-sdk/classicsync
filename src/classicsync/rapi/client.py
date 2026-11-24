import asyncio
import logging
import struct

from . import cedb
from ..i18n import N_, _
from .commands import Command
from .marshal import Reply, Request, decode_wide, encode_wide
from .structures import (
    FAF_ATTRIBUTES, FAF_CREATION_TIME, FAF_LASTACCESS_TIME, FAF_LASTWRITE_TIME, FAF_NAME, FAF_OID, FAF_SIZE_HIGH, FAF_SIZE_LOW,
    FindData, MemoryStatus, PowerStatus, ProcessInformation, StoreInformation, SystemInfo, VersionInfo,
)

log = logging.getLogger("classicsync.rapi")

HKEY_CLASSES_ROOT = 0x80000000
HKEY_CURRENT_USER = 0x80000001
HKEY_LOCAL_MACHINE = 0x80000002
HKEY_USERS = 0x80000003

ROOT_KEYS = {
    "HKCR": HKEY_CLASSES_ROOT, "HKEY_CLASSES_ROOT": HKEY_CLASSES_ROOT,
    "HKCU": HKEY_CURRENT_USER, "HKEY_CURRENT_USER": HKEY_CURRENT_USER,
    "HKLM": HKEY_LOCAL_MACHINE, "HKEY_LOCAL_MACHINE": HKEY_LOCAL_MACHINE,
    "HKU": HKEY_USERS, "HKEY_USERS": HKEY_USERS,
}

REG_NONE = 0
REG_SZ = 1
REG_EXPAND_SZ = 2
REG_BINARY = 3
REG_DWORD = 4
REG_MULTI_SZ = 7

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
CREATE_NEW = 1
CREATE_ALWAYS = 2
OPEN_EXISTING = 3
OPEN_ALWAYS = 4
FILE_ATTRIBUTE_NORMAL = 0x80
INVALID_HANDLE = 0xFFFFFFFF

ERROR_SUCCESS = 0
ERROR_FILE_NOT_FOUND = 2
ERROR_NO_MORE_ITEMS = 259

ERROR_NAMES = {
    2: N_("file not found"), 3: N_("path not found"), 5: N_("access denied"), 6: N_("invalid handle"),
    8: N_("not enough memory"), 18: N_("no more files"), 32: N_("file in use"), 80: N_("file exists"),
    87: N_("invalid parameter"), 112: N_("not enough storage"), 120: N_("not implemented"), 122: N_("buffer too small"),
    123: N_("invalid name"), 145: N_("folder not empty"), 183: N_("already exists"), 234: N_("more data"),
    259: N_("no more items"), 1168: N_("not found"),
}

FIND_ALL_DEFAULT = FAF_ATTRIBUTES | FAF_CREATION_TIME | FAF_LASTACCESS_TIME | FAF_LASTWRITE_TIME | FAF_SIZE_HIGH | FAF_SIZE_LOW | FAF_OID | FAF_NAME
FIND_ALL_FIELDS = [
    (FAF_ATTRIBUTES, "attributes", "<I"),
    (FAF_CREATION_TIME, "creation_time", "<Q"),
    (FAF_LASTACCESS_TIME, "last_access_time", "<Q"),
    (FAF_LASTWRITE_TIME, "last_write_time", "<Q"),
    (FAF_SIZE_HIGH, "size_high", "<I"),
    (FAF_SIZE_LOW, "size_low", "<I"),
    (FAF_OID, "oid", "<I"),
]

READ_CHUNK = 8192
WRITE_CHUNK = 8192
REGISTRY_DATA_MAX = 4096
REGISTRY_NAME_MAX = 256


class RapiError(Exception):
    def __init__(self, operation, code, hresult=False):
        self.operation = operation
        self.code = code
        self.hresult = hresult
        if hresult:
            description = f"HRESULT 0x{code:08x}"
        else:
            description = _(ERROR_NAMES[code]) if code in ERROR_NAMES else _("error {code}").format(code=code)
        super().__init__(f"{operation}: {description}")


class StreamAdapter:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer

    async def readexactly(self, size):
        return await self.reader.readexactly(size)

    def write(self, data):
        self.writer.write(data)

    async def drain(self):
        await self.writer.drain()

    def close(self):
        self.writer.close()


class RapiClient:
    def __init__(self, stream):
        self.stream = stream
        self.lock = asyncio.Lock()
        self.version = None

    @classmethod
    async def open_tcp(cls, host, port):
        reader, writer = await asyncio.open_connection(host, port)
        return cls(StreamAdapter(reader, writer))

    def close(self):
        self.stream.close()

    async def call(self, request):
        async with self.lock:
            log.debug("call %s", Command(request.command).name if request.command in Command._value2member_map_ else hex(request.command))
            try:
                self.stream.write(request.build())
                await self.stream.drain()
                length = struct.unpack("<I", await self.stream.readexactly(4))[0]
                reply = Reply(await self.stream.readexactly(length))
            except asyncio.IncompleteReadError:
                raise ConnectionError(_("device closed the RAPI connection")) from None
        status = reply.u32()
        if status == 1:
            hresult = reply.u32() if reply.remaining >= 4 else 0
            raise RapiError(Command(request.command).name, hresult, hresult=True)
        return reply

    async def call_result(self, request):
        reply = await self.call(request)
        last_error = reply.u32()
        result = reply.u32()
        return reply, last_error, result

    async def _checked(self, request, operation):
        reply, last_error, result = await self.call_result(request)
        if not result:
            raise RapiError(operation, last_error)
        return reply, result

    async def get_version(self):
        reply, last_error, result = await self.call_result(Request(Command.GET_VERSION_EX))
        if not result:
            raise RapiError("CeGetVersionEx", last_error)
        size = reply.u32()
        self.version = VersionInfo.parse(reply.take(size))
        return self.version

    async def get_system_info(self):
        reply = await self.call(Request(Command.GET_SYSTEM_INFO).out_buffer(0x24))
        reply.u32()
        return SystemInfo.parse(reply.out_buffer())

    async def get_store_information(self):
        reply, _ = await self._checked(Request(Command.GET_STORE_INFORMATION).out_buffer(8), "CeGetStoreInformation")
        store_size, free_size = struct.unpack("<II", reply.out_buffer()[:8])
        return StoreInformation(store_size, free_size)

    async def get_memory_status(self):
        request = Request(Command.GLOBAL_MEMORY_STATUS).buffer(struct.pack("<I", 0x20) + bytes(0x1C))
        reply = await self.call(request)
        reply.u32()
        return MemoryStatus.parse(reply.out_buffer())

    async def get_power_status(self, refresh=True):
        reply, _ = await self._checked(Request(Command.GET_SYSTEM_POWER_STATUS_EX).out_buffer(0x18).u32(int(refresh)), "CeGetSystemPowerStatusEx")
        return PowerStatus.parse(reply.out_buffer())

    async def get_special_folder_path(self, csidl, capacity=260):
        reply, last_error, result = await self.call_result(Request(Command.GET_SPECIAL_FOLDER_PATH).u32(csidl).u32(capacity))
        if not result:
            raise RapiError("CeGetSpecialFolderPath", last_error)
        return decode_wide(reply.take(result * 2 + 2))

    async def find_all_files(self, pattern, flags=FIND_ALL_DEFAULT):
        reply = await self.call(Request(Command.FIND_ALL_FILES).string(pattern).u32(flags))
        count = reply.u32()
        entries = []
        for entry_index in range(count):
            name_chars = reply.u32() if flags & FAF_NAME else 0
            values = {}
            for bit, field, layout in FIND_ALL_FIELDS:
                if flags & bit:
                    values[field] = struct.unpack(layout, reply.take(struct.calcsize(layout)))[0]
            name = decode_wide(reply.take(name_chars * 2)) if flags & FAF_NAME else ""
            size = (values.pop("size_high", 0) << 32) | values.pop("size_low", 0)
            entries.append(FindData(name=name, size=size, **values))
        return entries

    async def find_first_file(self, pattern):
        reply, last_error, handle = await self.call_result(Request(Command.FIND_FIRST_FILE).string(pattern))
        if handle == INVALID_HANDLE:
            raise RapiError("CeFindFirstFile", last_error)
        size = reply.u32()
        return handle, FindData.parse_find_data(reply.take(size))

    async def get_file_attributes(self, path):
        _, last_error, result = await self.call_result(Request(Command.GET_FILE_ATTRIBUTES).string(path))
        if result == INVALID_HANDLE:
            raise RapiError(f"CeGetFileAttributes {path}", last_error)
        return result

    async def set_file_attributes(self, path, attributes):
        await self._checked(Request(Command.SET_FILE_ATTRIBUTES).u32(attributes).string(path), f"CeSetFileAttributes {path}")

    async def create_file(self, path, access=GENERIC_READ, share=0, creation=OPEN_EXISTING, flags=FILE_ATTRIBUTE_NORMAL):
        request = Request(Command.CREATE_FILE).u32(access).u32(share).u32(creation).u32(flags).u32(0).string(path)
        _, last_error, handle = await self.call_result(request)
        if handle == INVALID_HANDLE:
            raise RapiError(f"CeCreateFile {path}", last_error)
        return handle

    async def read_file(self, handle, size):
        reply, _ = await self._checked(Request(Command.READ_FILE).u32(handle).u32(1).u32(size).u32(0), "CeReadFile")
        count = reply.u32()
        return reply.take(count)

    async def write_file(self, handle, data):
        reply, _ = await self._checked(Request(Command.WRITE_FILE).u32(handle).u32(1).u32(len(data)).raw(data).u32(0), "CeWriteFile")
        return reply.u32()

    async def close_handle(self, handle):
        await self._checked(Request(Command.CLOSE_HANDLE).u32(handle), "CeCloseHandle")

    async def get_file_size(self, handle):
        reply, last_error, low = await self.call_result(Request(Command.GET_FILE_SIZE).u32(handle).out_buffer(4))
        high = reply.out_u32()
        if low == INVALID_HANDLE and last_error:
            raise RapiError("CeGetFileSize", last_error)
        return (high << 32) | low

    async def get_file_times(self, handle):
        reply, _ = await self._checked(
            Request(Command.GET_FILE_TIME).u32(handle).out_buffer(8).out_buffer(8).out_buffer(8), "CeGetFileTime")
        return tuple(struct.unpack("<Q", reply.out_buffer() or bytes(8))[0] for _ in range(3))

    async def set_file_times(self, handle, creation=None, access=None, write=None):
        request = Request(Command.SET_FILE_TIME).u32(handle)
        for value in (creation, access, write):
            request.buffer(None if value is None else struct.pack("<Q", value))
        await self._checked(request, "CeSetFileTime")

    async def read_file_contents(self, path, progress=None):
        handle = await self.create_file(path)
        try:
            chunks = bytearray()
            while True:
                data = await self.read_file(handle, READ_CHUNK)
                if not data:
                    break
                chunks += data
                if progress:
                    progress(len(chunks))
            return bytes(chunks)
        finally:
            await self.close_handle(handle)

    async def write_file_contents(self, path, data, modified=None, progress=None):
        handle = await self.create_file(path, GENERIC_WRITE, 0, CREATE_ALWAYS)
        try:
            written = 0
            while written < len(data):
                count = await self.write_file(handle, data[written:written + WRITE_CHUNK])
                if count == 0:
                    raise RapiError(f"CeWriteFile {path}", 112)
                written += count
                if progress:
                    progress(written)
        finally:
            await self.close_handle(handle)
        if modified is not None:
            handle = await self.create_file(path, GENERIC_WRITE, 0, OPEN_EXISTING)
            try:
                await self.set_file_times(handle, write=modified)
            finally:
                await self.close_handle(handle)

    async def create_directory(self, path):
        await self._checked(Request(Command.CREATE_DIRECTORY).wide_buffer(path).null(), f"CeCreateDirectory {path}")

    async def remove_directory(self, path):
        await self._checked(Request(Command.REMOVE_DIRECTORY).wide_buffer(path), f"CeRemoveDirectory {path}")

    async def delete_file(self, path):
        await self._checked(Request(Command.DELETE_FILE).wide_buffer(path), f"CeDeleteFile {path}")

    async def move_file(self, source, destination):
        await self._checked(Request(Command.MOVE_FILE).wide_buffer(source).wide_buffer(destination), f"CeMoveFile {source}")

    async def copy_file(self, source, destination, fail_if_exists=False):
        request = Request(Command.COPY_FILE).wide_buffer(source).wide_buffer(destination).u32(int(fail_if_exists))
        await self._checked(request, f"CeCopyFile {source}")

    async def create_process(self, application, arguments=None):
        request = Request(Command.CREATE_PROCESS).wide_buffer(application).wide_buffer(arguments or None)
        for reserved_index in range(7):
            request.u32(0)
        request.out_buffer(16)
        reply, _ = await self._checked(request, f"CeCreateProcess {application}")
        data = reply.out_buffer()
        return ProcessInformation(*struct.unpack("<4I", data[:16])) if data else None

    async def kill_all_apps(self):
        await self._checked(Request(Command.KILL_ALL_APPS), "CeKillAllApps")

    async def create_shortcut(self, shortcut, target):
        await self._checked(Request(Command.SH_CREATE_SHORTCUT).wide_buffer(shortcut).wide_buffer(target), f"CeSHCreateShortcut {shortcut}")

    async def get_password_active(self):
        _, _, result = await self.call_result(Request(Command.GET_PASSWORD_ACTIVE))
        return bool(result)

    async def set_password_active(self, active, password):
        await self._checked(Request(Command.SET_PASSWORD_ACTIVE).u32(int(active)).wide_buffer(password), "CeSetPasswordActive")

    async def set_password(self, old_password, new_password):
        await self._checked(Request(Command.SET_PASSWORD).wide_buffer(old_password).wide_buffer(new_password), "CeSetPassword")

    async def sync_time_to_pc(self, filetime, bias_minutes, flag=0):
        request = Request(Command.SYNC_TIME_TO_PC).raw(struct.pack("<Q", filetime)).u32(bias_minutes).u32(flag)
        reply = await self.call(request)
        return reply.u32() if reply.remaining >= 4 else None

    async def reg_open_key(self, root, subkey):
        reply, _, error = await self.call_result(Request(Command.REG_OPEN_KEY).u32(root).string(subkey))
        if error != ERROR_SUCCESS:
            raise RapiError(f"CeRegOpenKeyEx {subkey}", error)
        return reply.u32()

    async def reg_create_key(self, root, subkey, class_name=""):
        reply, _, error = await self.call_result(Request(Command.REG_CREATE_KEY).u32(root).string(subkey).string(class_name))
        if error != ERROR_SUCCESS:
            raise RapiError(f"CeRegCreateKeyEx {subkey}", error)
        handle = reply.u32()
        disposition = reply.u32()
        return handle, disposition

    async def reg_close_key(self, handle):
        _, _, error = await self.call_result(Request(Command.REG_CLOSE_KEY).u32(handle))
        if error != ERROR_SUCCESS:
            raise RapiError("CeRegCloseKey", error)

    async def reg_enum_key(self, handle, index):
        request = (Request(Command.REG_ENUM_KEY).u32(handle).u32(index)
                   .out_buffer(REGISTRY_NAME_MAX * 2).u32_buffer(REGISTRY_NAME_MAX).null().null().null().null())
        reply, _, error = await self.call_result(request)
        if error == ERROR_NO_MORE_ITEMS:
            return None
        if error != ERROR_SUCCESS:
            raise RapiError("CeRegEnumKeyEx", error)
        name = reply.out_buffer()
        return decode_wide(name or b"")

    async def reg_enum_value(self, handle, index):
        request = (Request(Command.REG_ENUM_VALUE).u32(handle).u32(index)
                   .out_buffer(REGISTRY_NAME_MAX * 2).u32_buffer(REGISTRY_NAME_MAX).null()
                   .out_buffer(4).out_buffer(REGISTRY_DATA_MAX).u32_buffer(REGISTRY_DATA_MAX))
        reply, _, error = await self.call_result(request)
        if error == ERROR_NO_MORE_ITEMS:
            return None
        if error != ERROR_SUCCESS:
            raise RapiError("CeRegEnumValue", error)
        name = decode_wide(reply.out_buffer() or b"")
        reply.out_buffer()
        value_type = reply.out_u32()
        data = reply.out_buffer() or b""
        size = reply.out_u32(len(data))
        return name, value_type, decode_registry_value(value_type, data[:size])

    async def reg_query_value(self, handle, name):
        request = (Request(Command.REG_QUERY_VALUE).u32(handle).wide_buffer(name).null()
                   .out_buffer(4).out_buffer(REGISTRY_DATA_MAX).u32_buffer(REGISTRY_DATA_MAX))
        reply, _, error = await self.call_result(request)
        if error != ERROR_SUCCESS:
            raise RapiError(f"CeRegQueryValueEx {name}", error)
        value_type = reply.out_u32()
        data = reply.out_buffer() or b""
        size = reply.out_u32(len(data))
        return value_type, decode_registry_value(value_type, data[:size])

    async def reg_set_value(self, handle, name, value_type, value):
        data = encode_registry_value(value_type, value)
        request = Request(Command.REG_SET_VALUE).u32(handle).wide_buffer(name).u32(value_type).buffer(data).u32(len(data))
        _, _, error = await self.call_result(request)
        if error != ERROR_SUCCESS:
            raise RapiError(f"CeRegSetValueEx {name}", error)

    async def reg_delete_value(self, handle, name):
        _, _, error = await self.call_result(Request(Command.REG_DELETE_VALUE).u32(handle).wide_buffer(name))
        if error != ERROR_SUCCESS:
            raise RapiError(f"CeRegDeleteValue {name}", error)

    async def reg_delete_key(self, handle, subkey):
        _, _, error = await self.call_result(Request(Command.REG_DELETE_KEY).u32(handle).wide_buffer(subkey))
        if error != ERROR_SUCCESS:
            raise RapiError(f"CeRegDeleteKey {subkey}", error)

    async def find_all_databases(self, database_type=0, flags=0x01 | 0x04):
        reply = await self.call(Request(Command.FIND_ALL_DATABASES).u32(database_type).u16(flags))
        count = reply.u16()
        databases = []
        for database_index in range(count):
            entry = {}
            if flags & 0x01:
                entry["oid"] = reply.u32()
            if flags & ~0x01:
                name_chars = reply.u32() if flags & 0x04 else 0
                if flags & 0x02:
                    entry["flags"] = reply.u32()
                if flags & 0x04:
                    entry["name"] = decode_wide(reply.take(name_chars * 2))
                if flags & 0x08:
                    entry["type"] = reply.u32()
                if flags & 0x10:
                    entry["record_count"] = reply.u16()
                if flags & 0x20:
                    entry["sort_count"] = reply.u16()
                if flags & 0x40:
                    entry["size"] = reply.u32()
                if flags & 0x80:
                    entry["modified"] = struct.unpack("<Q", reply.take(8))[0]
            databases.append(entry)
        return databases

    async def open_database(self, name=None, oid=0, sort_propid=0, flags=cedb.CEDB_AUTOINCREMENT):
        request = Request(Command.OPEN_DATABASE).u32(oid).u32(sort_propid).u32(flags).string(name)
        reply, last_error, handle = await self.call_result(request)
        if handle == INVALID_HANDLE:
            raise RapiError(f"CeOpenDatabase {name or hex(oid)}", last_error)
        return handle, reply.u32() if reply.remaining >= 4 else oid

    async def seek_database(self, handle, seek_type, value=0):
        request = Request(Command.SEEK_DATABASE).u32(handle).u32(seek_type)
        if seek_type in cedb.VALUE_SEEK_TYPES:
            block = cedb.encode_properties([value])
            request.u32(len(block)).raw(block)
        else:
            request.u32(value)
        reply, last_error, oid = await self.call_result(request)
        index = reply.u32() if reply.remaining >= 4 else 0
        return oid, index, last_error

    async def read_record(self, handle, propids=None, buffer_size=0x1000):
        request = Request(Command.READ_RECORD_PROPS).u32(handle).u32(cedb.CEDB_ALLOWREALLOC)
        if propids:
            request.u16(len(propids)).u32(1)
            for propid in propids:
                request.u32(propid)
        else:
            request.u16(0).u32(0)
        request.u32(buffer_size)
        reply, last_error, oid = await self.call_result(request)
        if not oid:
            if last_error in (ERROR_NO_MORE_ITEMS, 0):
                return None
            raise RapiError("CeReadRecordProps", last_error)
        size = reply.u32()
        count = reply.u16()
        return oid, cedb.decode_properties(reply.take(size), count)

    async def write_record(self, handle, oid, properties):
        block = cedb.encode_properties(properties)
        request = Request(Command.WRITE_RECORD_PROPS).u32(handle).u32(oid).u16(len(properties)).u32(len(block)).raw(block)
        _, last_error, written_oid = await self.call_result(request)
        if not written_oid:
            raise RapiError("CeWriteRecordProps", last_error)
        return written_oid

    async def delete_record(self, handle, oid):
        await self._checked(Request(Command.DELETE_RECORD).u32(handle).u32(oid), "CeDeleteRecord")

    async def rapi_invoke(self, dll, function, data=b""):
        request = Request(Command.RAPI_INVOKE).u32(0).string(dll).string(function).u32(len(data)).raw(data).u32(0)
        reply, last_error, hresult = await self.call_result(request)
        size = reply.u32() if reply.remaining >= 4 else 0
        return hresult, reply.take(size), last_error


def decode_registry_value(value_type, data):
    if value_type in (REG_SZ, REG_EXPAND_SZ):
        return decode_wide(data)
    if value_type == REG_MULTI_SZ:
        text = bytes(data).decode("utf-16-le", errors="replace").rstrip("\0")
        return text.split("\0") if text else []
    if value_type == REG_DWORD and len(data) >= 4:
        return struct.unpack("<I", data[:4])[0]
    return bytes(data)


def encode_registry_value(value_type, value):
    if value_type in (REG_SZ, REG_EXPAND_SZ):
        return encode_wide(value)
    if value_type == REG_MULTI_SZ:
        return "".join(item + "\0" for item in value).encode("utf-16-le") + b"\0\0"
    if value_type == REG_DWORD:
        return struct.pack("<I", value)
    return bytes(value)
