import asyncio

from classicsync.connection.scanner import STATUS_FOUND, STATUS_NOT_AVAILABLE, scan_ports


async def start_fake_device(payload):
    async def handle(reader, writer):
        writer.write(payload)
        await writer.drain()
        await asyncio.sleep(2)
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


def test_scanner_finds_device_sending_client(run):
    async def scenario():
        server, port = await start_fake_device(b"\x00\xffCLIENT")
        reports = []
        result = await scan_ports([f"tcp:127.0.0.1:{port}"], progress=lambda *report: reports.append(report), seconds=3)
        server.close()
        assert result and result.port == f"tcp:127.0.0.1:{port}"
        assert reports[-1][2] == STATUS_FOUND
    run(scenario)


def test_scanner_skips_silent_and_missing_ports(run):
    async def scenario():
        server, silent_port = await start_fake_device(b"noise")
        reports = []
        result = await scan_ports([f"tcp:127.0.0.1:{silent_port}", "tcp:127.0.0.1:1"],
                                  progress=lambda *report: reports.append(report), seconds=1)
        server.close()
        assert result is None
        assert ("tcp:127.0.0.1:1", None, STATUS_NOT_AVAILABLE) in reports
    run(scenario)
