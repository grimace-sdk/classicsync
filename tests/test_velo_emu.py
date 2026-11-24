import asyncio
import os
import socket
import subprocess
from pathlib import Path

import pytest

from cab_builders import build_ce_cab
from classicsync.connection.desktop import Desktop
from classicsync.install import install_cab, install_file, list_installed_apps, read_cab_package, uninstall_app
from classicsync.link.transport import TcpSerialTransport
from classicsync.rapi.client import HKEY_CLASSES_ROOT, HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE

VELO_EMU = os.environ.get("VELO_EMU")

pytestmark = [
    pytest.mark.device,
    pytest.mark.skipif(not VELO_EMU, reason="set VELO_EMU to a velo-emu checkout to run against emulated devices"),
]

CE1_SETUP_TAPS = [
    "--key=8:4B", "--key=10:4B", "--tap=12:240:120", "--tap=14:96:48", "--tap=16:96:192", "--tap=18:384:192",
    "--tap=20:384:48", "--key=23:4B", "--tap=26:452:227", "--tap=29:452:227", "--tap=32:452:227", "--tap=35:452:227",
    "--tap=38:452:227", "--tap=41:452:227",
]

DEVICES = {
    "ce1": ("rom/nk.bin", None),
    "ce2": ("rom/nk-ce2-merged-patchsets-115k.bin", "ce2-merged-115k-desktop-16mb.state"),
}


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def ce1_state(tmp_path_factory):
    state = tmp_path_factory.mktemp("velo") / "ce1-desktop.state"
    subprocess.run(["./headless", "rom/nk.bin", "--seconds=44", f"--save={state}", *CE1_SETUP_TAPS],
                   cwd=VELO_EMU, check=True, capture_output=True)
    return state


@pytest.fixture(params=sorted(DEVICES))
def emulated_device(request, ce1_state):
    rom, state = DEVICES[request.param]
    state_path = ce1_state if state is None else Path(VELO_EMU) / state
    port = free_port()
    process = subprocess.Popen(
        ["./headless", rom, f"--load={state_path}", "--seconds=100000", "--realtime=1", f"--tcp={port}"],
        cwd=VELO_EMU, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    yield request.param, port
    process.terminate()
    process.wait(10)


def test_session(emulated_device):
    name, port = emulated_device

    async def scenario():
        await asyncio.sleep(0.5)
        desktop = Desktop(TcpSerialTransport("127.0.0.1", port))
        await desktop.start()
        try:
            announcement = await desktop.wait_for_device(60)
            if name == "ce1":
                assert announcement.legacy
            else:
                assert announcement.info.os_major == 2
                assert announcement.info.platform == "HPC"
            client = await desktop.open_rapi()
            version = await client.get_version()
            assert version.major == (1 if name == "ce1" else 2)
            assert {entry.name for entry in await client.find_all_files("\\*.*")} >= {"My Documents", "Windows"}
            blob = os.urandom(12345)
            await client.write_file_contents("\\My Documents\\classicsync.bin", blob)
            assert await client.read_file_contents("\\My Documents\\classicsync.bin") == blob
            await client.delete_file("\\My Documents\\classicsync.bin")
            key = await client.reg_open_key(HKEY_CURRENT_USER, "ControlPanel\\Comm")
            _, connection_name = await client.reg_query_value(key, "Cnct")
            await client.reg_close_key(key)
            assert "@" in connection_name
            databases = await client.find_all_databases()
            assert any(entry.get("name") == "Contacts Database" for entry in databases)
            client.close()
        finally:
            await desktop.close()

    asyncio.run(asyncio.wait_for(scenario(), 180))


async def connected_client(port):
    await asyncio.sleep(0.5)
    desktop = Desktop(TcpSerialTransport("127.0.0.1", port))
    await desktop.start()
    await desktop.wait_for_device(60)
    return desktop, await desktop.open_rapi()


async def registry_values(client, root, subkey):
    key = await client.reg_open_key(root, subkey)
    values = {}
    index = 0
    while (entry := await client.reg_enum_value(key, index)) is not None:
        values[entry[0]] = entry[2]
        index += 1
    await client.reg_close_key(key)
    return values


async def wait_until(condition, seconds=30):
    for _ in range(seconds):
        if await condition():
            return True
        await asyncio.sleep(1)
    return False


async def app_names(client):
    return {app.name for app in await list_installed_apps(client)}


async def check_load_install(client):
    outcomes = await install_file(client, Path(VELO_EMU) / "tests" / "load" / "Test.load", destination="\\Windows\\LoadTest")
    assert outcomes[0].errors == []
    assert await client.read_file_contents("\\Windows\\LoadTest\\tool.exe") == b"mips build\n"
    assert await client.read_file_contents("\\Windows\\Load Test\\Read Me.txt") == b"plain file\n"
    assert await client.read_file_contents("\\Windows\\Load Test\\Tool.lnk") == b"26#\\Windows\\LoadTest\\tool.exe"
    assert await client.read_file_contents("\\Windows\\Load Test\\Volume.lnk") == b'59#"\\Windows\\ctlpnl.exe" \\Windows\\sounds.cpl,Volume & Sounds,0'
    assert await client.read_file_contents("\\Windows\\Load Test\\Root.lnk") == b"1#\\"
    assert "Empty" in {entry.name for entry in await client.find_all_files("\\Windows\\Load Test\\*.*")}
    load_test = await registry_values(client, HKEY_LOCAL_MACHINE, "Software\\LoadTest")
    assert load_test == {"Name": "Load Test", "List": ["one", "two", "three"]}
    assert (await registry_values(client, HKEY_CLASSES_ROOT, ".loadtest")).get("Default") == "loadtestfile"
    home = await registry_values(client, HKEY_LOCAL_MACHINE, "Software\\Apps\\Load Test")
    assert home["Count"] == 42 and home["Tool"] == "\\Windows\\LoadTest\\tool.exe" and home["Instl"] == 1
    assert not await client.find_all_files("\\Windows\\LoadTest\\never.exe")
    assert "Load Test" in await app_names(client)
    await uninstall_app(client, "Load Test")
    assert await wait_until(lambda: removed(client, "Load Test", "\\Windows\\Load Test\\*.*"))


async def check_cab_install(client):
    files = [("hello.txt", ["%CE1%", "classicsync test"], b"hello from classicsync\r\n")]
    package = read_cab_package(build_ce_cab("Install Test", "classicsync", 4000, files), "InstallTest.mips.cab")
    outcome = await install_cab(client, package)
    assert outcome.device_path == "\\Windows\\AppMgr\\Install\\InstallTest.mips.cab"

    async def installed():
        queued = await client.find_all_files("\\Windows\\AppMgr\\Install\\*.*")
        return not queued and "classicsync Install Test" in await app_names(client)

    assert await wait_until(installed)
    assert await client.read_file_contents("\\Program Files\\classicsync test\\hello.txt") == files[0][2]
    await uninstall_app(client, "classicsync Install Test")
    assert await wait_until(lambda: removed(client, "classicsync Install Test", "\\Program Files\\classicsync test\\*.*"))


async def removed(client, name, pattern):
    return name not in await app_names(client) and not await client.find_all_files(pattern)


def test_install_and_uninstall(emulated_device):
    name, port = emulated_device

    async def scenario():
        desktop, client = await connected_client(port)
        try:
            if name == "ce1":
                await check_load_install(client)
            else:
                await check_cab_install(client)
        finally:
            client.close()
            await desktop.close()

    asyncio.run(asyncio.wait_for(scenario(), 240))
