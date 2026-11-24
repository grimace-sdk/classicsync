import asyncio
import logging
import re
import struct
from datetime import timedelta

from ..rapi.commands import Command
from ..rapi.marshal import decode_wide, encode_wide
from ..rapi.structures import (
    FAF_ATTRIBUTES, FAF_CREATION_TIME, FAF_LASTACCESS_TIME, FAF_LASTWRITE_TIME, FAF_NAME, FAF_OID, FAF_SIZE_HIGH, FAF_SIZE_LOW,
    FILETIME_EPOCH,
)
from .client import INVALID_HANDLE

log = logging.getLogger("classicsync.pcconnect")

E_NOTIMPL = 0x80004001
E_INVALIDARG = 0x80070057
VER_PLATFORM_WIN32_CE = 3
PROCESSOR_ARCHITECTURE_MIPS = 1
PROCESSOR_MIPS_R4000 = 4000
PAGE_SIZE = 4096
DEFAULT_CHUNK_SIZE = 1024
MINIMUM_CHUNK_SIZE = 128
ERROR_NOT_ENOUGH_STORAGE = 112
PLATFORM_VERSION_PATTERN = re.compile(r"CE\s*(\d+)\.(\d+)", re.IGNORECASE)
DEFAULT_OS_VERSION = (3, 0)

FIND_FIELDS = [
    (FAF_ATTRIBUTES, "attributes", "<I"),
    (FAF_CREATION_TIME, "creation_time", "<Q"),
    (FAF_LASTACCESS_TIME, "last_access_time", "<Q"),
    (FAF_LASTWRITE_TIME, "last_write_time", "<Q"),
]


class RequestBuffer:
    def __init__(self, size, data):
        self.size = size
        self.data = data


class RapiRequestReader:
    def __init__(self, data):
        self.data = bytes(data)
        self.offset = 0

    def take(self, size):
        if self.offset + size > len(self.data):
            raise ValueError(f"short RAPI request: wanted {size} bytes at {self.offset}, have {len(self.data)}")
        chunk = self.data[self.offset:self.offset + size]
        self.offset += size
        return chunk

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def u16(self):
        return struct.unpack("<H", self.take(2))[0]

    def u64(self):
        return struct.unpack("<Q", self.take(8))[0]

    def string(self):
        if not self.u32():
            return None
        characters = self.u32()
        return decode_wide(self.take(characters * 2))

    def buffer(self):
        if not self.u32():
            return None
        size = self.u32()
        has_data = self.u32()
        return RequestBuffer(size, self.take(size) if has_data else None)

    def data_size(self):
        return self.u32() if self.u32() else 0

    def wide_buffer(self):
        buffer = self.buffer()
        if buffer is None or buffer.data is None:
            return None
        return decode_wide(buffer.data)

    def u32_buffer(self, default=0):
        buffer = self.buffer()
        if buffer is None or not buffer.data or len(buffer.data) < 4:
            return default
        return struct.unpack("<I", buffer.data[:4])[0]


class RapiReplyWriter:
    def __init__(self, status=0):
        self.parts = [struct.pack("<I", status)]

    def u32(self, value):
        self.parts.append(struct.pack("<I", value & 0xFFFFFFFF))
        return self

    def raw(self, data):
        self.parts.append(bytes(data))
        return self

    def out_buffer(self, data):
        if data is None:
            return self.u32(0)
        return self.u32(1).u32(len(data)).u32(1).raw(data)

    def out_u32(self, value):
        return self.out_buffer(struct.pack("<I", value & 0xFFFFFFFF))

    def build(self):
        return b"".join(self.parts)


def result_reply(wil_reply):
    return RapiReplyWriter().u32(wil_reply.error).u32(wil_reply.value)


def failure_reply(hresult):
    return RapiReplyWriter(1).u32(hresult).build()


def os_version_from_platform(platform_name):
    match = PLATFORM_VERSION_PATTERN.search(platform_name or "")
    return (int(match.group(1)), int(match.group(2))) if match else DEFAULT_OS_VERSION


def filetime_to_systemtime(filetime):
    moment = FILETIME_EPOCH + timedelta(microseconds=filetime // 10)
    weekday = (moment.weekday() + 1) % 7
    return (moment.year, moment.month, weekday, moment.day, moment.hour, moment.minute, moment.second, moment.microsecond // 1000)


class RapiBridge:
    def __init__(self, wil, device=None, chunk_size=DEFAULT_CHUNK_SIZE):
        self.wil = wil
        self.device = device
        self.chunk_size = chunk_size
        self.handlers = {
            Command.GET_VERSION_EX: self.get_version,
            Command.GET_SYSTEM_INFO: self.get_system_info,
            Command.GET_STORE_INFORMATION: self.get_store_information,
            Command.FIND_ALL_FILES: self.find_all_files,
            Command.CREATE_FILE: self.create_file,
            Command.READ_FILE: self.read_file,
            Command.WRITE_FILE: self.write_file,
            Command.CLOSE_HANDLE: self.close_handle,
            Command.GET_FILE_ATTRIBUTES: self.get_file_attributes,
            Command.SET_FILE_ATTRIBUTES: self.set_file_attributes,
            Command.GET_FILE_SIZE: self.get_file_size,
            Command.GET_FILE_TIME: self.get_file_time,
            Command.SET_FILE_TIME: self.set_file_time,
            Command.CREATE_DIRECTORY: self.create_directory,
            Command.REMOVE_DIRECTORY: self.remove_directory,
            Command.DELETE_FILE: self.delete_file,
            Command.MOVE_FILE: self.move_file,
            Command.COPY_FILE: self.copy_file,
            Command.CREATE_PROCESS: self.create_process,
            Command.SYNC_TIME_TO_PC: self.sync_time_to_pc,
            Command.REG_OPEN_KEY: self.reg_open_key,
            Command.REG_CREATE_KEY: self.reg_create_key,
            Command.REG_CLOSE_KEY: self.reg_close_key,
            Command.REG_ENUM_KEY: self.reg_enum_key,
            Command.REG_ENUM_VALUE: self.reg_enum_value,
            Command.REG_QUERY_VALUE: self.reg_query_value,
            Command.REG_SET_VALUE: self.reg_set_value,
            Command.REG_DELETE_VALUE: self.reg_delete_value,
            Command.REG_DELETE_KEY: self.reg_delete_key,
        }

    async def handle(self, body):
        request = RapiRequestReader(body)
        try:
            command = request.u32()
        except ValueError:
            return failure_reply(E_INVALIDARG)
        handler = self.handlers.get(command)
        if handler is None:
            log.info("RAPI command 0x%02x has no PC Connect equivalent", command)
            return failure_reply(E_NOTIMPL)
        try:
            return await handler(request)
        except (ValueError, struct.error) as error:
            log.info("malformed RAPI request 0x%02x: %s", command, error)
            return failure_reply(E_INVALIDARG)

    async def get_version(self, request):
        major, minor = os_version_from_platform(self.device.platform_name if self.device else "")
        service_pack = encode_wide("")
        info = struct.pack("<5I", 20 + len(service_pack), major, minor, 0, VER_PLATFORM_WIN32_CE) + service_pack
        return RapiReplyWriter().u32(0).u32(1).u32(len(info)).raw(info).build()

    async def get_system_info(self, request):
        info = struct.pack("<HHIIIIIIIHH", PROCESSOR_ARCHITECTURE_MIPS, 0, PAGE_SIZE, 0x10000, 0x7FFFFFFF, 1, 1, PROCESSOR_MIPS_R4000,
                           0x10000, 4, 0)
        return RapiReplyWriter().u32(0).out_buffer(info).build()

    async def get_store_information(self, request):
        reply, store_size, free_size = await self.wil.get_store_information()
        return result_reply(reply).out_buffer(struct.pack("<II", store_size, free_size)).build()

    async def find_all_files(self, request):
        pattern = request.string() or "\\*"
        flags = request.u32()
        reply, entries = await self.wil.find_all_files(pattern)
        entries = [entry for entry in entries if entry.name not in ("", ".", "..")]
        writer = RapiReplyWriter().u32(len(entries))
        for entry in entries:
            name = encode_wide(entry.name)
            if flags & FAF_NAME:
                writer.u32(len(name) // 2)
            for bit, field, layout in FIND_FIELDS:
                if flags & bit:
                    writer.raw(struct.pack(layout, getattr(entry, field)))
            if flags & FAF_SIZE_HIGH:
                writer.u32(entry.size >> 32)
            if flags & FAF_SIZE_LOW:
                writer.u32(entry.size)
            if flags & FAF_OID:
                writer.u32(entry.oid)
            if flags & FAF_NAME:
                writer.raw(name)
        return writer.build()

    async def create_file(self, request):
        access, share, creation, flags, template = (request.u32() for field_index in range(5))
        path = request.string() or ""
        reply = await self.wil.create_file(path, access, share, creation, flags)
        handle = INVALID_HANDLE if reply.value == 0 else reply.value
        return RapiReplyWriter().u32(reply.error).u32(handle).build()

    async def read_file(self, request):
        handle = request.u32()
        wanted = request.data_size()
        data = bytearray()
        while len(data) < wanted:
            request_size = min(self.chunk_size, wanted - len(data))
            reply, chunk = await self.wil.read_file(handle, request_size)
            if not reply.value:
                if not data:
                    return RapiReplyWriter().u32(reply.error).u32(0).u32(0).build()
                break
            data += chunk
            if len(chunk) < request_size:
                break
        return RapiReplyWriter().u32(0).u32(1).u32(len(data)).raw(data).build()

    async def write_file(self, request):
        handle = request.u32()
        data = request.take(request.data_size())
        written_total = 0
        while written_total < len(data):
            piece = data[written_total:written_total + self.chunk_size]
            try:
                reply, written = await self.wil.write_file(handle, piece)
            except TimeoutError:
                if self.chunk_size <= MINIMUM_CHUNK_SIZE:
                    raise
                self.chunk_size //= 2
                log.info("write stalled, retrying with %d byte chunks", self.chunk_size)
                continue
            if not reply.value:
                return RapiReplyWriter().u32(reply.error).u32(0).u32(written_total).build()
            if not written:
                return RapiReplyWriter().u32(ERROR_NOT_ENOUGH_STORAGE).u32(0).u32(written_total).build()
            written_total += written
        return RapiReplyWriter().u32(0).u32(1).u32(written_total).build()

    async def close_handle(self, request):
        return result_reply(await self.wil.close_handle(request.u32())).build()

    async def get_file_attributes(self, request):
        return result_reply(await self.wil.get_file_attributes(request.string() or "")).build()

    async def set_file_attributes(self, request):
        attributes = request.u32()
        return result_reply(await self.wil.set_file_attributes(request.string() or "", attributes)).build()

    async def get_file_size(self, request):
        reply, high = await self.wil.get_file_size(request.u32())
        return result_reply(reply).out_u32(high).build()

    async def get_file_time(self, request):
        reply, times = await self.wil.get_file_times(request.u32())
        writer = result_reply(reply)
        for value in times:
            writer.out_buffer(struct.pack("<Q", value))
        return writer.build()

    async def set_file_time(self, request):
        handle = request.u32()
        wanted = []
        for field_index in range(3):
            buffer = request.buffer()
            wanted.append(struct.unpack("<Q", buffer.data[:8])[0] if buffer and buffer.data else None)
        if None in wanted:
            current_reply, current = await self.wil.get_file_times(handle)
            wanted = [current[index] if value is None else value for index, value in enumerate(wanted)]
        return result_reply(await self.wil.set_file_times(handle, *wanted)).build()

    async def create_directory(self, request):
        return result_reply(await self.wil.create_directory(request.wide_buffer() or "")).build()

    async def remove_directory(self, request):
        return result_reply(await self.wil.remove_directory(request.wide_buffer() or "")).build()

    async def delete_file(self, request):
        return result_reply(await self.wil.delete_file(request.wide_buffer() or "")).build()

    async def move_file(self, request):
        source = request.wide_buffer() or ""
        destination = request.wide_buffer() or ""
        return result_reply(await self.wil.move_file(source, destination)).build()

    async def copy_file(self, request):
        source = request.wide_buffer() or ""
        destination = request.wide_buffer() or ""
        fail_if_exists = request.u32()
        return result_reply(await self.wil.copy_file(source, destination, bool(fail_if_exists))).build()

    async def create_process(self, request):
        application = request.wide_buffer() or ""
        arguments = request.wide_buffer()
        process_attributes, thread_attributes, inherit_handles, creation_flags, environment, directory, startup = (
            request.u32() for field_index in range(7))
        reply, information = await self.wil.create_process(application, arguments or None, creation_flags)
        return result_reply(reply).out_buffer(struct.pack("<4I", *information) if information else None).build()

    async def sync_time_to_pc(self, request):
        filetime = request.u64()
        reply = await self.wil.set_system_time(filetime_to_systemtime(filetime))
        return RapiReplyWriter().u32(reply.value).build()

    async def reg_open_key(self, request):
        root = request.u32()
        subkey = request.string()
        reply, handle = await self.wil.reg_open_key(root, subkey or "")
        return RapiReplyWriter().u32(reply.error).u32(reply.value).u32(handle).build()

    async def reg_create_key(self, request):
        root = request.u32()
        subkey = request.string()
        class_name = request.string()
        reply, handle, disposition = await self.wil.reg_create_key(root, subkey or "", class_name)
        return RapiReplyWriter().u32(reply.error).u32(reply.value).u32(handle).u32(disposition).build()

    async def reg_close_key(self, request):
        reply = await self.wil.reg_close_key(request.u32())
        return RapiReplyWriter().u32(reply.error).u32(reply.value).build()

    async def reg_enum_key(self, request):
        handle = request.u32()
        index = request.u32()
        name_buffer = request.buffer()
        name_characters = request.u32_buffer(name_buffer.size // 2 if name_buffer else 256)
        reply, name = await self.wil.reg_enum_key(handle, index, name_characters)
        writer = RapiReplyWriter().u32(reply.error).u32(reply.value)
        return writer.out_buffer(encode_wide(name) if name is not None else None).build()

    async def reg_enum_value(self, request):
        handle = request.u32()
        index = request.u32()
        name_buffer = request.buffer()
        name_characters = request.u32_buffer(name_buffer.size // 2 if name_buffer else 256)
        request.buffer()
        request.buffer()
        data_buffer = request.buffer()
        data_size = request.u32_buffer(data_buffer.size if data_buffer else 0)
        reply, value = await self.wil.reg_enum_value(handle, index, name_characters, data_size)
        writer = RapiReplyWriter().u32(reply.error).u32(reply.value)
        if value is None:
            return writer.out_buffer(None).out_buffer(None).out_buffer(None).out_buffer(None).out_buffer(None).build()
        name, value_type, data = value
        name_bytes = encode_wide(name)
        return (writer.out_buffer(name_bytes).out_u32(len(name_bytes) // 2 - 1).out_u32(value_type).out_buffer(data)
                .out_u32(len(data)).build())

    async def reg_query_value(self, request):
        handle = request.u32()
        name = request.wide_buffer()
        request.buffer()
        request.buffer()
        data_buffer = request.buffer()
        data_size = request.u32_buffer(data_buffer.size if data_buffer else 0)
        reply, value = await self.wil.reg_query_value(handle, name or "", data_size)
        writer = RapiReplyWriter().u32(reply.error).u32(reply.value)
        if value is None:
            return writer.out_buffer(None).out_buffer(None).out_buffer(None).build()
        value_type, data = value
        return writer.out_u32(value_type).out_buffer(data).out_u32(len(data)).build()

    async def reg_set_value(self, request):
        handle = request.u32()
        name = request.wide_buffer()
        value_type = request.u32()
        buffer = request.buffer()
        data = buffer.data if buffer and buffer.data else b""
        reply = await self.wil.reg_set_value(handle, name or "", value_type, data)
        return RapiReplyWriter().u32(reply.error).u32(reply.value).build()

    async def reg_delete_value(self, request):
        handle = request.u32()
        reply = await self.wil.reg_delete_value(handle, request.wide_buffer() or "")
        return RapiReplyWriter().u32(reply.error).u32(reply.value).build()

    async def reg_delete_key(self, request):
        handle = request.u32()
        reply = await self.wil.reg_delete_key(handle, request.wide_buffer() or "")
        return RapiReplyWriter().u32(reply.error).u32(reply.value).build()


class BridgeStream:
    def __init__(self, bridge):
        self.bridge = bridge
        self.incoming = bytearray()
        self.outgoing = bytearray()
        self.closed = False

    def write(self, data):
        self.incoming += data

    async def drain(self):
        while len(self.incoming) >= 4:
            length = struct.unpack("<I", self.incoming[:4])[0]
            if len(self.incoming) < 4 + length:
                return
            body = bytes(self.incoming[4:4 + length])
            del self.incoming[:4 + length]
            reply = await self.bridge.handle(body)
            self.outgoing += struct.pack("<I", len(reply)) + reply

    async def readexactly(self, size):
        if self.closed or len(self.outgoing) < size:
            raise asyncio.IncompleteReadError(bytes(self.outgoing), size)
        data = bytes(self.outgoing[:size])
        del self.outgoing[:size]
        return data

    def close(self):
        self.closed = True


async def serve_bridge_connection(bridge, reader, writer):
    try:
        while True:
            header = await reader.readexactly(4)
            length = struct.unpack("<I", header)[0]
            body = await reader.readexactly(length)
            reply = await bridge.handle(body)
            writer.write(struct.pack("<I", len(reply)) + reply)
            await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    except TimeoutError as error:
        log.info("proxy: %s", error)
    finally:
        writer.close()
