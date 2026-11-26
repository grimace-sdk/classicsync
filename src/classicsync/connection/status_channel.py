import asyncio
import logging
import struct

log = logging.getLogger("classicsync.status")

STATUS_PORT = 999
MESSAGE_STATUS = 0x0001
MESSAGE_ERROR = 0x000A
MESSAGE_CREATE_PROGRESS = 0x005A
MESSAGE_DESTROY_PROGRESS = 0x005B
MESSAGE_PROGRESS_RANGE = 0x005C
MESSAGE_PROGRESS_POSITION = 0x005D
MAX_FIELD = 0xFFFF
UP_TO_DATE = "Up-to-date."
UP_TO_DATE_TOKEN = "$UPTODATE$"
UP_TO_DATE_TOKEN_MAJOR = 3
REQUEST_CLOSED = 0
REQUEST_STATUS = 1
REQUEST_SYNC = 2
REQUEST_SYNC_CANCEL = 3


def header(message_type, value=0):
    return struct.pack("<I", (message_type << 16) | (value & MAX_FIELD))


def up_to_date_text(os_major):
    return UP_TO_DATE_TOKEN if os_major >= UP_TO_DATE_TOKEN_MAJOR else UP_TO_DATE


def text_message(message_type, text):
    data = (text.encode("utf-16-le")[:MAX_FIELD - 3] + b"\0\0")
    return header(message_type, len(data)) + data


class StatusChannel:
    def __init__(self, host, port=STATUS_PORT):
        self.host = host
        self.port = port
        self.server = None
        self.writer = None
        self.connected = asyncio.Event()
        self.requests = asyncio.Queue()
        self.reader_task = None

    async def start(self):
        self.server = await asyncio.start_server(self._accepted, self.host, self.port)

    def listening_port(self):
        return self.server.sockets[0].getsockname()[1] if self.server and self.server.sockets else None

    async def _accepted(self, reader, writer):
        if self.writer is not None:
            self.writer.close()
        if self.reader_task is not None:
            self.reader_task.cancel()
        log.info("device status channel from %s", writer.get_extra_info("peername"))
        self.writer = writer
        self.requests = asyncio.Queue()
        self.reader_task = asyncio.create_task(self._read_requests(reader, writer))
        self.connected.set()

    async def _read_requests(self, reader, writer):
        try:
            while True:
                request = struct.unpack("<I", await reader.readexactly(4))[0]
                log.info("device status request %d", request)
                await self.requests.put(request)
                if request == REQUEST_CLOSED:
                    break
        except (asyncio.IncompleteReadError, ConnectionError):
            await self.requests.put(REQUEST_CLOSED)
        if self.writer is writer:
            self.forget()

    async def next_request(self):
        return await self.requests.get()

    async def wait_for_device(self, timeout):
        try:
            await asyncio.wait_for(self.connected.wait(), timeout)
        except asyncio.TimeoutError:
            return False
        return True

    async def send(self, data):
        if self.writer is None:
            return
        try:
            self.writer.write(data)
            await self.writer.drain()
        except ConnectionError as error:
            log.info("status channel closed: %s", error)
            self.forget()

    def forget(self):
        self.writer = None
        self.connected.clear()

    async def started(self):
        await self.send(header(MESSAGE_CREATE_PROGRESS))

    async def text(self, text):
        await self.send(text_message(MESSAGE_STATUS, text))

    async def progress(self, position, total):
        total = min(total, MAX_FIELD)
        await self.send(header(MESSAGE_PROGRESS_RANGE) + struct.pack("<I", total << 16) +
                        header(MESSAGE_PROGRESS_POSITION, min(position, total)))

    async def finished(self, text, error=False):
        await self.send(header(MESSAGE_DESTROY_PROGRESS))
        await self.send(text_message(MESSAGE_ERROR if error else MESSAGE_STATUS, text))

    def close(self):
        if self.writer is not None:
            self.writer.close()
        if self.reader_task is not None:
            self.reader_task.cancel()
        self.forget()
        if self.server:
            self.server.close()
