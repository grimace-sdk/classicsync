import asyncio
import threading


class Transport:
    name = "transport"

    async def open(self):
        pass

    async def read(self):
        raise NotImplementedError

    def write(self, data):
        raise NotImplementedError

    async def drain(self):
        pass

    async def close(self):
        pass

    async def set_baud(self, baud):
        pass

    async def set_dtr(self, active):
        pass

    @property
    def baud(self):
        return None


class TcpSerialTransport(Transport):
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.name = f"tcp:{host}:{port}"
        self.reader = None
        self.writer = None

    async def open(self):
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)

    async def read(self):
        return await self.reader.read(4096)

    def write(self, data):
        self.writer.write(data)

    async def drain(self):
        await self.writer.drain()

    async def close(self):
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except ConnectionError:
                pass


class SerialTransport(Transport):
    def __init__(self, device, baud=19200):
        self.device = device
        self.name = f"serial:{device}"
        self._baud = baud
        self.port = None
        self.loop = None
        self.queue = None
        self.thread = None
        self.stopping = threading.Event()

    @property
    def baud(self):
        return self._baud

    async def open(self):
        import serial

        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue()
        self.port = serial.Serial(self.device, self._baud, timeout=0.05, rtscts=False, dsrdtr=False)
        self.port.dtr = True
        self.port.rts = True
        self.stopping.clear()
        self.thread = threading.Thread(target=self._read_loop, name=f"serial-{self.device}", daemon=True)
        self.thread.start()

    def _read_loop(self):
        while not self.stopping.is_set():
            try:
                data = self.port.read(max(1, self.port.in_waiting))
            except Exception:
                self.loop.call_soon_threadsafe(self.queue.put_nowait, b"")
                return
            if data:
                self.loop.call_soon_threadsafe(self.queue.put_nowait, data)

    async def read(self):
        return await self.queue.get()

    def write(self, data):
        self.port.write(data)

    async def drain(self):
        await asyncio.to_thread(self.port.flush)

    async def set_baud(self, baud):
        self._baud = baud
        if self.port:
            self.port.baudrate = baud

    async def set_dtr(self, active):
        if self.port:
            self.port.dtr = active

    async def close(self):
        self.stopping.set()
        if self.thread:
            await asyncio.to_thread(self.thread.join, 1)
        if self.port:
            self.port.close()


class MemoryTransport(Transport):
    def __init__(self, name="memory"):
        self.name = name
        self.queue = asyncio.Queue()
        self.peer = None
        self.closed = False

    @classmethod
    def pair(cls):
        desktop = cls("memory-desktop")
        device = cls("memory-device")
        desktop.peer = device
        device.peer = desktop
        return desktop, device

    async def read(self):
        return await self.queue.get()

    def write(self, data):
        if not self.closed and self.peer and not self.peer.closed:
            self.peer.queue.put_nowait(bytes(data))

    async def close(self):
        if self.closed:
            return
        self.closed = True
        self.queue.put_nowait(b"")
        if self.peer:
            self.peer.queue.put_nowait(b"")


def port_has_baud(spec):
    return not (spec.startswith("tcp:") or spec == "usb" or spec.startswith("usb:"))


def open_transport(spec, baud=19200):
    if spec == "usb" or spec.startswith("usb:"):
        from .usb import UsbSerialTransport
        return UsbSerialTransport(spec)
    if spec.startswith("tcp:"):
        host, _, port = spec[4:].rpartition(":")
        return TcpSerialTransport(host or "127.0.0.1", int(port))
    return SerialTransport(spec, baud)
