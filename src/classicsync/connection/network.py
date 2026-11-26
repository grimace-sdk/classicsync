import asyncio
import logging

from ..i18n import _
from .dccm import CONNECTION_PORT, ConnectionManager, PasswordRejected, encode_password
from .desktop import PROXY_BUFFER, RAPI_CONNECT_ATTEMPTS, RAPI_PASSWORD_TIMEOUT, RAPI_PORT, RAPI_RETRY_SECONDS
from ..rapi.client import RapiClient

log = logging.getLogger("classicsync.network")

DEFAULT_LISTEN = "0.0.0.0"
CONNECT_TIMEOUT = 10.0


class SocketConnection:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        peer = writer.get_extra_info("peername") or ("", 0)
        self.peer = (peer[0], peer[1])

    async def read(self, size=-1):
        return await self.reader.read(size)

    async def readexactly(self, size):
        return await self.reader.readexactly(size)

    def write(self, data):
        self.writer.write(data)

    async def drain(self):
        await self.writer.drain()

    async def flush(self):
        await self.writer.drain()

    def close(self):
        self.writer.close()

    def abort(self):
        transport = self.writer.transport
        if transport is not None:
            transport.abort()


class SocketListener:
    def __init__(self):
        self.connections = asyncio.Queue()
        self.server = None

    async def accept(self):
        return await self.connections.get()

    def close(self):
        if self.server:
            self.server.close()


class HostLinkState:
    is_up = False


class HostStack:
    def __init__(self, host=DEFAULT_LISTEN):
        self.host = host
        self.link = HostLinkState()
        self.listeners = []

    async def start_listening(self, listener, port):
        async def accepted(reader, writer):
            await listener.connections.put(SocketConnection(reader, writer))
        listener.server = await asyncio.start_server(accepted, self.host, port)

    def listen(self, port):
        listener = SocketListener()
        self.listeners.append((listener, port))
        return listener

    async def open_listeners(self):
        for listener, port in self.listeners:
            if listener.server is None:
                await self.start_listening(listener, port)

    async def connect(self, address, port, timeout=CONNECT_TIMEOUT):
        reader, writer = await asyncio.wait_for(asyncio.open_connection(address, port), timeout)
        return SocketConnection(reader, writer)


class NetworkLink:
    def __init__(self):
        self.finished = asyncio.get_running_loop().create_future()
        self.listeners = []
        self.handshaken = True
        self.closed = False
        self.close_reason = ""

    def add_listener(self, listener):
        self.listeners.append(listener)

    def close(self, reason):
        if self.closed:
            return
        self.closed = True
        self.close_reason = reason
        for listener in list(self.listeners):
            listener("closed")
        if not self.finished.done():
            self.finished.set_result(reason)


class NetworkTransport:
    baud = None

    def __init__(self, name):
        self.name = name


class NetworkDesktop:
    def __init__(self, host=DEFAULT_LISTEN, port=CONNECTION_PORT, rapi_address=None, password_provider=None,
                 partnership_policy=None):
        self.host = host
        self.port = port
        self.rapi_address = rapi_address
        self.transport = NetworkTransport(f"network {host}:{port}")
        self.stack = HostStack(host)
        self.connection_manager = ConnectionManager(self.stack, password_provider, partnership_policy, port=port,
                                                    on_lost=self._device_lost)
        self.link = None
        self.device = None
        self.device_changed = asyncio.Event()
        self.watch_task = None

    async def start(self):
        self.link = NetworkLink()
        self.connection_manager.start()
        await self.stack.open_listeners()
        self.watch_task = asyncio.create_task(self._watch_devices())

    async def _watch_devices(self):
        while True:
            announcement = await self.connection_manager.next_device()
            if self.device is not None and not self.device.lost:
                log.info("already serving a device; refusing %s", announcement.address)
                announcement.connection.abort()
                continue
            log.info("network device connected from %s", announcement.address)
            self.device = announcement
            self.device_changed.set()

    def _device_lost(self, announcement):
        if announcement is self.device:
            log.info("network device disconnected")
            self.device = None
            self.device_changed.set()
            self.link.close(_("device disconnected"))

    async def wait_for_device(self, timeout=None):
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout
        while self.device is None:
            self.device_changed.clear()
            remaining = None if deadline is None else deadline - loop.time()
            if remaining is not None and remaining <= 0:
                raise TimeoutError(_("no device connected"))
            try:
                await asyncio.wait_for(self.device_changed.wait(), remaining)
            except asyncio.TimeoutError:
                raise TimeoutError(_("no device connected")) from None
        return self.device

    def listening_port(self):
        listener = self.connection_manager.listener
        if listener is None or listener.server is None or not listener.server.sockets:
            return None
        return listener.server.sockets[0].getsockname()[1]

    def rapi_target(self):
        if self.rapi_address:
            host, _separator, port = self.rapi_address.rpartition(":")
            return host or "127.0.0.1", int(port)
        return self.device.address, RAPI_PORT

    async def connect_rapi_socket(self):
        if self.device is None:
            raise ConnectionError(_("no device connected"))
        host, port = self.rapi_target()
        last_error = None
        for attempt in range(RAPI_CONNECT_ATTEMPTS):
            try:
                connection = await self.stack.connect(host, port)
            except (OSError, asyncio.TimeoutError) as error:
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

            async def pump(source_read, destination_write, destination_drain, close):
                try:
                    while data := await source_read(PROXY_BUFFER):
                        destination_write(data)
                        await destination_drain()
                finally:
                    close()

            await asyncio.gather(pump(reader.read, device_side.write, device_side.drain, device_side.close),
                                 pump(device_side.read, writer.write, writer.drain, writer.close), return_exceptions=True)

        return await asyncio.start_server(handle, host, port)

    async def close(self):
        if self.watch_task:
            self.watch_task.cancel()
        await self.connection_manager.stop()
        if self.link:
            self.link.close(_("stopped"))
