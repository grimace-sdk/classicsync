import asyncio
import fnmatch
import struct
from dataclasses import dataclass, field

HKEY_LOCAL_MACHINE = 0x80000002
ROOT_KEYS = (0x80000000, 0x80000001, 0x80000002, 0x80000003)
REG_SZ = 1
REG_DWORD = 4
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_ARCHIVE = 0x20
CREATE_ALWAYS = 2
OPEN_EXISTING = 3
ERROR_FILE_NOT_FOUND = 2
ERROR_PATH_NOT_FOUND = 3
ERROR_INVALID_HANDLE = 6
ERROR_DIR_NOT_EMPTY = 145
ERROR_NO_MORE_FILES = 18
ERROR_NO_MORE_ITEMS = 259
INVALID_HANDLE = 0xFFFFFFFF
NAND_BASE = 7584
NAND_HANDLE = 0x80DACD72
LARGE_REPLY_LIMIT = 0xFDC2


def be32(*values):
    return struct.pack(f">{len(values)}I", *(value & 0xFFFFFFFF for value in values))


def wstr(text):
    body = (text + "\0").encode("utf-16-be")
    return struct.pack(">H", len(body)) + body


def utf16le(text):
    return (text + "\0").encode("utf-16-le")


class Payload:
    def __init__(self, data):
        self.data = data
        self.offset = 0

    def u32(self):
        value = struct.unpack(">I", self.data[self.offset:self.offset + 4])[0]
        self.offset += 4
        return value

    def u16(self):
        value = struct.unpack(">H", self.data[self.offset:self.offset + 2])[0]
        self.offset += 2
        return value

    def wstr(self):
        length = self.u16()
        body = self.data[self.offset:self.offset + length]
        self.offset += length
        return body.decode("utf-16-be").split("\0")[0]

    def optional_wstr(self):
        return self.wstr() if self.u32() else None

    def raw(self, size):
        chunk = self.data[self.offset:self.offset + size]
        self.offset += size
        return chunk

    def filetime(self):
        low, high = struct.unpack(">II", self.raw(8))
        return (high << 32) | low


@dataclass
class FakeFile:
    path: str
    data: bytearray = field(default_factory=bytearray)
    attributes: int = FILE_ATTRIBUTE_ARCHIVE
    times: list = field(default_factory=lambda: [131000000000000000, 131000000000000000, 131000000000000000])


@dataclass
class OpenFile:
    file: FakeFile
    position: int = 0


def parent_of(path):
    head = path.rsplit("\\", 1)[0]
    return head or "\\"


def leaf_of(path):
    return path.rsplit("\\", 1)[-1]


class FakePcConnectDevice:
    def __init__(self, transport):
        self.transport = transport
        self.buffer = bytearray()
        self.handshakes = 0
        self.connected = False
        self.files = {}
        self.directories = {"\\": "\\", "\\nand disk": "\\Nand Disk", "\\temp": "\\Temp", "\\windows": "\\Windows"}
        self.handles = {}
        self.next_handle = 0x80DA0000
        self.registry = {(HKEY_LOCAL_MACHINE, "platform"): {
            "name": ("Name", REG_SZ, utf16le("Casio Jx740 CE3.00")),
            "release": ("Release", REG_SZ, utf16le("002202")),
        }}
        self.key_names = {}
        self.processes = []
        self.system_time = (2026, 11, 2, 24, 12, 0, 0, 0)
        self.commands = []
        self.host_keepalives = 0
        self.keepalive_before_reply = False
        self.busy_before_reply = 0
        self.resend_once = set()
        self.large_reply_limit = LARGE_REPLY_LIMIT
        self.bad_frames = 0
        self.uuid = bytes(range(0x10, 0x20))
        self.task = None
        self.handlers = {
            0x0301: self.version, 0x0346: self.get_uuid, 0x0338: self.disk_name, 0x0339: self.disk_name,
            0x030C: self.create_file, 0x0319: self.read_file, 0x031F: self.write_file, 0x0309: self.close_handle,
            0x030F: self.find_all_files, 0x0311: self.find_first_file, 0x0312: self.find_next_file, 0x0310: self.close_handle,
            0x0313: self.get_file_attributes, 0x031C: self.set_file_attributes, 0x0314: self.get_file_size,
            0x0315: self.get_file_time, 0x031E: self.set_file_time, 0x030B: self.create_directory, 0x031A: self.remove_directory,
            0x030E: self.delete_file, 0x0318: self.move_file, 0x030A: self.copy_file, 0x0317: self.store_information,
            0x030D: self.create_process, 0x033C: self.cosh_execute,
            0x0326: self.reg_open_key, 0x0321: self.reg_create_key, 0x0320: self.reg_close_key, 0x0324: self.reg_enum_key,
            0x0325: self.reg_enum_value, 0x0328: self.reg_query_value, 0x0329: self.reg_set_value, 0x0323: self.reg_delete_value,
            0x0322: self.reg_delete_key, 0x0347: self.get_system_time, 0x0349: self.set_system_time, 0x032A: self.soft_reset,
            0x033F: self.nand_open, 0x0340: self.nand_close, 0x0341: self.nand_get_info, 0x0342: self.nand_read_sector,
        }

    def start(self):
        self.task = asyncio.create_task(self.run())
        return self

    async def run(self):
        while True:
            data = await self.transport.read()
            if not data:
                return
            self.feed(data)

    def put_file(self, path, data):
        self.files[path.lower()] = FakeFile(path, bytearray(data))

    def file_data(self, path):
        return bytes(self.files[path.lower()].data)

    def feed(self, data):
        self.buffer += data
        while self.buffer:
            first = self.buffer[0]
            if not self.connected:
                del self.buffer[0]
                if first == 0x55:
                    self.transport.write(b"\x55")
                    self.handshakes += 1
                    self.connected = self.handshakes >= 2
                continue
            if first == 0x55:
                del self.buffer[0]
                self.host_keepalives += 1
                continue
            if first != 0x10:
                del self.buffer[0]
                continue
            if len(self.buffer) < 10:
                return
            length = struct.unpack(">H", self.buffer[2:4])[0]
            if len(self.buffer) < length:
                return
            frame = bytes(self.buffer[:length])
            del self.buffer[:length]
            self.handle_frame(frame)

    def handle_frame(self, frame):
        header_sum = sum(frame[:8]) & 0xFFFF
        payload_sum = sum(frame[10:]) & 0xFFFF
        if struct.unpack(">HH", frame[6:10]) != (payload_sum, header_sum):
            self.bad_frames += 1
            self.transport.write(b"\x20")
            return
        command = struct.unpack(">H", frame[4:6])[0]
        self.commands.append(command)
        if command in self.resend_once:
            self.resend_once.discard(command)
            self.transport.write(b"\x20")
            return
        handler = self.handlers.get(command)
        result = handler(Payload(frame[10:])) if handler else (0, 120, b"")
        if result is None:
            return
        value, error, data = result
        body = be32(value, error) + data
        if self.keepalive_before_reply:
            self.transport.write(b"\x55")
        for busy_index in range(self.busy_before_reply):
            self.transport.write(b"\x5a")
        if command == 0x030F and 10 + len(body) > self.large_reply_limit:
            full = bytes([0x11, frame[1], 0, 0]) + frame[4:6] + frame[6:10] + body
            self.transport.write(bytes([0x11, frame[1]]) + struct.pack(">HH", 14, 0x0401) + frame[6:10] + be32(len(full)))
            self.transport.write(full)
            return
        self.transport.write(bytes([0x11, frame[1]]) + struct.pack(">HH", 10 + len(body), command) + frame[6:10] + body)

    def new_handle(self, value):
        self.next_handle += 4
        self.handles[self.next_handle] = value
        return self.next_handle

    def version(self, payload):
        return 0x00010000, 0x57, b""

    def get_uuid(self, payload):
        return 1, 0x57, self.uuid

    def disk_name(self, payload):
        payload.u32()
        payload.u32()
        return 1, 0, wstr("\\Nand Disk")

    def create_file(self, payload):
        path = payload.wstr()
        access, share, creation, flags = (payload.u32() for field_index in range(4))
        key = path.lower()
        if parent_of(key) not in self.directories:
            return INVALID_HANDLE, ERROR_PATH_NOT_FOUND, b""
        if creation == CREATE_ALWAYS:
            self.files[key] = FakeFile(path)
        elif key not in self.files:
            return INVALID_HANDLE, ERROR_FILE_NOT_FOUND, b""
        return self.new_handle(OpenFile(self.files[key])), 0, b""

    def read_file(self, payload):
        handle, size = payload.u32(), payload.u32()
        opened = self.handles.get(handle)
        if not isinstance(opened, OpenFile):
            return 0, ERROR_INVALID_HANDLE, be32(0)
        chunk = bytes(opened.file.data[opened.position:opened.position + size])
        opened.position += len(chunk)
        return 1, 0, be32(len(chunk)) + chunk

    def write_file(self, payload):
        handle, size = payload.u32(), payload.u32()
        data = payload.raw(size)
        opened = self.handles.get(handle)
        if not isinstance(opened, OpenFile):
            return 0, ERROR_INVALID_HANDLE, be32(0)
        opened.file.data[opened.position:opened.position + len(data)] = data
        opened.position += len(data)
        return 1, 0, be32(len(data))

    def close_handle(self, payload):
        return (1, 0, b"") if self.handles.pop(payload.u32(), None) is not None else (0, ERROR_INVALID_HANDLE, b"")

    def find_data(self, entry):
        if isinstance(entry, FakeFile):
            size = len(entry.data)
            return be32(entry.attributes) + b"".join(be32(time & 0xFFFFFFFF, time >> 32) for time in entry.times) + \
                be32(size >> 32, size & 0xFFFFFFFF, 0) + wstr(leaf_of(entry.path))
        return be32(FILE_ATTRIBUTE_DIRECTORY) + bytes(24) + be32(0, 0, 0) + wstr(leaf_of(entry))

    def matching(self, pattern):
        directory, mask = parent_of(pattern.lower()), leaf_of(pattern.lower())
        mask = "*" if mask == "*.*" else mask
        entries = [path for key, path in sorted(self.directories.items()) if key != "\\" and parent_of(key) == directory
                   and fnmatch.fnmatch(leaf_of(key), mask)]
        entries += [entry for key, entry in sorted(self.files.items()) if parent_of(key) == directory and fnmatch.fnmatch(leaf_of(key), mask)]
        return entries

    def find_all_files(self, payload):
        entries = self.matching(payload.wstr())
        return 1, 0, be32(len(entries), 1) + b"".join(self.find_data(entry) for entry in entries)

    def find_first_file(self, payload):
        entries = self.matching(payload.wstr())
        if not entries:
            return INVALID_HANDLE, ERROR_FILE_NOT_FOUND, b""
        return self.new_handle(entries[1:]), 0, self.find_data(entries[0])

    def find_next_file(self, payload):
        remaining = self.handles.get(payload.u32())
        if not remaining:
            return 0, ERROR_NO_MORE_FILES, b""
        return 1, 0, self.find_data(remaining.pop(0))

    def get_file_attributes(self, payload):
        key = payload.wstr().lower()
        if key in self.directories:
            return FILE_ATTRIBUTE_DIRECTORY, 0, b""
        if key in self.files:
            return self.files[key].attributes, 0, b""
        return INVALID_HANDLE, ERROR_FILE_NOT_FOUND, b""

    def set_file_attributes(self, payload):
        key = payload.wstr().lower()
        attributes = payload.u32()
        if key not in self.files:
            return 0, ERROR_FILE_NOT_FOUND, b""
        self.files[key].attributes = attributes
        return 1, 0, b""

    def get_file_size(self, payload):
        opened = self.handles[payload.u32()]
        size = len(opened.file.data)
        return size & 0xFFFFFFFF, 0, be32(size >> 32) if payload.u32() else b""

    def get_file_time(self, payload):
        opened = self.handles[payload.u32()]
        return 1, 0, b"".join(be32(time & 0xFFFFFFFF, time >> 32) for time in opened.file.times)

    def set_file_time(self, payload):
        opened = self.handles[payload.u32()]
        opened.file.times = [payload.filetime() for time_index in range(3)]
        return 1, 0, b""

    def create_directory(self, payload):
        path = payload.wstr()
        if parent_of(path.lower()) not in self.directories:
            return 0, ERROR_PATH_NOT_FOUND, b""
        self.directories[path.lower()] = path
        return 1, 0, b""

    def remove_directory(self, payload):
        key = payload.wstr().lower()
        if key not in self.directories:
            return 0, ERROR_FILE_NOT_FOUND, b""
        if any(parent_of(other) == key for other in list(self.files) + list(self.directories) if other != key):
            return 0, ERROR_DIR_NOT_EMPTY, b""
        del self.directories[key]
        return 1, 0, b""

    def delete_file(self, payload):
        return (1, 0, b"") if self.files.pop(payload.wstr().lower(), None) else (0, ERROR_FILE_NOT_FOUND, b"")

    def move_file(self, payload):
        source, destination = payload.wstr(), payload.wstr()
        entry = self.files.pop(source.lower(), None)
        if entry is None:
            return 0, ERROR_FILE_NOT_FOUND, b""
        entry.path = destination
        self.files[destination.lower()] = entry
        return 1, 0, b""

    def copy_file(self, payload):
        source, destination = payload.wstr(), payload.wstr()
        payload.u32()
        entry = self.files.get(source.lower())
        if entry is None:
            return 0, ERROR_FILE_NOT_FOUND, b""
        self.files[destination.lower()] = FakeFile(destination, bytearray(entry.data), entry.attributes, list(entry.times))
        return 1, 0, b""

    def store_information(self, payload):
        return 1, 0, be32(12566528, 8000000)

    def create_process(self, payload):
        application = payload.wstr()
        command_line = payload.optional_wstr()
        payload.u32()
        self.processes.append((application, command_line))
        return 1, 0, be32(0x100, 0x200, 0x300, 0x400)

    def cosh_execute(self, payload):
        application = payload.optional_wstr()
        command_line = payload.optional_wstr()
        self.processes.append((application, command_line))
        return 1, 0, b""

    def key_path(self, handle, subkey):
        if handle in ROOT_KEYS:
            root, path = handle, ""
        else:
            root, path = self.handles[handle]
        if subkey:
            path = f"{path}\\{subkey}" if path else subkey
        return root, path.lower()

    def reg_open_key(self, payload):
        handle = payload.u32()
        key = self.key_path(handle, payload.optional_wstr())
        if key not in self.registry:
            return ERROR_FILE_NOT_FOUND, 0, be32(0)
        return 0, 0, be32(self.new_handle(key))

    def reg_create_key(self, payload):
        handle = payload.u32()
        subkey = payload.optional_wstr()
        key = self.key_path(handle, subkey)
        for name in (subkey or "").split("\\"):
            self.key_names[name.lower()] = name
        payload.optional_wstr()
        disposition = 2 if key in self.registry else 1
        root, subkey = key
        parts = subkey.split("\\")
        for depth in range(1, len(parts) + 1):
            self.registry.setdefault((root, "\\".join(parts[:depth])), {})
        return 0, 0, be32(self.new_handle(key), disposition)

    def reg_close_key(self, payload):
        self.handles.pop(payload.u32(), None)
        return 0, 0, b""

    def subkeys(self, key):
        root, path = key
        prefix = path + "\\" if path else ""
        names = []
        for other_root, other_path in self.registry:
            if other_root == root and other_path.startswith(prefix) and other_path != path:
                names.append(other_path[len(prefix):].split("\\")[0])
        return sorted({self.key_names.get(name, name) for name in names})

    def reg_enum_key(self, payload):
        handle, index = payload.u32(), payload.u32()
        names = self.subkeys(self.key_path(handle, None))
        if index >= len(names):
            return ERROR_NO_MORE_ITEMS, 0, b""
        return 0, 0, wstr(names[index]) + be32(len(names[index]))

    def reg_enum_value(self, payload):
        handle, index = payload.u32(), payload.u32()
        values = list(self.registry.get(self.key_path(handle, None), {}).values())
        if index >= len(values):
            return ERROR_NO_MORE_ITEMS, 0, b""
        name, value_type, data = values[index]
        return 0, 0, wstr(name) + be32(len(name), value_type, len(data)) + data

    def reg_query_value(self, payload):
        handle = payload.u32()
        name = payload.optional_wstr() or ""
        values = self.registry.get(self.key_path(handle, None), {})
        if name.lower() not in values:
            return ERROR_FILE_NOT_FOUND, 0, b""
        stored_name, value_type, data = values[name.lower()]
        return 0, 0, be32(value_type, len(data)) + data

    def reg_set_value(self, payload):
        handle = payload.u32()
        name = payload.optional_wstr() or ""
        value_type = payload.u32()
        payload.u32()
        size = payload.u32()
        self.registry[self.key_path(handle, None)][name.lower()] = (name, value_type, payload.raw(size))
        return 0, 0, b""

    def reg_delete_value(self, payload):
        handle = payload.u32()
        name = payload.optional_wstr() or ""
        values = self.registry.get(self.key_path(handle, None), {})
        return (0, 0, b"") if values.pop(name.lower(), None) else (ERROR_FILE_NOT_FOUND, 0, b"")

    def reg_delete_key(self, payload):
        handle = payload.u32()
        key = self.key_path(handle, payload.optional_wstr())
        return (0, 0, b"") if self.registry.pop(key, None) is not None else (ERROR_FILE_NOT_FOUND, 0, b"")

    def get_system_time(self, payload):
        return 1, 0, struct.pack(">8H", *self.system_time)

    def set_system_time(self, payload):
        self.system_time = struct.unpack(">8H", payload.raw(16))
        return 1, 0, b""

    def soft_reset(self, payload):
        self.processes.append(("soft reset", None))
        return None

    def nand_open(self, payload):
        return NAND_HANDLE, 87, b""

    def nand_close(self, payload):
        return int(payload.u32() == NAND_HANDLE), 0, b""

    def nand_get_info(self, payload):
        if payload.u32() != NAND_HANDLE:
            return 0, ERROR_INVALID_HANDLE, b""
        return 1, 0, be32(24544, 512, 16, 2, 767, 10)

    def nand_read_sector(self, payload):
        handle, logical, count = payload.u32(), payload.u32(), payload.u32()
        if handle != NAND_HANDLE:
            return 0, ERROR_INVALID_HANDLE, b""
        first = (logical + NAND_BASE) & 0xFFFFFFFF
        return 1, 0, b"".join(struct.pack(">I", first + index) * 128 for index in range(count))
