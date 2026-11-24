import struct
from dataclasses import dataclass, field

from ..rapi import cedb
from ..rapi.client import (
    ERROR_NO_MORE_ITEMS, FILE_ATTRIBUTE_NORMAL, GENERIC_READ, GENERIC_WRITE, HKEY_LOCAL_MACHINE, INVALID_HANDLE, OPEN_EXISTING,
    READ_CHUNK, WRITE_CHUNK, RapiError,
)
from ..rapi.commands import Command
from ..rapi.marshal import Request, decode_wide
from .format import DatabaseInfo

FILE_SHARE_READ = 1
CREATE_ALWAYS = 2
ERROR_ACCESS_DENIED = 5

FIND_ALL_DATABASE_FIELDS = 0x1FF
FIND_DATABASE_SORT_ORDERS = 0x100
NOTIFICATION_DATABASE_EVENT = 0x888

LANGUAGE_KEY = "nls"
LANGUAGE_VALUE = "DefaultLCID"


@dataclass
class MemoryDivision:
    store_pages: int
    ram_pages: int
    page_size: int


@dataclass
class DeviceDatabase:
    oid: int
    info: DatabaseInfo
    pending_delete: bool = field(default=False)


async def reg_copy_file(client, path):
    _, last_error, result = await client.call_result(Request(Command.REG_COPY_FILE).wide_buffer(path))
    if not result:
        raise RapiError(f"CeRegCopyFile {path}", last_error)


async def reg_restore_file(client, path):
    _, last_error, result = await client.call_result(Request(Command.REG_RESTORE_FILE).wide_buffer(path))
    if not result:
        raise RapiError(f"CeRegRestoreFile {path}", last_error)


async def get_memory_division(client):
    request = Request(Command.GET_SYSTEM_MEMORY_DIVISION).out_buffer(4).out_buffer(4).out_buffer(4)
    reply, last_error, result = await client.call_result(request)
    if not result:
        raise RapiError("GetSystemMemoryDivision", last_error)
    return MemoryDivision(reply.out_u32(), reply.out_u32(), reply.out_u32())


async def set_memory_division(client, store_pages):
    _, last_error, result = await client.call_result(Request(Command.SET_SYSTEM_MEMORY_DIVISION).u32(store_pages))
    return result


async def default_language(client, fallback):
    try:
        key = await client.reg_open_key(HKEY_LOCAL_MACHINE, LANGUAGE_KEY)
    except RapiError:
        return fallback
    try:
        value_type, value = await client.reg_query_value(key, LANGUAGE_VALUE)
        return value if isinstance(value, int) else fallback
    except RapiError:
        return fallback
    finally:
        await client.reg_close_key(key)


async def find_all_databases(client):
    reply = await client.call(Request(Command.FIND_ALL_DATABASES).u32(0).u16(FIND_ALL_DATABASE_FIELDS))
    databases = []
    for _ in range(reply.u16()):
        oid = reply.u32()
        name_chars = reply.u32()
        flags = reply.u32()
        name = decode_wide(reply.take(name_chars * 2))
        database_type = reply.u32()
        record_count = reply.u16()
        sort_count = reply.u16()
        size = reply.u32()
        modified = struct.unpack("<Q", reply.take(8))[0]
        sorts = [struct.unpack("<II", reply.take(8)) for _ in range(4)]
        info = DatabaseInfo(name, database_type, flags, record_count, sort_count, size, modified, sorts[:sort_count])
        databases.append(DeviceDatabase(oid, info))
    return databases


async def create_database(client, info):
    request = Request(Command.CREATE_DATABASE).u32(info.database_type).u16(len(info.sort_orders))
    for propid, flags in info.sort_orders:
        request.u32(propid).u32(flags)
    request.string(info.name)
    _, last_error, oid = await client.call_result(request)
    if not oid:
        raise RapiError(f"CeCreateDatabase {info.name}", last_error)
    return oid


async def set_database_info(client, oid, info):
    _, last_error, result = await client.call_result(Request(Command.SET_DATABASE_INFO).u32(oid).raw(info.pack()))
    if not result:
        raise RapiError(f"CeSetDatabaseInfo {info.name}", last_error)


async def delete_database(client, oid, name=""):
    _, last_error, result = await client.call_result(Request(Command.DELETE_DATABASE).u32(oid))
    if not result:
        raise RapiError(f"CeDeleteDatabase {name or hex(oid)}", last_error)


async def open_database_by_oid(client, oid):
    request = Request(Command.OPEN_DATABASE).u32(oid).u32(0).u32(cedb.CEDB_AUTOINCREMENT).string(None)
    _, last_error, handle = await client.call_result(request)
    if handle == INVALID_HANDLE:
        raise RapiError(f"CeOpenDatabase {oid:#x}", last_error)
    return handle


async def read_raw_record(client, handle, buffer_size=0x1000):
    request = Request(Command.READ_RECORD_PROPS).u32(handle).u32(cedb.CEDB_ALLOWREALLOC).u16(0).u32(0).u32(buffer_size)
    reply, last_error, oid = await client.call_result(request)
    if not oid:
        if last_error in (ERROR_NO_MORE_ITEMS, 0):
            return None
        raise RapiError("CeReadRecordProps", last_error)
    size = reply.u32()
    property_count = reply.u16()
    return oid, property_count, reply.take(size)


async def write_raw_record(client, handle, property_count, block):
    request = Request(Command.WRITE_RECORD_PROPS).u32(handle).u32(0).u16(property_count).u32(len(block)).raw(block)
    _, last_error, oid = await client.call_result(request)
    if not oid:
        raise RapiError("CeWriteRecordProps", last_error)
    return oid


async def event_has_occurred(client, event, parameter=None):
    _, _, result = await client.call_result(Request(Command.EVENT_HAS_OCCURRED).u32(event).string(parameter))
    return result


async def read_device_file(client, path):
    handle = await client.create_file(path, GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING)
    try:
        chunks = bytearray()
        while True:
            data = await client.read_file(handle, READ_CHUNK)
            if not data:
                return bytes(chunks)
            chunks += data
    finally:
        await client.close_handle(handle)


async def write_device_file(client, path, contents, attributes, modified):
    try:
        await client.delete_file(path)
    except RapiError:
        pass
    flags = attributes or FILE_ATTRIBUTE_NORMAL
    try:
        handle = await client.create_file(path, GENERIC_WRITE, 0, CREATE_ALWAYS, flags)
    except RapiError as error:
        if error.code != ERROR_ACCESS_DENIED:
            raise
        await client.set_file_attributes(path, FILE_ATTRIBUTE_NORMAL)
        await client.delete_file(path)
        handle = await client.create_file(path, GENERIC_WRITE, 0, CREATE_ALWAYS, flags)
    try:
        written = 0
        while written < len(contents):
            count = await client.write_file(handle, contents[written:written + WRITE_CHUNK])
            if count == 0:
                raise RapiError(f"CeWriteFile {path}", 112)
            written += count
        await client.set_file_times(handle, write=modified)
    finally:
        await client.close_handle(handle)
