import asyncio
import os

from conftest import DESKTOP_IP, DEVICE_IP


def test_ppp_negotiates_addresses(run, linked_pair):
    async def scenario():
        pair = linked_pair()
        await pair.start()
        assert pair.device_link.local_ip == DEVICE_IP
        assert pair.device_link.peer_ip == DESKTOP_IP
        assert pair.desktop_link.tx_accm == 0
        await pair.close()
    run(scenario)


def test_ping_both_ways(run, linked_pair):
    async def scenario():
        pair = linked_pair()
        await pair.start()
        assert await pair.desktop.ping() >= 0
        assert await pair.device.ping() >= 0
        await pair.close()
    run(scenario)


def test_device_connects_to_desktop_listener(run, linked_pair):
    async def scenario():
        pair = linked_pair()
        await pair.start()
        listener = pair.desktop.listen(5679)
        device_side = await pair.device.connect(5679)
        desktop_side = await listener.accept()
        device_side.write(b"hello desktop")
        assert await desktop_side.readexactly(13) == b"hello desktop"
        desktop_side.write(b"hello device")
        assert await device_side.readexactly(12) == b"hello device"
        device_side.close()
        assert await desktop_side.read() == b""
        desktop_side.close()
        await asyncio.wait_for(desktop_side.wait_closed(), 5)
        await asyncio.wait_for(device_side.wait_closed(), 5)
        await pair.close()
    run(scenario)


def test_bulk_transfer_desktop_to_device(run, linked_pair):
    async def scenario():
        pair = linked_pair()
        await pair.start()
        listener = pair.device.listen(990)
        desktop_side = await pair.desktop.connect(990)
        device_side = await listener.accept()
        blob = os.urandom(300_000)

        async def send():
            for offset in range(0, len(blob), 7000):
                desktop_side.write(blob[offset:offset + 7000])
                await desktop_side.drain()
            await desktop_side.flush()

        sender = asyncio.create_task(send())
        received = await device_side.readexactly(len(blob))
        await sender
        assert received == blob
        await pair.close()
    run(scenario)


def test_connect_to_closed_port_is_refused(run, linked_pair):
    async def scenario():
        pair = linked_pair()
        await pair.start()
        try:
            await pair.desktop.connect(1234)
        except ConnectionError as error:
            assert "refused" in str(error)
        else:
            raise AssertionError("expected refusal")
        await pair.close()
    run(scenario)


def test_link_down_resets_connections(run, linked_pair):
    async def scenario():
        pair = linked_pair()
        await pair.start()
        listener = pair.desktop.listen(5679)
        await pair.device.connect(5679)
        desktop_side = await listener.accept()
        await pair.device_link.close()
        try:
            await asyncio.wait_for(desktop_side.read(), 10)
        except ConnectionError:
            pass
        else:
            raise AssertionError("expected reset")
        await pair.desktop_link.close(terminate=False)
    run(scenario)
