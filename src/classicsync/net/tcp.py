import asyncio
import logging
import os
import struct
import time
from dataclasses import dataclass

from . import ipv4

log = logging.getLogger("classicsync.tcp")

FIN = 0x01
SYN = 0x02
RST = 0x04
PSH = 0x08
ACK = 0x10

OPTION_END = 0
OPTION_NOP = 1
OPTION_MSS = 2

CLOSED = "CLOSED"
LISTEN = "LISTEN"
SYN_SENT = "SYN_SENT"
SYN_RECEIVED = "SYN_RECEIVED"
ESTABLISHED = "ESTABLISHED"
FIN_WAIT_1 = "FIN_WAIT_1"
FIN_WAIT_2 = "FIN_WAIT_2"
CLOSE_WAIT = "CLOSE_WAIT"
CLOSING = "CLOSING"
LAST_ACK = "LAST_ACK"
TIME_WAIT = "TIME_WAIT"

SENDING_STATES = {ESTABLISHED, CLOSE_WAIT, FIN_WAIT_1, CLOSING, LAST_ACK}
RECEIVING_STATES = {ESTABLISHED, FIN_WAIT_1, FIN_WAIT_2}

DEFAULT_PEER_MSS = 536
RECEIVE_CAPACITY = 32768
SEND_HIGH_WATER = 65536
INITIAL_RTO = 3.0
MIN_RTO = 1.0
MAX_RTO = 60.0
MAX_RETRIES = 12
TIME_WAIT_SECONDS = 1.0

SEQUENCE_MODULUS = 1 << 32


def seq_add(a, b):
    return (a + b) % SEQUENCE_MODULUS


def seq_diff(a, b):
    difference = (a - b) % SEQUENCE_MODULUS
    return difference - SEQUENCE_MODULUS if difference >= 1 << 31 else difference


def seq_lt(a, b):
    return seq_diff(a, b) < 0


def seq_le(a, b):
    return seq_diff(a, b) <= 0


class ConnectionReset(ConnectionError):
    pass


@dataclass
class Segment:
    source_port: int
    destination_port: int
    sequence: int
    acknowledgement: int
    flags: int
    window: int
    payload: bytes
    mss: int = None

    @classmethod
    def parse(cls, data, source, destination):
        if len(data) < 20:
            return None
        if ipv4.checksum(ipv4.pseudo_header(source, destination, ipv4.PROTOCOL_TCP, len(data)) + data) != 0:
            return None
        source_port, destination_port, sequence, acknowledgement, offset_byte, flags, window = struct.unpack("!HHIIBBH", data[:16])
        header_length = (offset_byte >> 4) * 4
        if header_length < 20 or header_length > len(data):
            return None
        mss = None
        options = data[20:header_length]
        position = 0
        while position < len(options):
            kind = options[position]
            if kind == OPTION_END:
                break
            if kind == OPTION_NOP:
                position += 1
                continue
            if position + 1 >= len(options):
                break
            length = options[position + 1]
            if length < 2:
                break
            if kind == OPTION_MSS and length == 4:
                mss = struct.unpack("!H", options[position + 2:position + 4])[0]
            position += length
        return cls(source_port, destination_port, sequence, acknowledgement, flags, window, bytes(data[header_length:]), mss)

    def build(self, source, destination):
        options = struct.pack("!BBH", OPTION_MSS, 4, self.mss) if self.mss else b""
        header_length = 20 + len(options)
        header = struct.pack(
            "!HHIIBBHHH", self.source_port, self.destination_port, self.sequence, self.acknowledgement,
            (header_length // 4) << 4, self.flags, self.window, 0, 0,
        ) + options
        segment = header + self.payload
        value = ipv4.checksum(ipv4.pseudo_header(source, destination, ipv4.PROTOCOL_TCP, len(segment)) + segment)
        return segment[:16] + struct.pack("!H", value) + segment[18:]

    def describe(self):
        names = "".join(name for bit, name in ((SYN, "S"), (FIN, "F"), (RST, "R"), (PSH, "P"), (ACK, ".")) if self.flags & bit)
        return f"{self.source_port}>{self.destination_port} [{names}] seq={self.sequence} ack={self.acknowledgement} win={self.window} len={len(self.payload)}"


class TcpConnection:
    def __init__(self, stack, local_ip, local_port, remote_ip, remote_port):
        self.stack = stack
        self.loop = stack.loop
        self.local_ip = local_ip
        self.local_port = local_port
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self.state = CLOSED
        self.iss = int.from_bytes(os.urandom(4), "big")
        self.snd_una = self.iss
        self.snd_nxt = self.iss
        self.snd_max = self.iss
        self.snd_wnd = 0
        self.data_start = seq_add(self.iss, 1)
        self.send_buffer = bytearray()
        self.fin_queued = False
        self.fin_sent = False
        self.fin_sequence = None
        self.irs = 0
        self.rcv_nxt = 0
        self.receive_buffer = bytearray()
        self.peer_finished = False
        self.peer_mss = DEFAULT_PEER_MSS
        self.local_mss = stack.mss
        self.rto = INITIAL_RTO
        self.srtt = None
        self.rttvar = None
        self.rtt_sequence = None
        self.rtt_started = 0.0
        self.retries = 0
        self.retransmit_handle = None
        self.persist_handle = None
        self.advertised_window = RECEIVE_CAPACITY
        self.readable = asyncio.Event()
        self.writable = asyncio.Event()
        self.writable.set()
        self.all_acked = asyncio.Event()
        self.all_acked.set()
        self.established = self.loop.create_future()
        self.finished = self.loop.create_future()
        self.error = None
        self.listener = None

    @property
    def key(self):
        return (self.local_port, self.remote_ip, self.remote_port)

    @property
    def peer(self):
        return (ipv4.address_text(self.remote_ip), self.remote_port)

    def __repr__(self):
        return f"<TcpConnection {ipv4.address_text(self.local_ip)}:{self.local_port} <-> {ipv4.address_text(self.remote_ip)}:{self.remote_port} {self.state}>"

    def _receive_window(self):
        return max(0, min(0xFFFF, RECEIVE_CAPACITY - len(self.receive_buffer)))

    def _send_segment(self, flags, sequence=None, payload=b"", mss=None):
        window = self._receive_window()
        self.advertised_window = window
        segment = Segment(
            self.local_port, self.remote_port,
            self.snd_nxt if sequence is None else sequence,
            self.rcv_nxt if flags & ACK else 0,
            flags, window, payload, mss,
        )
        log.debug("send %s", segment.describe())
        self.stack.send_ip(ipv4.PROTOCOL_TCP, self.remote_ip, segment.build(self.local_ip, self.remote_ip))

    def _send_ack(self):
        self._send_segment(ACK)

    def open_active(self):
        self.state = SYN_SENT
        self._send_syn()

    def open_passive(self, segment):
        self.state = SYN_RECEIVED
        self.irs = segment.sequence
        self.rcv_nxt = seq_add(segment.sequence, 1)
        self.snd_wnd = segment.window
        if segment.mss:
            self.peer_mss = segment.mss
        self._send_syn()

    def _send_syn(self):
        flags = SYN | (ACK if self.state == SYN_RECEIVED else 0)
        self._send_segment(flags, sequence=self.iss, mss=self.local_mss)
        self._advance_to(seq_add(self.iss, 1))
        self._arm_retransmit()

    def _arm_retransmit(self):
        if self.retransmit_handle is None:
            self.retransmit_handle = self.loop.call_later(self.rto, self._retransmit_timeout)

    def _restart_retransmit(self):
        self._cancel_retransmit()
        self._arm_retransmit()

    def _cancel_retransmit(self):
        if self.retransmit_handle:
            self.retransmit_handle.cancel()
            self.retransmit_handle = None

    def _retransmit_timeout(self):
        self.retransmit_handle = None
        if self.state == CLOSED:
            return
        self.retries += 1
        if self.retries > MAX_RETRIES:
            self._reset("retransmission limit reached")
            return
        self.rto = min(MAX_RTO, self.rto * 2)
        self.rtt_sequence = None
        log.debug("%r retransmit #%d, rto %.1f", self, self.retries, self.rto)
        if self.state in (SYN_SENT, SYN_RECEIVED):
            self._send_syn()
            return
        self.snd_nxt = self.snd_una
        if self.fin_sent and seq_le(self.snd_una, self.fin_sequence):
            self.fin_sent = False
        self._transmit()

    def _update_rtt(self, acknowledgement):
        if self.rtt_sequence is None or seq_lt(acknowledgement, self.rtt_sequence):
            return
        sample = time.monotonic() - self.rtt_started
        self.rtt_sequence = None
        if self.srtt is None:
            self.srtt = sample
            self.rttvar = sample / 2
        else:
            self.rttvar = 0.75 * self.rttvar + 0.25 * abs(self.srtt - sample)
            self.srtt = 0.875 * self.srtt + 0.125 * sample
        self.rto = min(MAX_RTO, max(MIN_RTO, self.srtt + 4 * self.rttvar))

    def _unsent_offset(self):
        return seq_diff(self.snd_nxt, self.data_start)

    def _transmit(self):
        if self.state not in SENDING_STATES:
            return
        segment_size = max(1, min(self.peer_mss, self.stack.max_segment))
        while True:
            offset = self._unsent_offset()
            unsent = len(self.send_buffer) - offset
            usable = seq_diff(seq_add(self.snd_una, self.snd_wnd), self.snd_nxt)
            if unsent <= 0 or usable <= 0:
                break
            length = min(segment_size, unsent, usable)
            payload = bytes(self.send_buffer[offset:offset + length])
            flags = ACK | (PSH if length == unsent else 0)
            if self.rtt_sequence is None:
                self.rtt_sequence = seq_add(self.snd_nxt, length)
                self.rtt_started = time.monotonic()
            self._send_segment(flags, payload=payload)
            self._advance_to(seq_add(self.snd_nxt, length))
            self._arm_retransmit()
        offset = self._unsent_offset()
        if self.fin_queued and not self.fin_sent and offset >= len(self.send_buffer):
            self.fin_sequence = self.snd_nxt
            self._send_segment(FIN | ACK)
            self._advance_to(seq_add(self.snd_nxt, 1))
            self.fin_sent = True
            self._arm_retransmit()
        if self.snd_wnd == 0 and len(self.send_buffer) - self._unsent_offset() > 0 and self.snd_una == self.snd_nxt:
            self._arm_persist()

    def _advance_to(self, sequence):
        self.snd_nxt = sequence
        if seq_lt(self.snd_max, sequence):
            self.snd_max = sequence

    def _arm_persist(self):
        if self.persist_handle is None:
            self.persist_handle = self.loop.call_later(self.rto, self._persist_timeout)

    def _persist_timeout(self):
        self.persist_handle = None
        if self.state not in SENDING_STATES or self.snd_wnd != 0:
            return
        offset = self._unsent_offset()
        if offset < len(self.send_buffer):
            self._send_segment(ACK, payload=bytes(self.send_buffer[offset:offset + 1]))
        self._arm_persist()

    def handle(self, segment):
        log.debug("recv %s", segment.describe())
        if self.state == SYN_SENT:
            self._handle_syn_sent(segment)
            return
        if segment.flags & RST:
            if self._in_window(segment.sequence):
                self._reset("reset by peer")
            return
        if segment.flags & SYN:
            if self.state == SYN_RECEIVED and segment.sequence == self.irs:
                self._send_syn()
            else:
                self._send_ack()
            return
        if not segment.flags & ACK:
            return
        if self.state == SYN_RECEIVED:
            if seq_lt(self.snd_una, segment.acknowledgement) and seq_le(segment.acknowledgement, self.snd_max):
                self.snd_una = segment.acknowledgement
                self.snd_wnd = segment.window
                self._established()
            else:
                self._send_segment(RST, sequence=segment.acknowledgement)
                return
        self._process_ack(segment)
        if self.state == CLOSED:
            return
        self._process_payload(segment)
        self._transmit()

    def _handle_syn_sent(self, segment):
        acceptable = bool(segment.flags & ACK) and segment.acknowledgement == seq_add(self.iss, 1)
        if segment.flags & ACK and not acceptable:
            if not segment.flags & RST:
                self._send_segment(RST, sequence=segment.acknowledgement)
            return
        if segment.flags & RST:
            if acceptable:
                self._reset("connection refused")
            return
        if not segment.flags & SYN:
            return
        self.irs = segment.sequence
        self.rcv_nxt = seq_add(segment.sequence, 1)
        if segment.mss:
            self.peer_mss = segment.mss
        if acceptable:
            self.snd_una = segment.acknowledgement
            self.snd_wnd = segment.window
            self._cancel_retransmit()
            self.retries = 0
            self._send_ack()
            self._established()
            self._process_payload(segment)
            self._transmit()

    def _in_window(self, sequence):
        window = max(1, self.advertised_window)
        return seq_le(self.rcv_nxt, sequence) and seq_lt(sequence, seq_add(self.rcv_nxt, window))

    def _established(self):
        self.state = ESTABLISHED
        self.retries = 0
        self._cancel_retransmit()
        if not self.established.done():
            self.established.set_result(True)
        if self.listener:
            self.listener._deliver(self)
            self.listener = None

    def _process_ack(self, segment):
        acknowledgement = segment.acknowledgement
        if seq_lt(self.snd_max, acknowledgement):
            self._send_ack()
            return
        if seq_lt(self.snd_una, acknowledgement):
            if seq_lt(self.snd_nxt, acknowledgement):
                self.snd_nxt = acknowledgement
            self._update_rtt(acknowledgement)
            acked_data = seq_diff(acknowledgement, self.data_start)
            if acked_data > 0:
                trimmed = min(acked_data, len(self.send_buffer))
                del self.send_buffer[:trimmed]
                self.data_start = seq_add(self.data_start, trimmed)
            self.snd_una = acknowledgement
            self.retries = 0
            if self.snd_una == self.snd_max:
                self._cancel_retransmit()
            else:
                self._restart_retransmit()
            if len(self.send_buffer) < SEND_HIGH_WATER:
                self.writable.set()
            if not self.send_buffer:
                self.all_acked.set()
        if seq_le(self.snd_una, acknowledgement):
            self.snd_wnd = segment.window
            if self.snd_wnd and self.persist_handle:
                self.persist_handle.cancel()
                self.persist_handle = None
        if self.fin_sent and seq_lt(self.fin_sequence, self.snd_una):
            if self.state == FIN_WAIT_1:
                self.state = FIN_WAIT_2
            elif self.state == CLOSING:
                self._enter_time_wait()
            elif self.state == LAST_ACK:
                self._close("closed")

    def _process_payload(self, segment):
        payload = segment.payload
        sequence = segment.sequence
        has_fin = bool(segment.flags & FIN)
        if not payload and not has_fin:
            return
        if seq_lt(sequence, self.rcv_nxt):
            overlap = seq_diff(self.rcv_nxt, sequence)
            if overlap > len(payload):
                if not (has_fin and overlap == len(payload) + 1):
                    self._send_ack()
                    return
                payload = b""
                has_fin = False
            else:
                payload = payload[overlap:]
                sequence = self.rcv_nxt
        if sequence != self.rcv_nxt:
            self._send_ack()
            return
        if payload and self.state in RECEIVING_STATES:
            accepted = payload[:self._receive_window()]
            if accepted:
                self.receive_buffer += accepted
                self.rcv_nxt = seq_add(self.rcv_nxt, len(accepted))
                self.readable.set()
            if len(accepted) < len(payload):
                has_fin = False
        if has_fin and not self.peer_finished:
            self.rcv_nxt = seq_add(self.rcv_nxt, 1)
            self.peer_finished = True
            self.readable.set()
            if self.state == ESTABLISHED:
                self.state = CLOSE_WAIT
            elif self.state == FIN_WAIT_1:
                self.state = CLOSING
            elif self.state == FIN_WAIT_2:
                self._enter_time_wait()
        self._send_ack()

    def _enter_time_wait(self):
        self.state = TIME_WAIT
        self._cancel_retransmit()
        self.loop.call_later(TIME_WAIT_SECONDS, self._close, "closed")

    def _close(self, reason):
        if self.state == CLOSED and self.finished.done():
            return
        self.state = CLOSED
        self._cancel_retransmit()
        if self.persist_handle:
            self.persist_handle.cancel()
            self.persist_handle = None
        self.readable.set()
        self.writable.set()
        self.all_acked.set()
        if not self.established.done():
            self.established.set_exception(ConnectionReset(reason))
            self.established.exception()
        if not self.finished.done():
            self.finished.set_result(reason)
        self.stack._forget(self)

    def _reset(self, reason):
        log.info("%r %s", self, reason)
        self.error = ConnectionReset(reason)
        self._close(reason)

    def link_down(self):
        self._reset("link down")

    async def read(self, size=-1):
        while not self.receive_buffer:
            if self.peer_finished or self.state == CLOSED:
                if self.error and not self.peer_finished:
                    raise self.error
                return b""
            self.readable.clear()
            await self.readable.wait()
        if size < 0 or size >= len(self.receive_buffer):
            size = len(self.receive_buffer)
        data = bytes(self.receive_buffer[:size])
        window_before = self._receive_window()
        del self.receive_buffer[:size]
        if window_before < self.local_mss <= self._receive_window() and self.state in RECEIVING_STATES:
            self._send_ack()
        return data

    async def readexactly(self, size):
        chunks = bytearray()
        while len(chunks) < size:
            data = await self.read(size - len(chunks))
            if not data:
                raise asyncio.IncompleteReadError(bytes(chunks), size)
            chunks += data
        return bytes(chunks)

    def write(self, data):
        if self.error:
            raise self.error
        if self.fin_queued or self.state not in (ESTABLISHED, CLOSE_WAIT):
            raise ConnectionError(f"cannot write in state {self.state}")
        if not data:
            return
        self.send_buffer += data
        self.all_acked.clear()
        if len(self.send_buffer) >= SEND_HIGH_WATER:
            self.writable.clear()
        self._transmit()

    async def drain(self):
        await self.writable.wait()
        if self.error:
            raise self.error

    async def flush(self):
        await self.all_acked.wait()
        if self.error:
            raise self.error

    def close(self):
        if self.state in (ESTABLISHED, SYN_RECEIVED):
            self.state = FIN_WAIT_1
        elif self.state == CLOSE_WAIT:
            self.state = LAST_ACK
        elif self.state == SYN_SENT:
            self._close("closed before established")
            return
        else:
            return
        self.fin_queued = True
        self._transmit()

    def abort(self):
        if self.state not in (CLOSED, SYN_SENT, TIME_WAIT):
            self._send_segment(RST | ACK)
        self._reset("aborted locally")

    async def wait_closed(self):
        await self.finished


class TcpListener:
    def __init__(self, stack, port):
        self.stack = stack
        self.port = port
        self.queue = asyncio.Queue()
        self.closed = False

    def _deliver(self, connection):
        self.queue.put_nowait(connection)

    async def accept(self):
        connection = await self.queue.get()
        if connection is None:
            raise ConnectionError("listener closed")
        return connection

    def close(self):
        self.closed = True
        self.stack._unlisten(self)
        self.queue.put_nowait(None)
