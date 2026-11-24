import asyncio
import ipaddress
import logging
import os
import struct

from ..i18n import _
from . import hdlc

log = logging.getLogger("classicsync.ppp")

PROTOCOL_IP = 0x0021
PROTOCOL_LCP = 0xC021
PROTOCOL_IPCP = 0x8021

CONFIGURE_REQUEST = 1
CONFIGURE_ACK = 2
CONFIGURE_NAK = 3
CONFIGURE_REJECT = 4
TERMINATE_REQUEST = 5
TERMINATE_ACK = 6
CODE_REJECT = 7
PROTOCOL_REJECT = 8
ECHO_REQUEST = 9
ECHO_REPLY = 10
DISCARD_REQUEST = 11

LCP_MRU = 1
LCP_ACCM = 2
LCP_MAGIC = 5
LCP_PFC = 7
LCP_ACFC = 8

IPCP_ADDRESS = 3
IPCP_PRIMARY_DNS = 129

HANDSHAKE_REQUEST = b"CLIENT"
HANDSHAKE_REPLY = b"CLIENTSERVER"

ROLE_DESKTOP = "desktop"
ROLE_DEVICE = "device"

RESTART_SECONDS = 3.0
MAX_CONFIGURE = 10
DEFAULT_MRU = 1500


def parse_options(data):
    options = []
    position = 0
    while position + 2 <= len(data):
        option_type = data[position]
        option_length = data[position + 1]
        if option_length < 2 or position + option_length > len(data):
            break
        options.append((option_type, bytes(data[position + 2:position + option_length])))
        position += option_length
    return options


def build_options(options):
    return b"".join(bytes([option_type, len(value) + 2]) + value for option_type, value in options)


def ip_bytes(address):
    return ipaddress.IPv4Address(address).packed


class ControlProtocol:
    def __init__(self, link, protocol, name):
        self.link = link
        self.protocol = protocol
        self.name = name
        self.reset()

    def reset(self):
        self.request_id = None
        self.request_options = self.initial_options()
        self.peer_acked = False
        self.we_acked = False
        self.opened = False
        self.configure_count = 0
        self.restart_handle = None

    def cancel_restart(self):
        if self.restart_handle:
            self.restart_handle.cancel()
            self.restart_handle = None

    def initial_options(self):
        return []

    def send_request(self):
        self.cancel_restart()
        self.configure_count += 1
        if self.configure_count > MAX_CONFIGURE:
            log.warning("%s: peer never acknowledged our configuration", self.name)
            self.link.fail(f"{self.name} negotiation failed")
            return
        self.request_id = self.link.next_identifier()
        self.link.send_control(self.protocol, CONFIGURE_REQUEST, self.request_id, build_options(self.request_options))
        self.restart_handle = self.link.loop.call_later(RESTART_SECONDS, self.restart_timeout)

    def restart_timeout(self):
        self.restart_handle = None
        if not self.peer_acked and not self.link.closed:
            self.send_request()

    def judge_option(self, option_type, value):
        return "reject", None

    def apply_peer_options(self, options):
        pass

    def adopt_nak(self, options):
        pass

    def on_opened(self):
        pass

    def on_peer_request(self, identifier, data):
        if self.opened:
            log.info("%s: peer restarted negotiation", self.name)
            self.on_restart()
        options = parse_options(data)
        rejected = []
        naked = []
        for option_type, value in options:
            verdict, suggestion = self.judge_option(option_type, value)
            if verdict == "reject":
                rejected.append((option_type, value))
            elif verdict == "nak":
                naked.append((option_type, suggestion))
        if rejected:
            self.link.send_control(self.protocol, CONFIGURE_REJECT, identifier, build_options(rejected))
        elif naked:
            self.link.send_control(self.protocol, CONFIGURE_NAK, identifier, build_options(naked))
        else:
            self.link.send_control(self.protocol, CONFIGURE_ACK, identifier, data)
            self.apply_peer_options(options)
            self.we_acked = True
        if self.request_id is None:
            self.send_request()
        self.check_open()

    def on_restart(self):
        self.opened = False
        self.peer_acked = False
        self.we_acked = False
        self.configure_count = 0
        self.request_id = None
        self.request_options = self.initial_options()

    def on_ack(self, identifier, data):
        if identifier != self.request_id:
            return
        self.cancel_restart()
        self.peer_acked = True
        self.check_open()

    def on_nak_or_reject(self, code, identifier, data):
        if identifier != self.request_id:
            return
        options = parse_options(data)
        if code == CONFIGURE_REJECT:
            rejected_types = {option_type for option_type, _ in options}
            self.request_options = [option for option in self.request_options if option[0] not in rejected_types]
        else:
            self.adopt_nak(options)
        self.send_request()

    def check_open(self):
        if self.opened or not (self.peer_acked and self.we_acked):
            return
        self.opened = True
        self.cancel_restart()
        log.info("%s: opened", self.name)
        self.on_opened()

    def handle(self, code, identifier, data):
        if code == CONFIGURE_REQUEST:
            self.on_peer_request(identifier, data)
        elif code == CONFIGURE_ACK:
            self.on_ack(identifier, data)
        elif code in (CONFIGURE_NAK, CONFIGURE_REJECT):
            self.on_nak_or_reject(code, identifier, data)
        elif code == TERMINATE_REQUEST:
            self.link.send_control(self.protocol, TERMINATE_ACK, identifier, data)
            log.info("%s: terminated by peer", self.name)
            self.on_terminated()
        elif code == TERMINATE_ACK:
            self.on_terminated()
        else:
            self.handle_other(code, identifier, data)

    def on_terminated(self):
        self.cancel_restart()
        self.opened = False

    def handle_other(self, code, identifier, data):
        self.link.send_control(self.protocol, CODE_REJECT, self.link.next_identifier(), bytes([code, identifier]) + struct.pack(">H", len(data) + 4) + data)


class LinkControl(ControlProtocol):
    def __init__(self, link):
        self.magic = int.from_bytes(os.urandom(4), "big") or 1
        super().__init__(link, PROTOCOL_LCP, "LCP")

    def initial_options(self):
        if self.link.role == ROLE_DESKTOP:
            return []
        return [
            (LCP_MRU, struct.pack(">H", DEFAULT_MRU)),
            (LCP_ACCM, struct.pack(">I", 0)),
            (LCP_MAGIC, struct.pack(">I", self.magic)),
            (LCP_PFC, b""),
            (LCP_ACFC, b""),
        ]

    def judge_option(self, option_type, value):
        if option_type == LCP_MRU and len(value) == 2:
            return "accept", None
        if option_type == LCP_ACCM and len(value) == 4:
            return "accept", None
        if option_type == LCP_MAGIC and len(value) == 4:
            if value == b"\0\0\0\0":
                return "reject", None
            if int.from_bytes(value, "big") == self.magic:
                return "nak", struct.pack(">I", int.from_bytes(os.urandom(4), "big") or 2)
            return "accept", None
        if option_type in (LCP_PFC, LCP_ACFC) and not value:
            return "accept", None
        return "reject", None

    def apply_peer_options(self, options):
        self.link.peer_accm = hdlc.DEFAULT_ACCM
        self.link.peer_mru = DEFAULT_MRU
        for option_type, value in options:
            if option_type == LCP_ACCM:
                self.link.peer_accm = int.from_bytes(value, "big")
            elif option_type == LCP_MRU:
                self.link.peer_mru = int.from_bytes(value, "big")

    def on_opened(self):
        self.link.tx_accm = self.link.peer_accm
        self.link.ipcp.reset()
        if self.link.role == ROLE_DEVICE:
            self.link.ipcp.send_request()

    def on_restart(self):
        super().on_restart()
        self.link.tx_accm = hdlc.DEFAULT_ACCM
        self.link.ipcp.cancel_restart()
        self.link.ipcp.reset()
        self.link.set_down()

    def on_terminated(self):
        super().on_terminated()
        self.link.ipcp.cancel_restart()
        if self.link.role == ROLE_DESKTOP:
            self.link.handshaken = False
            self.link._renegotiate()
        else:
            self.link.close_soon(_("terminated by peer"))

    def handle_other(self, code, identifier, data):
        if code == ECHO_REQUEST:
            if self.opened:
                self.link.send_control(PROTOCOL_LCP, ECHO_REPLY, identifier, struct.pack(">I", self.magic) + data[4:])
        elif code in (ECHO_REPLY, DISCARD_REQUEST, CODE_REJECT):
            pass
        elif code == PROTOCOL_REJECT:
            rejected = struct.unpack(">H", data[:2])[0] if len(data) >= 2 else 0
            log.info("LCP: peer rejected protocol 0x%04x", rejected)
        else:
            super().handle_other(code, identifier, data)


class InternetControl(ControlProtocol):
    def __init__(self, link):
        super().__init__(link, PROTOCOL_IPCP, "IPCP")

    def initial_options(self):
        if self.link.role == ROLE_DESKTOP:
            return [(IPCP_ADDRESS, ip_bytes(self.link.local_ip))]
        return [(IPCP_ADDRESS, ip_bytes(self.link.local_ip or "0.0.0.0"))]

    def judge_option(self, option_type, value):
        if self.link.role == ROLE_DESKTOP:
            if option_type == IPCP_ADDRESS and len(value) == 4:
                wanted = ip_bytes(self.link.peer_ip)
                return ("accept", None) if value == wanted else ("nak", wanted)
            if option_type == IPCP_PRIMARY_DNS and len(value) == 4 and self.link.dns_ip:
                wanted = ip_bytes(self.link.dns_ip)
                return ("accept", None) if value == wanted else ("nak", wanted)
            return "reject", None
        if option_type == IPCP_ADDRESS and len(value) == 4 and value != b"\0\0\0\0":
            return "accept", None
        return "reject", None

    def apply_peer_options(self, options):
        if self.link.role == ROLE_DEVICE:
            for option_type, value in options:
                if option_type == IPCP_ADDRESS:
                    self.link.peer_ip = str(ipaddress.IPv4Address(value))

    def adopt_nak(self, options):
        if self.link.role != ROLE_DEVICE:
            return
        suggestions = dict(options)
        updated = []
        for option_type, value in self.request_options:
            if option_type in suggestions:
                value = suggestions[option_type]
                if option_type == IPCP_ADDRESS:
                    self.link.local_ip = str(ipaddress.IPv4Address(value))
            updated.append((option_type, value))
        self.request_options = updated

    def on_opened(self):
        self.link.set_up()

    def on_restart(self):
        super().on_restart()
        self.link.set_down()

    def on_terminated(self):
        super().on_terminated()
        self.link.set_down()


class PppLink:
    def __init__(self, transport, role=ROLE_DESKTOP, local_ip=None, peer_ip=None, dns_ip=None, on_ip=None):
        self.transport = transport
        self.role = role
        self.local_ip = local_ip
        self.peer_ip = peer_ip
        self.dns_ip = dns_ip
        self.on_ip = on_ip
        self.decoder = hdlc.FrameDecoder()
        self.tx_accm = hdlc.DEFAULT_ACCM
        self.peer_accm = hdlc.DEFAULT_ACCM
        self.peer_mru = DEFAULT_MRU
        self.identifier = 0
        self.handshaken = False
        self.text = bytearray()
        self.loop = None
        self.lcp = None
        self.ipcp = None
        self.up = None
        self.finished = None
        self.closed = False
        self.close_reason = None
        self.reader_task = None
        self.handshake_task = None
        self.listeners = []

    def add_listener(self, callback):
        self.listeners.append(callback)

    def _notify(self, event):
        for callback in list(self.listeners):
            callback(event)

    async def start(self):
        self.loop = asyncio.get_running_loop()
        self.up = asyncio.Event()
        self.finished = self.loop.create_future()
        self.lcp = LinkControl(self)
        self.ipcp = InternetControl(self)
        self.reader_task = asyncio.create_task(self._read_loop())
        if self.role == ROLE_DEVICE:
            self.handshake_task = asyncio.create_task(self._dial())

    async def _dial(self):
        while not self.handshaken and not self.closed:
            self.transport.write(HANDSHAKE_REQUEST)
            await asyncio.sleep(1.0)

    async def wait_up(self, timeout=None):
        waiter = asyncio.create_task(self.up.wait())
        done, pending = await asyncio.wait({waiter, self.finished}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        if waiter not in done:
            waiter.cancel()
            if self.finished in done:
                raise ConnectionError(_("link closed: {reason}").format(reason=self.close_reason))
            raise TimeoutError(_("link did not come up"))

    def next_identifier(self):
        self.identifier = (self.identifier + 1) & 0xFF
        return self.identifier

    async def _read_loop(self):
        try:
            while not self.closed:
                data = await self.transport.read()
                if not data:
                    self.close_soon(_("transport closed"))
                    return
                self.receive(data)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log.exception("link read failed")
            self.close_soon(_("read failed: {error}").format(error=error))

    def receive(self, data):
        frames, text = self.decoder.feed(data)
        if text:
            self._handle_text(text)
        for frame in frames:
            self._handle_frame(frame)

    def _handle_text(self, text):
        self.text += text
        del self.text[:-64]
        if self.role == ROLE_DESKTOP:
            if HANDSHAKE_REQUEST in self.text and not self.text.endswith(HANDSHAKE_REPLY):
                log.info("direct connection handshake")
                self.text.clear()
                if self.lcp.opened:
                    self._renegotiate()
                self.handshaken = True
                self.transport.write(HANDSHAKE_REPLY)
                self._notify("handshake")
        elif HANDSHAKE_REPLY in self.text and not self.handshaken:
            self.text.clear()
            self.handshaken = True
            log.info("desktop answered handshake")
            self._notify("handshake")
            self.lcp.send_request()

    def _renegotiate(self):
        self.lcp.cancel_restart()
        self.ipcp.cancel_restart()
        self.lcp.reset()
        self.ipcp.reset()
        self.tx_accm = hdlc.DEFAULT_ACCM
        self.set_down()

    def _handle_frame(self, frame):
        if len(frame) >= 2 and frame[0] == 0xFF and frame[1] == 0x03:
            frame = frame[2:]
        if not frame:
            return
        if frame[0] & 1:
            protocol = frame[0]
            payload = frame[1:]
        elif len(frame) >= 2:
            protocol = (frame[0] << 8) | frame[1]
            payload = frame[2:]
        else:
            return
        if protocol in (PROTOCOL_LCP, PROTOCOL_IPCP):
            self._handle_control(protocol, payload)
        elif protocol == PROTOCOL_IP:
            if self.ipcp.opened and self.on_ip:
                self.on_ip(payload)
        elif self.lcp.opened:
            log.info("rejecting protocol 0x%04x", protocol)
            self.send_control(PROTOCOL_LCP, PROTOCOL_REJECT, self.next_identifier(), struct.pack(">H", protocol) + payload[:self.peer_mru - 6])

    def _handle_control(self, protocol, payload):
        if len(payload) < 4:
            return
        code, identifier, length = struct.unpack(">BBH", payload[:4])
        if length < 4 or length > len(payload):
            length = len(payload)
        data = payload[4:length]
        if protocol == PROTOCOL_LCP:
            if not self.handshaken and code == CONFIGURE_REQUEST:
                self.handshaken = True
            self.lcp.handle(code, identifier, data)
        elif self.lcp.opened:
            self.ipcp.handle(code, identifier, data)

    def send_frame(self, protocol, payload):
        if self.closed:
            return
        header = bytes([0xFF, 0x03]) + struct.pack(">H", protocol)
        accm = self.tx_accm if protocol != PROTOCOL_LCP else hdlc.DEFAULT_ACCM
        self.transport.write(hdlc.encode_frame(header + payload, accm))

    def send_control(self, protocol, code, identifier, data):
        self.send_frame(protocol, struct.pack(">BBH", code, identifier, len(data) + 4) + data)

    def send_ip(self, packet):
        if self.ipcp and self.ipcp.opened:
            self.send_frame(PROTOCOL_IP, packet)

    @property
    def is_up(self):
        return bool(self.up and self.up.is_set())

    def set_up(self):
        if not self.up.is_set():
            log.info("link up: local %s, peer %s", self.local_ip, self.peer_ip)
            self.up.set()
            self._notify("up")

    def set_down(self):
        if self.up and self.up.is_set():
            self.up.clear()
            log.info("link down")
            self._notify("down")

    def fail(self, reason):
        self.close_soon(reason)

    def close_soon(self, reason):
        if self.closed:
            return
        self.closed = True
        self.close_reason = reason
        log.info("link closed: %s", reason)
        for control in (self.lcp, self.ipcp):
            if control:
                control.cancel_restart()
        self.set_down()
        self._notify("closed")
        if self.finished and not self.finished.done():
            self.finished.set_result(reason)

    async def wait_closed(self):
        if self.reader_task:
            try:
                await self.reader_task
            except asyncio.CancelledError:
                pass

    async def close(self, terminate=True):
        if terminate and self.lcp and self.lcp.opened and not self.closed:
            self.send_control(PROTOCOL_LCP, TERMINATE_REQUEST, self.next_identifier(), b"")
            try:
                await self.transport.drain()
            except Exception:
                pass
        self.close_soon(_("closed locally"))
        for task in (self.reader_task, self.handshake_task):
            if task and task is not asyncio.current_task():
                task.cancel()
        await self.transport.close()
