import ipaddress
import struct
from dataclasses import dataclass

PROTOCOL_ICMP = 1
PROTOCOL_TCP = 6
PROTOCOL_UDP = 17

HEADER_LENGTH = 20


def checksum(data):
    if len(data) % 2:
        data = bytes(data) + b"\0"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def pseudo_header(source, destination, protocol, length):
    return source + destination + struct.pack("!BBH", 0, protocol, length)


def address_bytes(address):
    return ipaddress.IPv4Address(address).packed


def address_text(raw):
    return str(ipaddress.IPv4Address(raw))


@dataclass
class Ipv4Packet:
    source: bytes
    destination: bytes
    protocol: int
    payload: bytes
    identification: int = 0
    ttl: int = 64
    fragmented: bool = False

    @classmethod
    def parse(cls, data):
        if len(data) < HEADER_LENGTH or data[0] >> 4 != 4:
            return None
        header_length = (data[0] & 0x0F) * 4
        total_length = struct.unpack("!H", data[2:4])[0]
        if header_length < HEADER_LENGTH or total_length < header_length or total_length > len(data):
            return None
        if checksum(data[:header_length]) != 0:
            return None
        identification, flags_offset = struct.unpack("!HH", data[4:8])
        fragmented = bool(flags_offset & 0x2000) or bool(flags_offset & 0x1FFF)
        return cls(
            source=bytes(data[12:16]),
            destination=bytes(data[16:20]),
            protocol=data[9],
            payload=bytes(data[header_length:total_length]),
            identification=identification,
            ttl=data[8],
            fragmented=fragmented,
        )

    def build(self):
        total_length = HEADER_LENGTH + len(self.payload)
        header = struct.pack(
            "!BBHHHBBH4s4s",
            0x45, 0, total_length, self.identification & 0xFFFF, 0x4000,
            self.ttl, self.protocol, 0, self.source, self.destination,
        )
        header = header[:10] + struct.pack("!H", checksum(header)) + header[12:]
        return header + self.payload
