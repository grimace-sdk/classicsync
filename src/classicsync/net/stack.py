import asyncio
import logging
import random
import struct

from . import ipv4, tcp

log = logging.getLogger("classicsync.net")

ICMP_ECHO_REPLY = 0
ICMP_DESTINATION_UNREACHABLE = 3
ICMP_ECHO_REQUEST = 8
ICMP_PORT_UNREACHABLE = 3


class NetworkStack:
    def __init__(self, link):
        self.link = link
        self.loop = None
        self.listeners = {}
        self.connections = {}
        self.udp_handlers = {}
        self.identification = random.randrange(0x10000)
        self.next_ephemeral = random.randrange(49152, 60000)
        self.ping_waiters = {}
        link.on_ip = self.receive_ip
        link.add_listener(self._link_event)

    async def start(self):
        self.loop = asyncio.get_running_loop()

    @property
    def local_ip(self):
        return ipv4.address_bytes(self.link.local_ip)

    @property
    def peer_ip(self):
        return ipv4.address_bytes(self.link.peer_ip)

    @property
    def max_segment(self):
        return max(64, self.link.peer_mru - 40)

    @property
    def mss(self):
        return 1460

    def _link_event(self, event):
        if event in ("down", "closed"):
            for connection in list(self.connections.values()):
                connection.link_down()

    def send_ip(self, protocol, destination, payload):
        self.identification = (self.identification + 1) & 0xFFFF
        packet = ipv4.Ipv4Packet(self.local_ip, destination, protocol, payload, self.identification)
        self.link.send_ip(packet.build())

    def receive_ip(self, data):
        packet = ipv4.Ipv4Packet.parse(data)
        if packet is None:
            log.debug("dropping malformed IP packet")
            return
        if packet.fragmented:
            log.info("dropping fragmented IP packet from %s", ipv4.address_text(packet.source))
            return
        if packet.destination != self.local_ip and packet.destination != b"\xff\xff\xff\xff":
            return
        if packet.protocol == ipv4.PROTOCOL_TCP:
            self._receive_tcp(packet)
        elif packet.protocol == ipv4.PROTOCOL_UDP:
            self._receive_udp(packet)
        elif packet.protocol == ipv4.PROTOCOL_ICMP:
            self._receive_icmp(packet)

    def _receive_tcp(self, packet):
        segment = tcp.Segment.parse(packet.payload, packet.source, packet.destination)
        if segment is None:
            log.debug("dropping TCP segment with bad checksum")
            return
        key = (segment.destination_port, packet.source, segment.source_port)
        connection = self.connections.get(key)
        if connection:
            connection.handle(segment)
            return
        listener = self.listeners.get(segment.destination_port)
        if listener and segment.flags & tcp.SYN and not segment.flags & (tcp.ACK | tcp.RST):
            connection = tcp.TcpConnection(self, packet.destination, segment.destination_port, packet.source, segment.source_port)
            connection.listener = listener
            self.connections[key] = connection
            log.info("accepting %r", connection)
            connection.open_passive(segment)
            return
        if not segment.flags & tcp.RST:
            self._send_reset(packet, segment)

    def _send_reset(self, packet, segment):
        if segment.flags & tcp.ACK:
            reply = tcp.Segment(segment.destination_port, segment.source_port, segment.acknowledgement, 0, tcp.RST, 0, b"")
        else:
            length = len(segment.payload) + (1 if segment.flags & tcp.SYN else 0) + (1 if segment.flags & tcp.FIN else 0)
            reply = tcp.Segment(segment.destination_port, segment.source_port, 0, tcp.seq_add(segment.sequence, length), tcp.RST | tcp.ACK, 0, b"")
        self.send_ip(ipv4.PROTOCOL_TCP, packet.source, reply.build(packet.destination, packet.source))

    def _receive_udp(self, packet):
        if len(packet.payload) < 8:
            return
        source_port, destination_port, length, _ = struct.unpack("!HHHH", packet.payload[:8])
        data = packet.payload[8:length]
        handler = self.udp_handlers.get(destination_port)
        if handler:
            handler(data, ipv4.address_text(packet.source), source_port)
        else:
            log.debug("UDP to closed port %d", destination_port)

    def _receive_icmp(self, packet):
        payload = packet.payload
        if len(payload) < 8 or ipv4.checksum(payload) != 0:
            return
        icmp_type = payload[0]
        if icmp_type == ICMP_ECHO_REQUEST:
            reply = bytes([ICMP_ECHO_REPLY, 0, 0, 0]) + payload[4:]
            value = ipv4.checksum(reply)
            self.send_ip(ipv4.PROTOCOL_ICMP, packet.source, reply[:2] + struct.pack("!H", value) + reply[4:])
        elif icmp_type == ICMP_ECHO_REPLY:
            identifier, sequence = struct.unpack("!HH", payload[4:8])
            waiter = self.ping_waiters.pop((identifier, sequence), None)
            if waiter and not waiter.done():
                waiter.set_result(self.loop.time())

    def listen(self, port):
        if port in self.listeners:
            raise OSError(f"port {port} already listening")
        listener = tcp.TcpListener(self, port)
        self.listeners[port] = listener
        return listener

    def _unlisten(self, listener):
        if self.listeners.get(listener.port) is listener:
            del self.listeners[listener.port]

    def _ephemeral_port(self):
        for _ in range(16384):
            port = self.next_ephemeral
            self.next_ephemeral = 49152 + (self.next_ephemeral - 49152 + 1) % 16384
            if not any(key[0] == port for key in self.connections) and port not in self.listeners:
                return port
        raise OSError("no free ports")

    async def connect(self, port, address=None, timeout=10.0):
        remote = ipv4.address_bytes(address) if address else self.peer_ip
        connection = tcp.TcpConnection(self, self.local_ip, self._ephemeral_port(), remote, port)
        self.connections[connection.key] = connection
        connection.open_active()
        try:
            await asyncio.wait_for(asyncio.shield(connection.established), timeout)
        except asyncio.TimeoutError:
            connection.abort()
            raise TimeoutError(f"connect to port {port} timed out")
        return connection

    def _forget(self, connection):
        if self.connections.get(connection.key) is connection:
            del self.connections[connection.key]

    def bind_udp(self, port, handler):
        self.udp_handlers[port] = handler

    def unbind_udp(self, port):
        self.udp_handlers.pop(port, None)

    def send_udp(self, source_port, destination_port, data, address=None):
        destination = ipv4.address_bytes(address) if address else self.peer_ip
        header = struct.pack("!HHHH", source_port, destination_port, 8 + len(data), 0)
        datagram = header + data
        value = ipv4.checksum(ipv4.pseudo_header(self.local_ip, destination, ipv4.PROTOCOL_UDP, len(datagram)) + datagram) or 0xFFFF
        self.send_ip(ipv4.PROTOCOL_UDP, destination, datagram[:6] + struct.pack("!H", value) + datagram[8:])

    async def ping(self, address=None, timeout=5.0, size=32):
        destination = ipv4.address_bytes(address) if address else self.peer_ip
        identifier = random.randrange(0x10000)
        sequence = random.randrange(0x10000)
        body = bytes(range(size % 256)) if size < 256 else bytes(size)
        message = struct.pack("!BBHHH", ICMP_ECHO_REQUEST, 0, 0, identifier, sequence) + body
        value = ipv4.checksum(message)
        message = message[:2] + struct.pack("!H", value) + message[4:]
        waiter = self.loop.create_future()
        self.ping_waiters[(identifier, sequence)] = waiter
        started = self.loop.time()
        self.send_ip(ipv4.PROTOCOL_ICMP, destination, message)
        try:
            finished = await asyncio.wait_for(waiter, timeout)
        finally:
            self.ping_waiters.pop((identifier, sequence), None)
        return finished - started
