import asyncio
import os
import subprocess

import pytest

from classicsync.connection.desktop import Desktop
from classicsync.link.transport import TcpSerialTransport

from test_velo_emu import free_port

VELO_EMU = os.environ.get("VELO_EMU")

pytestmark = [
    pytest.mark.device,
    pytest.mark.skipif(not VELO_EMU, reason="set VELO_EMU to a velo-emu checkout to run against emulated devices"),
]


@pytest.fixture
def ce2_device():
    port = free_port()
    process = subprocess.Popen(
        ["./headless", "rom/nk-ce2-merged-patchsets-115k.bin", "--load=ce2-merged-115k-desktop-16mb.state", "--seconds=100000",
         "--realtime=1", f"--tcp={port}"],
        cwd=VELO_EMU, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    yield port
    process.terminate()
    process.wait(10)


def test_password_protected_device(ce2_device):
    async def connect(password_provider=None):
        desktop = Desktop(TcpSerialTransport("127.0.0.1", ce2_device), password_provider=password_provider)
        await desktop.start()
        return desktop

    async def scenario():
        await asyncio.sleep(0.5)
        desktop = await connect()
        announcement = await desktop.wait_for_device(60)
        assert announcement.key == 0
        client = await desktop.open_rapi()
        await client.set_password(None, "secret")
        await client.set_password_active(True, "secret")
        assert await client.get_password_active()
        client.close()
        await desktop.close()

        attempts = []

        async def provider(announcement, attempt):
            attempts.append(attempt)
            return "wrong" if attempt == 0 else "Secret"

        await asyncio.sleep(2)
        desktop = await connect(provider)
        try:
            announcement = await desktop.wait_for_device(90)
            assert announcement.key != 0
            assert attempts == [0, 1]
            client = await desktop.open_rapi()
            version = await client.get_version()
            assert version.major == 2
            client.close()
        finally:
            await desktop.close()

    asyncio.run(asyncio.wait_for(scenario(), 240))
