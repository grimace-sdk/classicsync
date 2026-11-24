import asyncio
import logging
import struct
from dataclasses import dataclass

from ..i18n import _

log = logging.getLogger("classicsync.pcconnect")

CASIO_VENDOR_ID = 0x07CF
BE300_PRODUCT_ID = 0x2002
DEFAULT_USB_SPEC = f"usb:{CASIO_VENDOR_ID:04x}:{BE300_PRODUCT_ID:04x}"
SERIAL_BAUD = 115200

REQUEST = 0x10
REPLY = 0x11
HANDSHAKE = 0x55
BUSY = 0x5A
RESEND = 0x20
HEADER_SIZE = 10
LARGE_TRANSFER = 0x0401
LARGE_ANNOUNCEMENT_SIZE = 14
MAX_FRAME_SIZE = 0xFFFF
SEQUENCE_MASK = 0x7F
RETRANSMISSION = 0x80

HANDSHAKE_ROUNDS = 2
HANDSHAKE_READ_SECONDS = 0.25
REPLY_TIMEOUT = 6.0
KEEPALIVE_SECONDS = 0.15
RETRANSMIT_LIMIT = 3


def byte_sum(data):
    return sum(data) & 0xFFFF


def build_frame(command, payload=b"", sequence=0, frame_type=REQUEST):
    payload = bytes(payload)
    total = HEADER_SIZE + len(payload)
    if total > MAX_FRAME_SIZE:
        raise ValueError(f"PC Connect frame too large: {total} bytes")
    head = struct.pack(">BBHHH", frame_type, sequence & 0xFF, total, command, byte_sum(payload))
    return head + struct.pack(">H", byte_sum(head)) + payload


def frame_checksums_valid(frame):
    head_sum, = struct.unpack(">H", frame[8:10])
    payload_sum, = struct.unpack(">H", frame[6:8])
    return byte_sum(frame[:8]) == head_sum and byte_sum(frame[HEADER_SIZE:]) == payload_sum


@dataclass
class Frame:
    frame_type: int
    sequence: int
    command: int
    payload: bytes
    raw: bytes

    @classmethod
    def parse(cls, raw):
        raw = bytes(raw)
        frame_type, sequence, _length, command = struct.unpack(">BBHH", raw[:6])
        return cls(frame_type, sequence, command, raw[HEADER_SIZE:], raw)


@dataclass
class WilReply:
    command: int
    value: int
    error: int
    data: bytes

    @classmethod
    def from_frame(cls, frame):
        payload = frame.payload
        value = struct.unpack(">I", payload[:4])[0] if len(payload) >= 4 else 0
        error = struct.unpack(">I", payload[4:8])[0] if len(payload) >= 8 else 0
        return cls(frame.command, value, error, payload[8:])


class FrameParser:
    def __init__(self, accepted_type=REPLY, on_handshake=None, on_busy=None, on_resend=None):
        self.accepted_type = accepted_type
        self.on_handshake = on_handshake
        self.on_busy = on_busy
        self.on_resend = on_resend
        self.buffer = bytearray()
        self.large_size = 0

    def feed(self, data):
        self.buffer += data
        frames = []
        while self.buffer:
            if self.buffer[0] != self.accepted_type:
                self._control_byte(self.buffer.pop(0))
                continue
            if len(self.buffer) < HEADER_SIZE:
                break
            length, command = struct.unpack(">HH", self.buffer[2:6])
            if command == LARGE_TRANSFER and length == LARGE_ANNOUNCEMENT_SIZE:
                if len(self.buffer) < LARGE_ANNOUNCEMENT_SIZE:
                    break
                self.large_size = struct.unpack(">I", self.buffer[10:14])[0]
                del self.buffer[:LARGE_ANNOUNCEMENT_SIZE]
                continue
            if length == 0 and self.large_size >= HEADER_SIZE:
                length = self.large_size
            elif length < HEADER_SIZE:
                del self.buffer[0]
                continue
            if len(self.buffer) < length:
                break
            frames.append(Frame.parse(self.buffer[:length]))
            del self.buffer[:length]
            self.large_size = 0
        return frames

    def _control_byte(self, value):
        if value == HANDSHAKE and self.on_handshake:
            self.on_handshake()
        elif value == BUSY and self.on_busy:
            self.on_busy()
        elif value == RESEND and self.on_resend:
            self.on_resend()


class PcConnectLink:
    def __init__(self, transport, reply_timeout=REPLY_TIMEOUT, keepalive_seconds=KEEPALIVE_SECONDS):
        self.transport = transport
        self.reply_timeout = reply_timeout
        self.reply_timeout_for_call = reply_timeout
        self.keepalive_seconds = keepalive_seconds
        self.parser = FrameParser(on_handshake=self._echo_keepalive, on_busy=self._device_busy, on_resend=self._resend_requested)
        self.lock = asyncio.Lock()
        self.sequence = 0
        self.pending = None
        self.pending_command = None
        self.pending_sequence = None
        self.pending_frame = None
        self.retransmissions = 0
        self.reply_deadline = 0.0
        self.reader_task = None
        self.keepalive_task = None
        self.closed = asyncio.Event()
        self.close_reason = ""
        self.connected = False

    async def handshake(self, attempts):
        consecutive = 0
        for attempt in range(attempts):
            self.transport.write(bytes([HANDSHAKE]))
            await self.transport.drain()
            try:
                data = await asyncio.wait_for(self.transport.read(), HANDSHAKE_READ_SECONDS)
            except asyncio.TimeoutError:
                consecutive = 0
                continue
            if data == b"":
                raise ConnectionError(_("the device went away during the PC Connect handshake"))
            if data[-1] == HANDSHAKE:
                consecutive += 1
                if consecutive >= HANDSHAKE_ROUNDS:
                    return True
            else:
                consecutive = 0
        return False

    def start(self):
        self.connected = True
        self.closed.clear()
        self.reader_task = asyncio.create_task(self._read_loop())
        if self.keepalive_seconds:
            self.keepalive_task = asyncio.create_task(self._keepalive_loop())

    async def _read_loop(self):
        try:
            while True:
                data = await self.transport.read()
                if not data:
                    self._mark_closed(_("the device closed the PC Connect link"))
                    return
                for frame in self.parser.feed(data):
                    self._deliver(frame)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._mark_closed(str(error))

    async def _keepalive_loop(self):
        while not self.closed.is_set():
            await asyncio.sleep(self.keepalive_seconds)
            if not self.lock.locked() and not self.closed.is_set():
                self.transport.write(bytes([HANDSHAKE]))

    def _echo_keepalive(self):
        if not self.closed.is_set():
            self.transport.write(bytes([HANDSHAKE]))

    def _device_busy(self):
        if self.pending is not None:
            self.reply_deadline = asyncio.get_running_loop().time() + self.reply_timeout_for_call

    def _resend_requested(self):
        if self.pending is None or self.pending.done() or self.retransmissions >= RETRANSMIT_LIMIT:
            return
        self.retransmissions += 1
        log.info("device asked for command 0x%04x again", self.pending_command)
        frame = bytearray(self.pending_frame)
        frame[1] = self.pending_sequence | RETRANSMISSION
        frame[8:10] = struct.pack(">H", byte_sum(frame[:8]))
        self._write_frame(bytes(frame))

    def _deliver(self, frame):
        if self.pending is None or self.pending.done():
            log.debug("unexpected frame 0x%04x", frame.command)
            return
        if frame.command != self.pending_command or (frame.sequence & SEQUENCE_MASK) != self.pending_sequence:
            log.info("discarding stale reply 0x%04x sequence %d", frame.command, frame.sequence)
            return
        self.pending.set_result(frame)

    def _mark_closed(self, reason):
        if self.closed.is_set():
            return
        self.connected = False
        self.close_reason = reason
        self.closed.set()
        if self.pending is not None and not self.pending.done():
            self.pending.set_exception(ConnectionError(reason))

    def _write_frame(self, frame):
        self.transport.write(frame[:HEADER_SIZE])
        if len(frame) > HEADER_SIZE:
            self.transport.write(frame[HEADER_SIZE:])

    async def call(self, command, payload=b"", expect_reply=True, timeout=None):
        async with self.lock:
            if self.closed.is_set() or not self.connected:
                raise ConnectionError(self.close_reason or _("the PC Connect link is closed"))
            loop = asyncio.get_running_loop()
            self.sequence = (self.sequence + 1) & SEQUENCE_MASK
            frame = build_frame(command, payload, self.sequence)
            self.pending = loop.create_future()
            self.pending_command = command
            self.pending_sequence = self.sequence
            self.pending_frame = frame
            self.retransmissions = 0
            self.reply_timeout_for_call = timeout or self.reply_timeout
            try:
                self._write_frame(frame)
                await self.transport.drain()
                if not expect_reply:
                    return None
                self.reply_deadline = loop.time() + self.reply_timeout_for_call
                while True:
                    remaining = self.reply_deadline - loop.time()
                    if remaining <= 0:
                        raise TimeoutError(_("no reply to PC Connect command 0x{command:04x}").format(command=command))
                    try:
                        reply = await asyncio.wait_for(asyncio.shield(self.pending), remaining)
                    except asyncio.TimeoutError:
                        continue
                    return WilReply.from_frame(reply)
            finally:
                self.pending = None
                self.pending_frame = None

    async def close(self):
        self._mark_closed(_("closed"))
        for task in (self.keepalive_task, self.reader_task):
            if task:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self.keepalive_task = None
        self.reader_task = None
