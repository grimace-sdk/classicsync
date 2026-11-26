import asyncio
import struct
from datetime import datetime

import pytest

from classicsync.link.transport import Transport
from classicsync.palm import DlpClient, DlpError, DlpStatus, NetSyncError, NetSyncLink
from classicsync.palm.dlp import DlpCommand, decode_response, encode_request, parse_database_list
from classicsync.palm.netsync import HEADER, desktop_confirm, desktop_options
from classicsync.formats.pdb import PalmDatabase, PdbRecord, PdbResource, read_pdb, write_pdb
from classicsync.palm.backup import backup_file_name, backup_handheld
from classicsync.palm.install import InstallError, install_files, load_installable
from classicsync.palm.users import set_user
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
            reply = reply(payload) if callable(reply) else reply
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


def test_pdb_round_trip():
    records = PalmDatabase("MemoDB", "DATA", "memo", attributes=0x0008, version=1, created=datetime(2001, 2, 22, 18, 24, 12),
                           modified=datetime(2026, 11, 26, 21, 0), app_info=bytes(276), records=[
                               PdbRecord(b"Shopping\0", 0x10 | 1, 0x123456), PdbRecord(b"", 0, 0x123457), PdbRecord(b"x\0", 0, 9)])
    data = write_pdb(records)
    assert len(data) == 78 + 3 * 8 + 2 + 276 + 9 + 0 + 2
    assert data[78:86] == struct.pack(">IB3s", 78 + 24 + 2 + 276, 0x11, bytes.fromhex("123456"))
    assert read_pdb(data) == records
    resources = PalmDatabase("Giraffe", "appl", "Gira", attributes=0x0001, resources=[
        PdbResource("code", 1, b"\x4e\x75"), PdbResource("tAIN", 1000, b"Giraffe\0")])
    data = write_pdb(resources)
    assert data[78:88] == struct.pack(">4sHI", b"code", 1, 78 + 20 + 2)
    assert read_pdb(data) == resources


def test_backup_file_names_follow_the_backup_conduit():
    database = PalmDatabase("Graffiti ShortCuts", "macr", "graf")
    assert backup_file_name(database) == "Graffiti_ShortCuts.PDB"
    assert backup_file_name(PalmDatabase("a/b:c", "appl", "Xxxx", attributes=1)) == "a_b_c.PRC"


def database_entry(name, kind, creator, attributes, index):
    date = struct.pack(">HBBBBBx", 2026, 11, 21, 8, 1, 54)
    fixed = struct.pack(">BBH4s4sHI8s8s8sH", 0, 0x40, attributes, kind.encode(), creator.encode(), 0, 1, date, date,
                        bytes(8), index)
    entry = fixed + name.encode() + b"\0"
    return bytes([len(entry)]) + entry[1:]


def test_backup_reads_each_database(run, tmp_path):
    memo = [(0x111111, 0x40, 1, b"First memo\0"), (0x111112, 0x10, 0, b"Private\0")]
    entries = (database_entry("MemoDB", "DATA", "memo", 0x0008, 0) + database_entry("Saved Preferences", "sprf", "psys", 0x0001, 1)
               + database_entry("Giraffe", "appl", "Gira", 0x0001, 2))

    def open_database(payload):
        name = payload[6:-1].decode()
        return bytes.fromhex("970100002001") + bytes([{"MemoDB": 1, "Giraffe": 2}[name]])

    def record_count(payload):
        return bytes.fromhex("ab0100002002") + struct.pack(">H", {1: len(memo), 2: 1}[payload[4]])

    def read_record(payload):
        index = struct.unpack(">H", payload[6:8])[0]
        record_id, attributes, category, data = memo[index]
        body = struct.pack(">IHHBB", record_id, index, len(data), attributes, category) + data
        return bytes.fromhex("a0010000") + bytes([0x20, len(body)]) + body

    def read_resource(payload):
        body = struct.pack(">4sHHH", b"code", 0, 0, 2) + b"\x4e\x75"
        return bytes.fromhex("a3010000") + bytes([0x20, len(body)]) + body

    handheld = FakeHandheld(m500_replies())
    handheld.replies.update({
        0x16: database_list_reply(entries, 3, 2, False),
        0x17: open_database,
        0x2B: record_count,
        0x1B: bytes.fromhex("9b0100002004") + b"\0\x02AB",
        0x1D: bytes.fromhex("9d000005"),
        0x20: read_record,
        0x23: read_resource,
        0x19: bytes.fromhex("99000000"),
    })

    async def scenario():
        link = NetSyncLink(handheld)
        await link.accept()
        return await backup_handheld(DlpClient(link), tmp_path)

    result = run(scenario)
    assert result.written == [("MemoDB.PDB", 2), ("Giraffe.PRC", 1)] and result.skipped == ["Saved Preferences"]
    memo_file = read_pdb((tmp_path / "MemoDB.PDB").read_bytes())
    assert memo_file.app_info == b"AB" and memo_file.sort_info == b""
    assert [(record.unique_id, record.attributes, record.data) for record in memo_file.records] == [
        (0x111111, 0x41, b"First memo\0"), (0x111112, 0x10, b"Private\0")]
    assert read_pdb((tmp_path / "Giraffe.PRC").read_bytes()).resources == [PdbResource("code", 0, b"\x4e\x75")]


def write_handheld():
    handheld = FakeHandheld(m500_replies())
    handheld.replies.update({
        0x1A: bytes.fromhex("9a000005"),
        0x18: bytes.fromhex("980100002001") + b"\x07",
        0x24: bytes.fromhex("a4000000"),
        0x1C: bytes.fromhex("9c000000"),
        0x21: lambda payload: bytes.fromhex("a10100002004") + payload[8:12],
        0x19: bytes.fromhex("99000000"),
        0x11: bytes.fromhex("91000000"),
    })
    return handheld


def test_install_writes_a_prc_like_the_install_conduit(run, tmp_path):
    game = PalmDatabase("MineHunt", "appl", "mine", attributes=0x0001, version=2,
                        resources=[PdbResource("code", 1, b"\x4e\x75"), PdbResource("tAIN", 1000, b"MineHunt\0")])
    (tmp_path / "MINEHUNT.PRC").write_bytes(write_pdb(game))
    handheld = write_handheld()

    async def scenario():
        link = NetSyncLink(handheld)
        await link.accept()
        return await install_files(DlpClient(link), [("MINEHUNT.PRC", load_installable(tmp_path / "MINEHUNT.PRC"))])

    result = run(scenario)
    assert result.installed == ["MINEHUNT.PRC"] and result.replaced == [] and not result.reset_needed
    requests = handheld.sent[2:]
    assert requests[0] == bytes.fromhex("1a01200b0000") + b"MineHunt\0"
    assert requests[1] == bytes.fromhex("18012017") + b"mineappl" + bytes.fromhex("000000010002") + b"MineHunt\0"
    assert requests[2] == bytes.fromhex("2401a000000c" "0700") + b"code" + bytes.fromhex("00010002") + b"\x4e\x75"
    assert requests[3][:6] == bytes.fromhex("2401a0000013")
    assert requests[4] == bytes.fromhex("1901220207" "80")


def test_install_writes_records_with_their_ids(run, tmp_path):
    memos = PalmDatabase("MemoDB", "DATA", "Memo", app_info=b"\0" * 276, records=[
        PdbRecord(b"Kept\0", 0x10 | 2, 0x101), PdbRecord(b"", 0x80, 0x102)])
    (tmp_path / "memo.pdb").write_bytes(write_pdb(memos))
    handheld = write_handheld()

    async def scenario():
        link = NetSyncLink(handheld)
        await link.accept()
        return await install_files(DlpClient(link), [("memo.pdb", load_installable(tmp_path / "memo.pdb"))])

    run(scenario)
    requests = handheld.sent[2:]
    assert requests[1][14:16] == bytes.fromhex("0008")
    assert requests[2][:8] == bytes.fromhex("1c01a00001180700") and requests[2][8:10] == bytes.fromhex("0114")
    assert requests[3] == bytes.fromhex("2101a000000d" "0780" "00000101" "1002") + b"Kept\0"
    assert len(requests) == 5


def test_install_rejects_bad_files(tmp_path):
    (tmp_path / "notes.txt").write_text("hello")
    with pytest.raises(InstallError):
        load_installable(tmp_path / "notes.txt")
    (tmp_path / "broken.prc").write_bytes(b"short")
    with pytest.raises(InstallError):
        load_installable(tmp_path / "broken.prc")


def test_set_user_keeps_an_existing_id_and_records_the_pc(run):
    handheld = write_handheld()

    async def scenario():
        link = NetSyncLink(handheld)
        await link.accept()
        return await set_user(DlpClient(link), "Phil", 0x1234)

    user_id = run(scenario)
    request = handheld.sent[-1]
    assert 0x100 <= user_id <= 0x7FFF
    assert request[:4] == bytes.fromhex("1101201b") and request[4:16] == struct.pack(">III", user_id, 0, 0x1234)
    assert request[24:] == bytes.fromhex("ff05") + b"Phil\0"
