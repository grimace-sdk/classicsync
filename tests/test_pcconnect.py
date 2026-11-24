import asyncio
import struct
import threading
from datetime import datetime, timezone

import pytest

from classicsync import cli
from classicsync.install import InstallError, install_file, read_cbea
from classicsync.link.pcconnect import FrameParser, PcConnectLink, WilReply, build_frame
from classicsync.link.transport import MemoryTransport
from classicsync.pcconnect import PcConnectSession, WilClient
from classicsync.pcconnect.client import format_uuid
from classicsync.rapi.client import HKEY_LOCAL_MACHINE, REG_DWORD, REG_SZ, RapiClient, RapiError
from classicsync.rapi.structures import datetime_to_filetime
from fake_pcconnect import FakePcConnectDevice

def build_cbea(members, platform="Casio Jx740 CE3.00"):
    header = bytearray(0x100)
    header[2:4] = struct.pack("<H", len(members))
    encoded_platform = platform.encode("utf-16-le")
    header[8:8 + len(encoded_platform)] = encoded_platform
    body = bytearray(header)
    for name, member_type, data in members:
        encoded_name = name.encode("latin-1")
        size = len(encoded_name) + 9 + len(data)
        body += struct.pack("<IHBB", size, 0, member_type, len(encoded_name)) + encoded_name + b"\0" + struct.pack("<I", len(data)) + data
    checksum = 0
    for value in body:
        checksum ^= value
    return bytes(body) + bytes([checksum])


INSTALL_INF = b"""[App Information]
Program="Hello Casio"
Version=1.00
InstallDir=?Drive?\\Program Files\\Hello

[Copy Files]
%INSTALL_DIR%\\Hello.exe,Hello.exe,0
"""


def sample_package():
    return build_cbea([("Install.inf", 1, INSTALL_INF), ("Hello.exe", 2, b"MZ" + bytes(300))])


async def connected_session(configure=None, keepalive_seconds=None):
    desktop_transport, device_transport = MemoryTransport.pair()
    device = FakePcConnectDevice(device_transport)
    if configure:
        configure(device)
    device.start()
    session = PcConnectSession(desktop_transport, handshake_attempts=8, retry_seconds=0.05, keepalive_seconds=keepalive_seconds)
    await session.start()
    await session.wait_for_device(5)
    return session, device


def test_frames_match_captures_from_hardware():
    assert build_frame(0x0301) == bytes.fromhex("1000000a03010000001e")
    assert build_frame(0x0346) == bytes.fromhex("1000000a034600000063")
    parser = FrameParser()
    capture = bytes.fromhex("55 20 11 00 00 12 03 01 00 00 00 1e 00 01 00 00 00 00 00 57"
                            "11 00 00 22 03 46 00 00 00 63 00 00 00 01 00 00 00 57"
                            "00 37 85 01 e4 02 01 10 80 00 74 51 3f bf 50 00")
    frames = parser.feed(capture[:7]) + parser.feed(capture[7:])
    version, uuid = (WilReply.from_frame(frame) for frame in frames)
    assert (version.command, version.value, version.error) == (0x0301, 0x00010000, 0x57)
    assert (uuid.value, uuid.error) == (1, 0x57)
    assert format_uuid(uuid.data) == "00378501-e402-0110-8000-74513fbf5000"


def test_parser_reassembles_large_replies():
    parser = FrameParser()
    full = bytes([0x11, 0x05, 0, 0, 0x03, 0x0F, 0, 0, 0, 0]) + bytes(range(200))
    announcement = bytes([0x11, 0x05]) + struct.pack(">HH", 14, 0x0401) + bytes(4) + struct.pack(">I", len(full))
    frames = parser.feed(announcement + full[:50]) + parser.feed(full[50:])
    assert len(frames) == 1
    assert frames[0].command == 0x030F
    assert frames[0].payload == bytes(range(200))


def test_session_reads_device_identity(run):
    async def scenario():
        session, device = await connected_session()
        try:
            identity = session.device
            assert identity.uuid == format_uuid(device.uuid)
            assert identity.platform_name == "Casio Jx740 CE3.00"
            assert identity.platform_release == "002202"
            assert identity.server_version_text == "1.00"
            assert device.commands[0] == 0x0301
            assert "Casio Jx740 CE3.00" in cli.describe_device(identity)
        finally:
            await session.close()

    run(scenario)


def test_rapi_bridge_files(run):
    async def scenario():
        session, device = await connected_session()
        device.put_file("\\Nand Disk\\notes.txt", b"hello")
        client = await session.open_rapi()
        try:
            version = await client.get_version()
            assert (version.major, version.minor, version.platform) == (3, 0, 3)
            assert (await client.get_system_info()).processor_type == 4000
            store = await client.get_store_information()
            assert (store.store_size, store.free_size) == (12566528, 8000000)
            listing = {entry.name: entry for entry in await client.find_all_files("\\Nand Disk\\*.*")}
            assert listing["notes.txt"].size == 5 and not listing["notes.txt"].is_directory

            payload = bytes(index % 251 for index in range(5000))
            modified = datetime_to_filetime(datetime(2001, 6, 1, 12, 0))
            await client.write_file_contents("\\Nand Disk\\big.bin", payload, modified=modified)
            assert device.file_data("\\Nand Disk\\big.bin") == payload
            assert device.files["\\nand disk\\big.bin"].times[2] == modified
            assert device.files["\\nand disk\\big.bin"].times[0] == 131000000000000000
            assert await client.read_file_contents("\\Nand Disk\\big.bin") == payload

            await client.create_directory("\\Nand Disk\\Letters")
            assert await client.get_file_attributes("\\Nand Disk\\Letters") & 0x10
            await client.move_file("\\Nand Disk\\notes.txt", "\\Nand Disk\\Letters\\notes.txt")
            await client.copy_file("\\Nand Disk\\Letters\\notes.txt", "\\Nand Disk\\copy.txt")
            await client.delete_file("\\Nand Disk\\copy.txt")
            with pytest.raises(RapiError):
                await client.remove_directory("\\Nand Disk\\Letters")
            with pytest.raises(RapiError):
                await client.create_file("\\Nand Disk\\missing.txt")
            assert sorted(device.files) == ["\\nand disk\\big.bin", "\\nand disk\\letters\\notes.txt"]
        finally:
            client.close()
            await session.close()

    run(scenario)


def test_rapi_bridge_registry_processes_and_time(run):
    async def scenario():
        session, device = await connected_session()
        client = await session.open_rapi()
        try:
            key, disposition = await client.reg_create_key(HKEY_LOCAL_MACHINE, "Software\\Example")
            assert disposition == 1
            await client.reg_set_value(key, "Count", REG_DWORD, 7)
            await client.reg_set_value(key, "Label", REG_SZ, "BE-300")
            assert await client.reg_query_value(key, "Count") == (REG_DWORD, 7)
            assert await client.reg_query_value(key, "Label") == (REG_SZ, "BE-300")
            assert await client.reg_enum_value(key, 1) == ("Label", REG_SZ, "BE-300")
            assert await client.reg_enum_value(key, 2) is None
            await client.reg_delete_value(key, "Count")
            with pytest.raises(RapiError):
                await client.reg_query_value(key, "Count")
            await client.reg_close_key(key)
            software = await client.reg_open_key(HKEY_LOCAL_MACHINE, "Software")
            assert await client.reg_enum_key(software, 0) == "Example"
            assert await client.reg_enum_key(software, 1) is None
            await client.reg_close_key(software)
            with pytest.raises(RapiError):
                await client.reg_open_key(HKEY_LOCAL_MACHINE, "Nowhere")

            information = await client.create_process("\\Windows\\calc.exe", "/x")
            assert information.process_id == 0x300
            assert device.processes == [("\\Windows\\calc.exe", "/x")]

            moment = datetime(2026, 11, 24, 10, 30, 15, tzinfo=timezone.utc)
            await client.sync_time_to_pc(datetime_to_filetime(moment), 0)
            assert device.system_time == (2026, 11, 2, 24, 10, 30, 15, 0)

            with pytest.raises(RapiError):
                await client.get_memory_status()
        finally:
            client.close()
            await session.close()

    run(scenario)


def test_keepalives_busy_and_resend(run):
    async def scenario():
        def configure(device):
            device.keepalive_before_reply = True
            device.busy_before_reply = 2
            device.large_reply_limit = 64

        session, device = await connected_session(configure, keepalive_seconds=0)
        try:
            for index in range(5):
                device.put_file(f"\\Nand Disk\\file{index}.txt", b"x" * index)
            device.resend_once.add(0x0313)
            replies_before = len(device.commands)
            reply, entries = await session.wil.find_all_files("\\Nand Disk\\*")
            assert [entry.name for entry in entries] == [f"file{index}.txt" for index in range(5)]
            attributes = await session.wil.get_file_attributes("\\Nand Disk\\file1.txt")
            assert attributes.value == 0x20
            assert device.commands[replies_before:].count(0x0313) == 2
            await asyncio.sleep(0.05)
            assert device.host_keepalives == len(device.commands) - 1
            assert device.bad_frames == 0
        finally:
            await session.close()

    run(scenario)


def test_nand_reads_reach_below_the_user_volume(run):
    async def scenario():
        session, device = await connected_session()
        try:
            handle = await session.wil.nand_open()
            geometry = await session.wil.nand_get_info(handle)
            assert (geometry.sectors, geometry.sector_size) == (24544, 512)
            data = await session.wil.nand_read_sectors(handle, 0, 2)
            assert data[:4] == bytes(4) and data[512:516] == struct.pack(">I", 1)
            await session.wil.nand_close(handle)
        finally:
            await session.close()

    run(scenario)


def test_session_notices_disconnect(run):
    async def scenario():
        session, device = await connected_session()
        try:
            session.device_changed.clear()
            await device.transport.close()
            await asyncio.wait_for(session.device_changed.wait(), 5)
            assert session.device is None
        finally:
            await session.close()

    run(scenario)


def test_failed_handshake_resets_usb_device(run):
    class SilentTransport(MemoryTransport):
        resets = 0

        async def reset_device(self):
            SilentTransport.resets += 1

    async def scenario():
        transport = SilentTransport()
        session = PcConnectSession(transport, handshake_attempts=2, reset_settle_seconds=0, retry_seconds=0.01)
        await session.start()
        with pytest.raises(TimeoutError, match="handshake"):
            await session.wait_for_device(1.5)
        await session.close()
        assert SilentTransport.resets >= 1

    run(scenario)


def test_rapi_proxy_serves_the_bridge(run):
    async def scenario():
        session, device = await connected_session()
        device.put_file("\\Nand Disk\\a.txt", b"abc")
        server = await session.serve_rapi_proxy("127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            client = await RapiClient.open_tcp("127.0.0.1", port)
            assert [entry.name for entry in await client.find_all_files("\\Nand Disk\\*.*")] == ["a.txt"]
            assert await client.read_file_contents("\\Nand Disk\\a.txt") == b"abc"
            client.close()
        finally:
            server.close()
            await session.close()

    run(scenario)


def test_cbea_reader(tmp_path):
    path = tmp_path / "Hello.cbea"
    path.write_bytes(sample_package())
    package = read_cbea(path)
    assert package.platform == "Casio Jx740 CE3.00"
    assert [member.name for member in package.members] == ["Install.inf", "Hello.exe"]
    assert (package.program, package.version, package.install_directory) == ("Hello Casio", "1.00", "?Drive?\\Program Files\\Hello")
    damaged = bytearray(sample_package())
    damaged[0x120] ^= 1
    with pytest.raises(InstallError, match="checksum"):
        read_cbea(bytes(damaged))
    miscounted = bytearray(sample_package())
    miscounted[2] = 1
    with pytest.raises(InstallError, match="lists 1 files but the package holds 2"):
        read_cbea(bytes(miscounted))
    with pytest.raises(InstallError, match="not a Casio"):
        read_cbea(b"MSCF" + bytes(400))


def test_cbea_install_stages_package_and_runs_coinstall(run, tmp_path):
    path = tmp_path / "Hello.cbea"
    path.write_bytes(sample_package())

    async def scenario():
        session, device = await connected_session()
        client = await session.open_rapi()
        try:
            progress = []
            outcomes = await install_file(client, path, progress=lambda written, total: progress.append((written, total)))
            assert outcomes[0].succeeded
            assert device.file_data("\\Temp\\install.cbea") == path.read_bytes()
            assert device.processes == [("CoInstall.exe", "_M \\Temp\\install.cbea")]
            assert progress[-1] == (len(path.read_bytes()), len(path.read_bytes()))
        finally:
            client.close()
            await session.close()

    run(scenario)


class StreamTransport:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer

    async def read(self):
        return await self.reader.read(4096)

    def write(self, data):
        if not self.writer.is_closing():
            self.writer.write(data)

    async def close(self):
        self.writer.close()


class ThreadedFakeDevice:
    def __init__(self):
        self.device = FakePcConnectDevice(None)
        self.ready = threading.Event()
        self.port = None
        self.loop = None
        self.stopped = None
        self.thread = threading.Thread(target=lambda: asyncio.run(self.serve()), daemon=True)

    async def serve(self):
        self.loop = asyncio.get_running_loop()
        self.stopped = asyncio.Event()
        server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        self.port = server.sockets[0].getsockname()[1]
        self.ready.set()
        await self.stopped.wait()
        server.close()

    async def handle(self, reader, writer):
        self.device.transport = StreamTransport(reader, writer)
        self.device.buffer.clear()
        self.device.connected = False
        self.device.handshakes = 0
        await self.device.run()

    def __enter__(self):
        self.thread.start()
        self.ready.wait(5)
        return self

    def __exit__(self, *exception):
        self.loop.call_soon_threadsafe(self.stopped.set)
        self.thread.join(5)


def test_cli_commands_over_pc_connect(tmp_path, capsys):
    package = tmp_path / "Hello.cbea"
    package.write_bytes(sample_package())
    local = tmp_path / "local.txt"
    local.write_bytes(b"from the desktop")
    with ThreadedFakeDevice() as fake:
        port = ["--port", f"tcp:127.0.0.1:{fake.port}", "--pc-connect", "--timeout", "10"]
        assert cli.main(["info", *port]) == 0
        output = capsys.readouterr()
        assert "Windows CE 3.00" in output.out and "MIPS R4000" in output.out
        assert "Casio Jx740 CE3.00" in output.err
        assert cli.main(["put", str(local), "\\Nand Disk\\local.txt", *port]) == 0
        assert fake.device.file_data("\\Nand Disk\\local.txt") == b"from the desktop"
        assert cli.main(["ls", "\\Nand Disk", *port]) == 0
        assert "local.txt" in capsys.readouterr().out
        assert cli.main(["get", "\\Nand Disk\\local.txt", str(tmp_path / "back.txt"), *port]) == 0
        assert (tmp_path / "back.txt").read_bytes() == b"from the desktop"
        assert cli.main(["install", str(package), *port]) == 0
        assert "CoInstall.exe" in capsys.readouterr().out
        assert fake.device.processes[-1] == ("CoInstall.exe", "_M \\Temp\\install.cbea")
        dump = tmp_path / "nand.bin"
        assert cli.main(["nand-dump", str(dump), *port]) == 0
        assert dump.stat().st_size == 32768 * 512
        assert dump.read_bytes()[7584 * 512:7584 * 512 + 4] == struct.pack(">I", 7584)


def test_link_refuses_calls_when_closed(run):
    async def scenario():
        desktop_transport, device_transport = MemoryTransport.pair()
        link = PcConnectLink(desktop_transport)
        with pytest.raises(ConnectionError):
            await WilClient(link).version()

    run(scenario)
