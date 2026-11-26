import asyncio
import struct

from test_dccm import build_block

from classicsync.connection import dccm
from classicsync.connection.dccm import KEEPALIVE, STATUS_NO_PARTNERSHIP
from classicsync.connection.network import NetworkDesktop


async def announce(port, block):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(struct.pack("<I", 0) + struct.pack("<I", len(block)) + block)
    await writer.drain()
    return reader, writer


def test_network_device_announces_and_reaches_rapi_through_the_override(run, monkeypatch):
    monkeypatch.setattr(dccm, "KEEPALIVE_INTERVAL", 0.05)
    monkeypatch.setattr(dccm, "KEEPALIVE_RESPONSE_WAIT", 0.5)

    async def scenario():
        async def rapi_server(reader, writer):
            writer.write(b"rapi here")
            await writer.drain()
            writer.close()
        rapi = await asyncio.start_server(rapi_server, "127.0.0.1", 0)
        rapi_port = rapi.sockets[0].getsockname()[1]
        desktop = NetworkDesktop(host="127.0.0.1", port=0, rapi_address=f"127.0.0.1:{rapi_port}")
        await desktop.start()
        reader, writer = await announce(desktop.listening_port(), build_block(name="Jornada720"))
        device = await desktop.wait_for_device(5)
        assert device.info.name == "Jornada720" and device.address == "127.0.0.1"
        assert await reader.readexactly(4) == struct.pack("<I", KEEPALIVE)
        writer.write(struct.pack("<I", KEEPALIVE))
        await writer.drain()
        connection = await desktop.connect_rapi_socket()
        assert await connection.readexactly(9) == b"rapi here"
        connection.close()
        writer.close()
        await asyncio.wait_for(desktop.link.finished, 5)
        assert desktop.device is None
        await desktop.close()
        rapi.close()
    run(scenario)


def test_unpartnered_network_device_is_refused_with_its_status(run):
    async def refuse(announcement):
        return STATUS_NO_PARTNERSHIP

    async def scenario():
        desktop = NetworkDesktop(host="127.0.0.1", port=0, partnership_policy=refuse)
        await desktop.start()
        reader, writer = await announce(desktop.listening_port(), build_block(flags=1))
        assert struct.unpack("<I", await asyncio.wait_for(reader.readexactly(4), 5))[0] == STATUS_NO_PARTNERSHIP
        assert await reader.read() == b""
        assert desktop.device is None
        writer.close()
        await desktop.close()
    run(scenario)
