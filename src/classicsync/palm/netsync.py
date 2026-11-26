import struct

HEADER = struct.Struct(">BBI")
RITUAL_HEADER = struct.Struct(">BBHI")
RITUAL_ARGUMENT = struct.Struct(">HI")

TYPE_DATA = 1
TYPE_CANCEL = 2
TYPE_DISCONNECT = 4
TYPE_ABORT = 8
TYPE_MASK = 0x0F
HANDHELD_XID = 0xFF
MAX_XID = 0xFE

RITUAL_REPLY = 0x80
RITUAL_HELLO = 0x90
RITUAL_FAIL = 0x11
RITUAL_OPTIONS = 0x12
RITUAL_CONFIRM = 0x13
RITUAL_ARGUMENT_ID = 0x20

UNLIMITED_BLOCK = 0xFFFFFFFF
DESKTOP_TIMEOUT = 60
OPTIONS_ARGUMENT_SIZE = 36
CONFIRM_ARGUMENT_SIZE = 32
CONFIRM_ECHO_SIZE = 8


class NetSyncError(ConnectionError):
    pass


def ritual_message(command, argument):
    return RITUAL_HEADER.pack(command, 1, 0, 0) + RITUAL_ARGUMENT.pack(RITUAL_ARGUMENT_ID, len(argument)) + argument


def ritual_argument(message):
    if len(message) < RITUAL_HEADER.size + RITUAL_ARGUMENT.size:
        return b""
    _identifier, length = RITUAL_ARGUMENT.unpack_from(message, RITUAL_HEADER.size)
    start = RITUAL_HEADER.size + RITUAL_ARGUMENT.size
    return message[start:start + length]


def desktop_options():
    argument = struct.pack(">I", UNLIMITED_BLOCK) + struct.pack("<HH", DESKTOP_TIMEOUT, DESKTOP_TIMEOUT)
    return ritual_message(RITUAL_OPTIONS, argument.ljust(OPTIONS_ARGUMENT_SIZE, b"\0"))


def desktop_confirm(handheld_options):
    echoed = ritual_argument(handheld_options)[:CONFIRM_ECHO_SIZE].ljust(CONFIRM_ECHO_SIZE, b"\0")
    argument = echoed + bytes(CONFIRM_ARGUMENT_SIZE - CONFIRM_ECHO_SIZE - 1) + b"\x01"
    return ritual_message(RITUAL_CONFIRM, argument)


class NetSyncLink:
    def __init__(self, transport):
        self.transport = transport
        self.buffer = b""
        self.xid = 0

    async def _read_exactly(self, count):
        while len(self.buffer) < count:
            data = await self.transport.read()
            if not data:
                raise NetSyncError("the handheld closed the connection")
            self.buffer += data
        data, self.buffer = self.buffer[:count], self.buffer[count:]
        return data

    async def receive(self):
        kind, xid, length = HEADER.unpack(await self._read_exactly(HEADER.size))
        payload = await self._read_exactly(length)
        message_type = kind & TYPE_MASK
        if message_type == TYPE_DISCONNECT:
            raise NetSyncError("the handheld disconnected")
        if message_type in (TYPE_CANCEL, TYPE_ABORT):
            raise NetSyncError("the handheld cancelled the HotSync")
        return xid, payload

    async def send(self, payload, xid=None):
        if xid is None:
            self.xid = self.xid % MAX_XID + 1
            xid = self.xid
        self.transport.write(HEADER.pack(TYPE_DATA, xid, len(payload)))
        self.transport.write(payload)
        await self.transport.drain()
        return xid

    async def request(self, payload):
        xid = await self.send(payload)
        reply_xid, reply = await self.receive()
        if reply_xid != xid:
            raise NetSyncError(f"reply for transaction {reply_xid}, expected {xid}")
        return reply

    async def accept(self):
        _xid, hello = await self.receive()
        if not hello or hello[0] != RITUAL_HELLO:
            raise NetSyncError(f"unexpected first message {hello[:1].hex()}")
        options = await self.request(desktop_options())
        if options[:1] != bytes([RITUAL_OPTIONS | RITUAL_REPLY]):
            raise NetSyncError(f"handshake refused: {options[:4].hex()}")
        confirmed = await self.request(desktop_confirm(options))
        if confirmed[:1] != bytes([RITUAL_CONFIRM | RITUAL_REPLY]):
            raise NetSyncError(f"handshake not confirmed: {confirmed[:4].hex()}")
        return hello
