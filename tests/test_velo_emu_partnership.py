import asyncio

import pytest
from test_velo_emu import VELO_EMU, ce1_state, emulated_device  # noqa: F401

from classicsync.connection.desktop import Desktop
from classicsync.link.transport import TcpSerialTransport
from classicsync.sync import (
    NoPartnership, SyncOptions, create_partnership, delete_partnership, find_partnership, read_device_partners, synchronize,
)

pytestmark = [
    pytest.mark.device,
    pytest.mark.skipif(not VELO_EMU, reason="set VELO_EMU to a velo-emu checkout to run against emulated devices"),
]


async def connect(port):
    desktop = Desktop(TcpSerialTransport("127.0.0.1", port))
    await desktop.start()
    announcement = await desktop.wait_for_device(90)
    return desktop, announcement, await desktop.open_rapi()


def announced_ids(announcement):
    return () if announcement.legacy else announcement.info.partner_ids


def test_partnership_survives_reconnect(emulated_device, tmp_path, monkeypatch):
    name, port = emulated_device
    monkeypatch.setenv("CLASSICSYNC_HOME", str(tmp_path))
    options = SyncOptions(object_types=["contacts"], provider_settings={"folder": str(tmp_path / "folder")})

    async def session(check):
        desktop, announcement, client = await connect(port)
        try:
            return await check(announcement, client)
        finally:
            client.close()
            await desktop.close()
            await asyncio.sleep(2)

    async def as_guest_then_create(announcement, client):
        assert announced_ids(announcement) in ((), (0, 0))
        lookup = await find_partnership(client, announced_ids(announcement))
        assert lookup.partnership is None
        assert lookup.partners.legacy == (name == "ce1")
        assert lookup.partners.services_supported == (name == "ce2")
        with pytest.raises(NoPartnership):
            await synchronize(client, None, options)
        return await create_partnership(client, partners=lookup.partners)

    async def recognised(announcement, client):
        if name == "ce2":
            assert announcement.info.partner_ids == (partnership.partner_id, 0)
        lookup = await find_partnership(client, announced_ids(announcement))
        assert lookup.partnership is not None and lookup.partnership.partner_id == partnership.partner_id
        report = await synchronize(client, None, options)
        assert not report.errors
        await delete_partnership(lookup.partnership, client)
        assert (await read_device_partners(client)).partner_ids == []

    async def forgotten(announcement, client):
        assert announced_ids(announcement) in ((), (0, 0))
        assert (await find_partnership(client, announced_ids(announcement))).partnership is None

    async def scenario():
        await asyncio.sleep(0.5)
        nonlocal partnership
        partnership = await session(as_guest_then_create)
        assert partnership.explicit
        await session(recognised)
        await session(forgotten)

    partnership = None
    asyncio.run(asyncio.wait_for(scenario(), 420))
