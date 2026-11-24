import asyncio
import logging
from dataclasses import dataclass

from ..link.ppp import HANDSHAKE_REQUEST
from ..link.transport import open_transport, port_has_baud

log = logging.getLogger("classicsync.scanner")

AUTOBAUD_SPEEDS = [19200, 57600, 115200, 38400]
DTR_DROP_SECONDS = 2.0
LISTEN_SECONDS = 8.0
RECONNECT_SECONDS = 0.5
NETWORK_ATTEMPT_SECONDS = 3.0

STATUS_CHECKING = "checking"
STATUS_NOT_AVAILABLE = "not available"
STATUS_LOOKING = "looking"
STATUS_FOUND = "found"
STATUS_NOT_FOUND = "not found"


@dataclass
class ScanResult:
    port: str
    baud: int


async def listen_for_device(port, baud, seconds=LISTEN_SECONDS, cycle_dtr=True):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while True:
        attempt_deadline = deadline if cycle_dtr else min(deadline, loop.time() + NETWORK_ATTEMPT_SECONDS)
        result, ended_early = await _listen_once(port, baud, attempt_deadline, cycle_dtr)
        if result:
            return result
        if loop.time() + RECONNECT_SECONDS >= deadline or (cycle_dtr and not ended_early):
            return None
        await asyncio.sleep(RECONNECT_SECONDS)


async def _listen_once(port, baud, deadline, cycle_dtr):
    transport = open_transport(port, baud)
    await transport.open()
    try:
        if cycle_dtr:
            await transport.set_dtr(False)
            await asyncio.sleep(DTR_DROP_SECONDS)
            await transport.set_dtr(True)
        received = bytearray()
        loop = asyncio.get_running_loop()
        while loop.time() < deadline:
            try:
                data = await asyncio.wait_for(transport.read(), max(0.01, deadline - loop.time()))
            except asyncio.TimeoutError:
                break
            if not data:
                return None, True
            received += data
            if HANDSHAKE_REQUEST in received:
                return ScanResult(port, baud), False
            del received[:-64]
        return None, False
    finally:
        await transport.close()


async def scan_ports(ports, speeds=None, progress=None, seconds=LISTEN_SECONDS):
    report = progress or (lambda port, baud, status: None)
    for port in ports:
        is_network = not port_has_baud(port)
        for baud in ([None] if is_network else (speeds or AUTOBAUD_SPEEDS)):
            report(port, baud, STATUS_CHECKING)
            try:
                result = await listen_for_device(port, baud or 19200, seconds, cycle_dtr=not is_network)
            except (OSError, ImportError) as error:
                log.info("%s: %s", port, error)
                report(port, baud, STATUS_NOT_AVAILABLE)
                break
            if result:
                report(port, baud, STATUS_FOUND)
                return result
            report(port, baud, STATUS_LOOKING)
        report(port, None, STATUS_NOT_FOUND)
    return None
