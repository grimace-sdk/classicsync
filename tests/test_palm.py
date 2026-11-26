import asyncio
import struct
from datetime import datetime

import pytest

from classicsync.link.transport import Transport
from classicsync.palm import DlpClient, DlpError, DlpStatus, NetSyncError, NetSyncLink
from classicsync.palm.dlp import DlpCommand, decode_response, encode_request, parse_database_list
from classicsync.palm.netsync import HEADER, desktop_confirm, desktop_options
from classicsync.palm.usb import hotsync_port

M500_HELLO = bytes.fromhex("90010000000000000020000000080000010000000000")
M500_OPTIONS = bytes.fromhex("9201000000000000002000000024ffffffff003c003c40000000010000000000040000000400003c003c"
                             "0000000000000000")
M500_SYS_INFO = bytes.fromhex("92020000200e0400000000010000000400030000210c00010002000300000000ffe1")
M500_USER_INFO = bytes.fromhex("90010000201e00000000000000000000000000000003c594c594000057fe0003f35c0000")
M500_CONNECTION_INFO = bytes.fromhex("01000000636e7973020000000003f35c00030003")
M500_DATABASE_ENTRIES = bytes.fromhex(
    "36400008444154416164647200000000000107d102051037280007d001020203280000000000033ccf0000004164647265737344420038400008"
    "444154416461746500000000000207ea0b150801360007ea0b1508013a0000003c0000000000000144617465626f6f6b44420000")


def database_list_reply(entries, count, last_index, more):
    block = struct.pack(">HBB", last_index, 0x80 if more else 0, count) + entries
    return struct.pack(">BBHBBH", 0x96, 1, 0, 0xA0, 0, len(block)) + block


class FakeHandheld(Transport):
    def __init__(self, replies):
        self.replies = replies
        self.incoming = asyncio.Queue()
        self.sent = []
        self.pending = b""
        self.incoming.put_nowait(HEADER.pack(1, 0xFF, len(M500_HELLO)) + M500_HELLO)

    async def read(self):
        return await self.incoming.get()

    def write(self, data):
        self.pending += data

    async def drain(self):
        while len(self.pending) >= HEADER.size:
            _kind, xid, length = HEADER.unpack(self.pending[:HEADER.size])
            if len(self.pending) < HEADER.size + length:
                return
            payload = self.pending[HEADER.size:HEADER.size + length]
            self.pending = self.pending[HEADER.size + length:]
            self.sent.append(payload)
            reply = self.replies[payload[0]]
            reply = reply.pop(0) if isinstance(reply, list) else reply
            self.incoming.put_nowait(HEADER.pack(1, xid, len(reply)) + reply)


def m500_replies():
    return {
        0x12: [M500_OPTIONS, M500_SYS_INFO],
        0x13: bytes.fromhex("9300000000000000"),
        0x10: M500_USER_INFO,
        0x16: [database_list_reply(M500_DATABASE_ENTRIES, 2, 126, False)],
        0x2F: bytes.fromhex("af000000"),
    }


def test_handshake_matches_hotsync(run):
    async def scenario():
        handheld = FakeHandheld(m500_replies())
        hello = await NetSyncLink(handheld).accept()
        assert hello == M500_HELLO
        assert handheld.sent[0] == desktop_options()
        assert handheld.sent[0][14:22] == bytes.fromhex("ffffffff3c003c00") and len(handheld.sent[0]) == 50
        assert handheld.sent[1] == desktop_confirm(M500_OPTIONS)
        assert handheld.sent[1][14:22] == bytes.fromhex("ffffffff003c003c") and handheld.sent[1][-1] == 1
    run(scenario)


def test_reads_the_m500_session(run):
    async def scenario():
        handheld = FakeHandheld(m500_replies())
        link = NetSyncLink(handheld)
        await link.accept()
        client = DlpClient(link)
        system = await client.read_sys_info()
        assert system.os_version == "4.0" and system.dlp_version == (1, 2) and system.max_record_size == 0xFFE1
        assert handheld.sent[-1] == bytes.fromhex("12012004" "00010003")
        user = await client.read_user_info()
        assert not user.synced and user.name == "" and user.last_sync is None
        databases = await client.read_database_list()
        assert [(database.name, database.type, database.creator) for database in databases] == [
            ("AddressDB", "DATA", "addr"), ("DatebookDB", "DATA", "date")]
        assert databases[1].created == datetime(2026, 11, 21, 8, 1, 54) and databases[0].in_ram
        await client.end_of_sync()
        assert handheld.sent[-1] == bytes.fromhex("2f0120020000")
    run(scenario)


def test_database_list_follows_the_more_flag(run):
    async def scenario():
        first, second = M500_DATABASE_ENTRIES[:0x36], M500_DATABASE_ENTRIES[0x36:]
        handheld = FakeHandheld(m500_replies())
        handheld.replies[0x16] = [database_list_reply(first, 1, 0, True), database_list_reply(second, 1, 5, False)]
        link = NetSyncLink(handheld)
        await link.accept()
        databases = await DlpClient(link).read_database_list()
        assert [database.name for database in databases] == ["AddressDB", "DatebookDB"]
        requests = [payload for payload in handheld.sent if payload[0] == 0x16]
        assert [request[-2:] for request in requests] == [b"\0\0", b"\0\1"]
    run(scenario)


def test_handshake_refused_is_an_error(run):
    async def scenario():
        handheld = FakeHandheld(m500_replies())
        handheld.replies[0x12] = bytes.fromhex("9100000000000000")
        with pytest.raises(NetSyncError):
            await NetSyncLink(handheld).accept()
    run(scenario)


def test_dlp_errors_and_argument_forms():
    with pytest.raises(DlpError) as raised:
        decode_response(DlpCommand.READ_DB_LIST, bytes.fromhex("96000005"))
    assert raised.value.status == DlpStatus.NOT_FOUND
    long_data = bytes(300)
    request = encode_request(0x21, [b"\x01", long_data])
    assert request[:5] == bytes.fromhex("2102200101") and request[5:9] == bytes.fromhex("a100012c")
    entries, last_index, more = parse_database_list(decode_response(0x16, database_list_reply(M500_DATABASE_ENTRIES, 2, 126, True)))
    assert (len(entries), last_index, more) == (2, 126, True)


def test_hotsync_port_from_m500_connection_info():
    assert hotsync_port(M500_CONNECTION_INFO) == (0x82, 0x02)
    assert hotsync_port(bytes(20)) == (0x82, 0x02)
