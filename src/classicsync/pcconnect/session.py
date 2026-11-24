import asyncio
import logging
from dataclasses import dataclass

from ..i18n import _
from ..link.pcconnect import DEFAULT_USB_SPEC, SERIAL_BAUD, PcConnectLink
from ..link.transport import SerialTransport, TcpSerialTransport
from ..rapi.client import HKEY_LOCAL_MACHINE, REG_SZ, RapiClient
from ..rapi.marshal import decode_wide
from .bridge import BridgeStream, RapiBridge, serve_bridge_connection
from .client import WilClient, format_uuid

log = logging.getLogger("classicsync.pcconnect")

HANDSHAKE_ATTEMPTS = 60
RESET_SETTLE_SECONDS = 8.0
RETRY_SECONDS = 2.0
PLATFORM_KEY = "Platform"


@dataclass
class PcConnectDevice:
    server_version: int
    uuid: str
    system_disk: str
    user_disk: str
    platform_name: str
    platform_release: str

    pc_connect = True

    @property
    def server_version_text(self):
        return f"{self.server_version >> 16}.{self.server_version & 0xFFFF:02d}"

    def describe(self):
        return _("{platform} (PC Connect server {version}), unit ID {uuid}, system disk {system}, user disk {user}").format(
            platform=self.platform_name or _("Casio PC Connect device"), version=self.server_version_text, uuid=self.uuid or _("unknown"),
            system=self.system_disk or _("unknown"), user=self.user_disk or _("unknown"))


def open_pc_connect_transport(spec, baud=None):
    if spec == "usb" or spec.startswith("usb:"):
        from ..link.usb import LINE_STATE_DTR_RTS, UsbSerialTransport
        return UsbSerialTransport(DEFAULT_USB_SPEC if spec == "usb" else spec, line_state=LINE_STATE_DTR_RTS, coalesce_writes=False)
    if spec.startswith("tcp:"):
        host, _separator, port = spec[4:].rpartition(":")
        return TcpSerialTransport(host or "127.0.0.1", int(port))
    return SerialTransport(spec, baud or SERIAL_BAUD)


async def read_platform_strings(wil):
    reply, handle = await wil.reg_open_key(HKEY_LOCAL_MACHINE, PLATFORM_KEY)
    if reply.value:
        return "", ""
    values = []
    try:
        for name in ("Name", "Release"):
            query_reply, value = await wil.reg_query_value(handle, name)
            values.append(decode_wide(value[1]) if value and value[0] == REG_SZ else "")
    finally:
        await wil.reg_close_key(handle)
    return values[0], values[1]


class PcConnectSession:
    def __init__(self, transport, handshake_attempts=HANDSHAKE_ATTEMPTS, reset_settle_seconds=RESET_SETTLE_SECONDS,
                 retry_seconds=RETRY_SECONDS, keepalive_seconds=None):
        self.transport = transport
        self.handshake_attempts = handshake_attempts
        self.reset_settle_seconds = reset_settle_seconds
        self.retry_seconds = retry_seconds
        self.keepalive_seconds = keepalive_seconds
        self.link = None
        self.wil = None
        self.bridge = None
        self.device = None
        self.device_changed = asyncio.Event()
        self.run_task = None
        self.last_error = None
        self.closing = False

    async def start(self):
        self.closing = False
        self.run_task = asyncio.create_task(self._run())

    async def _run(self):
        while not self.closing:
            try:
                await self._connect()
            except (ConnectionError, OSError, TimeoutError) as error:
                self.last_error = error
                log.info("PC Connect: %s", error)
                await self._drop_link()
                await asyncio.sleep(self.retry_seconds)
                continue
            self.last_error = None
            self.device_changed.set()
            await self.link.closed.wait()
            log.info("device disconnected: %s", self.link.close_reason)
            self.device = None
            self.bridge = None
            self.device_changed.set()
            await self._drop_link()

    async def _connect(self):
        await self.transport.open()
        link_options = {} if self.keepalive_seconds is None else {"keepalive_seconds": self.keepalive_seconds}
        self.link = PcConnectLink(self.transport, **link_options)
        if not await self.link.handshake(self.handshake_attempts):
            await self.transport.close()
            if hasattr(self.transport, "reset_device"):
                log.info("no handshake; resetting the USB device so it starts a connection")
                await self.transport.reset_device()
                await asyncio.sleep(self.reset_settle_seconds)
            raise ConnectionError(_("the device did not answer the PC Connect handshake; choose Connect Now on the device"))
        self.link.start()
        self.wil = WilClient(self.link)
        server_version = await self.wil.version()
        uuid = await self.wil.uuid()
        system_disk = await self.wil.system_disk()
        user_disk = await self.wil.inner_user_disk()
        platform_name, platform_release = await read_platform_strings(self.wil)
        self.device = PcConnectDevice(server_version, format_uuid(uuid) if uuid else "", system_disk, user_disk, platform_name, platform_release)
        self.bridge = RapiBridge(self.wil, self.device)
        log.info("connected: %s", self.device.describe())

    async def _drop_link(self):
        if self.link:
            await self.link.close()
        await self.transport.close()

    async def wait_for_device(self, timeout=None):
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout
        while self.device is None:
            if self.run_task is None or self.run_task.done():
                raise ConnectionError(_("the PC Connect session is not running"))
            remaining = None if deadline is None else deadline - loop.time()
            if remaining is not None and remaining <= 0:
                raise TimeoutError(self._timeout_message())
            self.device_changed.clear()
            try:
                await asyncio.wait_for(self.device_changed.wait(), remaining)
            except asyncio.TimeoutError:
                raise TimeoutError(self._timeout_message()) from None
        return self.device

    def _timeout_message(self):
        if self.last_error:
            return _("no device connected ({error})").format(error=self.last_error)
        return _("no device connected")

    async def open_rapi(self):
        if self.bridge is None:
            raise ConnectionError(_("no device connected"))
        return RapiClient(BridgeStream(self.bridge))

    async def serve_rapi_proxy(self, host="127.0.0.1", port=9990):
        async def handle(reader, writer):
            if self.bridge is None:
                writer.close()
                return
            log.info("proxy: client %s connected", writer.get_extra_info("peername"))
            await serve_bridge_connection(self.bridge, reader, writer)

        return await asyncio.start_server(handle, host, port)

    async def close(self):
        self.closing = True
        if self.run_task:
            self.run_task.cancel()
            try:
                await self.run_task
            except (asyncio.CancelledError, Exception):
                pass
        await self._drop_link()
        self.device = None
        self.bridge = None
