import asyncio
import logging

from ..i18n import _
from ..link.ppp import ROLE_DESKTOP, PppLink
from ..net.stack import NetworkStack
from ..rapi.client import RapiClient
from .dccm import ConnectionManager, PasswordRejected, encode_password

log = logging.getLogger("classicsync.desktop")

DESKTOP_IP = "192.168.55.100"
DEVICE_IP = "192.168.55.101"
RAPI_PORT = 990
RAPI_CONNECT_ATTEMPTS = 5
RAPI_RETRY_SECONDS = 2.0
RAPI_PASSWORD_TIMEOUT = 20.0
PROXY_BUFFER = 16384


class Desktop:
    def __init__(self, transport, desktop_ip=DESKTOP_IP, device_ip=DEVICE_IP, password_provider=None, partnership_policy=None):
        self.transport = transport
        self.link = PppLink(transport, ROLE_DESKTOP, local_ip=desktop_ip, peer_ip=device_ip, dns_ip=desktop_ip)
        self.stack = NetworkStack(self.link)
        self.connection_manager = ConnectionManager(self.stack, password_provider, partnership_policy)
        self.device = None
        self.device_changed = asyncio.Event()
        self.watch_task = None

    async def start(self):
        await self.transport.open()
        await self.stack.start()
        self.connection_manager.start()
        await self.link.start()
        self.link.add_listener(self._link_event)
        self.watch_task = asyncio.create_task(self._watch_devices())

    def _link_event(self, event):
        if event in ("down", "closed") and self.device:
            log.info("device disconnected")
            self.device = None
            self.device_changed.set()

    async def _watch_devices(self):
        while True:
            announcement = await self.connection_manager.next_device()
            self.device = announcement
            self.device_changed.set()

    async def wait_for_device(self, timeout=None):
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout
        while self.device is None:
            if self.link.closed:
                raise ConnectionError(_("link closed: {reason}").format(reason=self.link.close_reason))
            self.device_changed.clear()
            remaining = None if deadline is None else deadline - loop.time()
            if remaining is not None and remaining <= 0:
                raise TimeoutError(_("no device connected"))
            waiter = asyncio.create_task(self.device_changed.wait())
            done, pending = await asyncio.wait({waiter, self.link.finished}, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
            if waiter not in done:
                waiter.cancel()
        return self.device

    async def connect_rapi_socket(self):
        last_error = None
        for attempt in range(RAPI_CONNECT_ATTEMPTS):
            try:
                connection = await self.stack.connect(RAPI_PORT)
            except (ConnectionError, TimeoutError) as error:
                last_error = error
                await asyncio.sleep(RAPI_RETRY_SECONDS)
                continue
            await self._unlock_rapi(connection)
            return connection
        raise ConnectionError(_("device RAPI server not reachable: {error}").format(error=last_error))

    async def _unlock_rapi(self, connection):
        device = self.device
        if not device or not device.key or device.password is None:
            return
        platform = device.info.platform if device.info else ""
        connection.write(encode_password(device.password, device.key, platform))
        accepted = await asyncio.wait_for(connection.readexactly(1), RAPI_PASSWORD_TIMEOUT)
        if not accepted[0]:
            connection.abort()
            raise PasswordRejected("device rejected the password for RAPI")

    async def open_rapi(self):
        return RapiClient(await self.connect_rapi_socket())

    async def serve_rapi_proxy(self, host="127.0.0.1", port=9990):
        async def handle(reader, writer):
            try:
                device_side = await self.connect_rapi_socket()
            except ConnectionError as error:
                log.info("proxy: %s", error)
                writer.close()
                return
            log.info("proxy: client %s connected", writer.get_extra_info("peername"))

            async def to_device():
                try:
                    while data := await reader.read(PROXY_BUFFER):
                        device_side.write(data)
                        await device_side.drain()
                finally:
                    device_side.close()

            async def to_client():
                try:
                    while data := await device_side.read(PROXY_BUFFER):
                        writer.write(data)
                        await writer.drain()
                finally:
                    writer.close()

            results = await asyncio.gather(to_device(), to_client(), return_exceptions=True)
            for result in results:
                if isinstance(result, Exception) and not isinstance(result, (ConnectionError, asyncio.CancelledError)):
                    log.warning("proxy: %r", result)

        return await asyncio.start_server(handle, host, port)

    async def close(self):
        if self.watch_task:
            self.watch_task.cancel()
        await self.connection_manager.stop()
        await self.link.close()
