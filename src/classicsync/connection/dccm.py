import asyncio
import logging
import struct
from dataclasses import dataclass, field

from ..rapi.structures import PROCESSOR_NAMES

log = logging.getLogger("classicsync.dccm")

CONNECTION_PORT = 5679
KEEPALIVE = 0x12345678
KEEPALIVE_INTERVAL = 5.0
KEEPALIVE_RESPONSE_WAIT = 9.0
PASSWORD_TIMEOUT = 20.0
KEEPALIVE_GRACE = 60.0
INFO_BLOCK_TIMEOUT = 4.0
INFO_BLOCK_HEADER = 0x24
INFO_BLOCK_MAX = 0x800
MAX_PLATFORMS = 6

STATUS_NETWORK_DISABLED = 1
STATUS_SERIAL_DISABLED = 2
STATUS_NO_PARTNERSHIP = 3
STATUS_SYNC_DISABLED = 4

FLAG_REMOTE_SYNC = 0x01
FLAG_PLATFORM_VERSIONS = 0x04

CASE_SENSITIVE_PASSWORD_PLATFORMS = {"PocketPC", "SmartPhone"}


def _string_end(block, offset):
    end = offset
    while end + 1 < len(block):
        if not block[end] and not block[end + 1]:
            return end
        end += 2
    raise ValueError(f"device info string at 0x{offset:x} is not terminated inside the block")


def _string_at(block, offset):
    if not offset:
        return ""
    if offset < INFO_BLOCK_HEADER or offset >= len(block):
        raise ValueError(f"device info string offset 0x{offset:x} is outside the block")
    return block[offset:_string_end(block, offset)].decode("utf-16-le", errors="replace")


def _strings_from(block, offset, limit):
    strings = []
    while offset and offset < len(block) and len(strings) < limit:
        end = _string_end(block, offset)
        if end == offset:
            break
        strings.append(block[offset:end].decode("utf-16-le", errors="replace"))
        offset = end + 2
    return strings, offset


@dataclass
class DeviceInfo:
    os_major: int = 1
    os_minor: int = 0
    os_build: int = 0
    processor_type: int = 0
    flags: int = 0
    partner_ids: tuple = (0, 0)
    name: str = ""
    platform: str = ""
    oem_info: str = ""
    platforms: list = field(default_factory=list)
    raw: bytes = field(default=b"", repr=False)

    @classmethod
    def parse(cls, block):
        if not INFO_BLOCK_HEADER < len(block) <= INFO_BLOCK_MAX:
            raise ValueError(f"device info block length {len(block)} is outside 0x{INFO_BLOCK_HEADER:x}-0x{INFO_BLOCK_MAX:x}")
        _, major, minor, build, processor, flags, partner_one, partner_two, name_offset, platform_offset, oem_offset = struct.unpack(
            "<IBBHIIIIIII", block[:INFO_BLOCK_HEADER])
        platform = _string_at(block, platform_offset)
        oem_info = _string_at(block, oem_offset)
        platforms = []
        if flags & FLAG_PLATFORM_VERSIONS and platform_offset:
            names, _ = _strings_from(block, platform_offset, MAX_PLATFORMS)
            version_offset = _string_end(block, oem_offset) + 2 if oem_offset else 0
            for name in names:
                if version_offset and version_offset + 8 <= len(block):
                    platforms.append((name, *struct.unpack("<II", block[version_offset:version_offset + 8])))
                    version_offset += 8
                else:
                    platforms.append((name, None, None))
        return cls(
            os_major=major, os_minor=minor, os_build=build, processor_type=processor, flags=flags,
            partner_ids=(partner_one, partner_two), name=_string_at(block, name_offset), platform=platform,
            oem_info=oem_info, platforms=platforms, raw=bytes(block),
        )

    @property
    def remote_sync(self):
        return bool(self.flags & FLAG_REMOTE_SYNC)

    @property
    def processor_name(self):
        return PROCESSOR_NAMES.get(self.processor_type, f"type {self.processor_type}")


def encode_password(password, key, platform=""):
    key_byte = key & 0xFF
    if platform not in CASE_SENSITIVE_PASSWORD_PLATFORMS:
        password = password.lower()
    encoded = (password + "\0").encode("utf-16-le")
    return struct.pack("<H", len(encoded) & 0xFF) + bytes(byte ^ key_byte for byte in encoded)


@dataclass
class DeviceAnnouncement:
    connection: object
    address: str
    key: int
    info: DeviceInfo = None
    password: str = None
    lost: bool = False

    @property
    def legacy(self):
        return self.info is None

    @property
    def password_protected(self):
        return self.key != 0


class PasswordRejected(Exception):
    pass


class ConnectionManager:
    def __init__(self, stack, password_provider=None, partnership_policy=None, port=CONNECTION_PORT, on_lost=None):
        self.stack = stack
        self.password_provider = password_provider
        self.partnership_policy = partnership_policy
        self.port = port
        self.on_lost = on_lost
        self.listener = None
        self.sessions = asyncio.Queue()
        self.accept_task = None
        self.keepalive_tasks = set()

    def start(self):
        self.listener = self.stack.listen(self.port)
        self.accept_task = asyncio.create_task(self._accept_loop())

    async def stop(self):
        if self.accept_task:
            self.accept_task.cancel()
        for task in list(self.keepalive_tasks):
            task.cancel()
        if self.listener:
            self.listener.close()

    async def next_device(self):
        return await self.sessions.get()

    async def _accept_loop(self):
        while True:
            connection = await self.listener.accept()
            asyncio.create_task(self._handle(connection))

    async def _handle(self, connection):
        address = connection.peer[0]
        try:
            key = struct.unpack("<I", await asyncio.wait_for(connection.readexactly(4), PASSWORD_TIMEOUT))[0]
            info = await self._read_info_block(connection)
            announcement = DeviceAnnouncement(connection, address, key, info)
            if info:
                log.info("device %r, Windows CE %d.%02d build %d, %s, %s", info.name, info.os_major, info.os_minor,
                         info.os_build, info.platform or "unknown platform", info.processor_name)
            else:
                log.info("version 1 device at %s (key only)", address)
            if key:
                await self._authenticate(announcement)
            if info and self.partnership_policy:
                status = await self.partnership_policy(announcement)
                if status:
                    log.info("refusing device with status %d", status)
                    connection.write(struct.pack("<I", status))
                    await connection.flush()
                    connection.close()
                    return
            if info:
                task = asyncio.create_task(self._keepalive(announcement))
                self.keepalive_tasks.add(task)
                task.add_done_callback(self.keepalive_tasks.discard)
            else:
                connection.close()
            await self.sessions.put(announcement)
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.TimeoutError, PasswordRejected, ValueError) as error:
            log.info("device connection on %d ended: %s", CONNECTION_PORT, error or type(error).__name__)
            connection.abort()

    async def _read_info_block(self, connection):
        try:
            header = await asyncio.wait_for(connection.readexactly(4), INFO_BLOCK_TIMEOUT)
        except asyncio.TimeoutError:
            return None
        except asyncio.IncompleteReadError as error:
            if not error.partial:
                return None
            raise
        length = struct.unpack("<I", header)[0]
        if length > INFO_BLOCK_MAX:
            raise ValueError(f"device info block length {length} is implausible")
        return DeviceInfo.parse(await connection.readexactly(length))

    async def _authenticate(self, announcement):
        if not self.password_provider:
            raise PasswordRejected("device is password protected and no password is available")
        for attempt in range(3):
            password = await self.password_provider(announcement, attempt)
            if password is None:
                raise PasswordRejected("no password given")
            platform = announcement.info.platform if announcement.info else ""
            announcement.connection.write(encode_password(password, announcement.key, platform))
            result = struct.unpack("<H", await asyncio.wait_for(announcement.connection.readexactly(2), PASSWORD_TIMEOUT))[0]
            if result:
                announcement.password = password
                return
            log.info("device rejected the password")
        raise PasswordRejected("device rejected the password")

    async def _await_keepalive(self, connection):
        try:
            return await asyncio.wait_for(connection.readexactly(4), KEEPALIVE_RESPONSE_WAIT)
        except asyncio.TimeoutError:
            if not self.stack.link.is_up:
                raise
            log.info("device slow to answer keepalive; link still up, waiting up to %d s", KEEPALIVE_GRACE)
            return await asyncio.wait_for(connection.readexactly(4), KEEPALIVE_GRACE - KEEPALIVE_RESPONSE_WAIT)

    async def _keepalive(self, announcement):
        connection = announcement.connection
        ping = struct.pack("<I", KEEPALIVE)
        try:
            while True:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                connection.write(ping)
                reply = await self._await_keepalive(connection)
                if reply != ping:
                    log.info("unexpected keepalive reply %s", reply.hex())
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError) as error:
            log.info("device stopped answering keepalives: %s", error or type(error).__name__)
            connection.abort()
            announcement.lost = True
            if self.on_lost:
                self.on_lost(announcement)
