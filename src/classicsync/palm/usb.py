import asyncio
import logging
import struct

from ..link.transport import Transport
from ..link.usb import require_pyusb, usb_backend

log = logging.getLogger("classicsync.palm.usb")

PALM_VENDOR_ID = 0x0830
REQUEST_TYPE_VENDOR_IN_ENDPOINT = 0xC2
GET_EXT_CONNECTION_INFO = 4
EXT_CONNECTION_INFO_LENGTH = 20
EXT_CONNECTION_ENTRY = struct.Struct("<4sBBH")
HOTSYNC_CREATOR = b"sync"
DEFAULT_HOTSYNC_PORT = 2
ENDPOINT_IN = 0x80
CONTROL_TIMEOUT_MS = 2000
READ_TIMEOUT_MS = 500
WRITE_TIMEOUT_MS = 10000
READ_SIZE = 4096
POLL_SECONDS = 0.25


def attached_palm():
    try:
        core, _ = require_pyusb()
        return core.find(backend=usb_backend(), idVendor=PALM_VENDOR_ID)
    except Exception as error:
        log.info("USB enumeration unavailable: %s", error)
        return None


async def wait_for_palm(timeout):
    loop = asyncio.get_running_loop()
    deadline = None if timeout is None else loop.time() + timeout
    while True:
        device = await asyncio.to_thread(attached_palm)
        if device is not None:
            return device
        if deadline is not None and loop.time() >= deadline:
            raise TimeoutError("no Palm handheld appeared on USB; press the HotSync button on the cradle")
        await asyncio.sleep(POLL_SECONDS)


def hotsync_port(connection_info):
    port_count, different_endpoints = connection_info[0], connection_info[1]
    for index in range(min(port_count, 2)):
        creator, port, endpoints, _ = EXT_CONNECTION_ENTRY.unpack_from(connection_info, 4 + index * EXT_CONNECTION_ENTRY.size)
        if creator[::-1] != HOTSYNC_CREATOR:
            continue
        if different_endpoints and endpoints:
            return endpoints >> 4 | ENDPOINT_IN, endpoints & 0x0F
        return port | ENDPOINT_IN, port
    return DEFAULT_HOTSYNC_PORT | ENDPOINT_IN, DEFAULT_HOTSYNC_PORT


class PalmUsbTransport(Transport):
    def __init__(self, device):
        self.device = device
        self.name = f"usb:{device.idVendor:04x}:{device.idProduct:04x}"
        self.endpoint_in = DEFAULT_HOTSYNC_PORT | ENDPOINT_IN
        self.endpoint_out = DEFAULT_HOTSYNC_PORT
        self.max_packet = 64
        self.pending = []
        self.closed = False

    async def open(self):
        await asyncio.to_thread(self._open)

    def _open(self):
        core, _ = require_pyusb()
        try:
            self.device.set_configuration()
        except core.USBError as error:
            log.info("%s set configuration: %s", self.name, error)
        try:
            info = bytes(self.device.ctrl_transfer(REQUEST_TYPE_VENDOR_IN_ENDPOINT, GET_EXT_CONNECTION_INFO, 0, 0,
                                                   EXT_CONNECTION_INFO_LENGTH, timeout=CONTROL_TIMEOUT_MS))
            self.endpoint_in, self.endpoint_out = hotsync_port(info)
        except core.USBError as error:
            log.info("%s has no extended connection info (%s); using endpoint %d", self.name, error, DEFAULT_HOTSYNC_PORT)
        for interface in self.device.get_active_configuration():
            for endpoint in interface:
                if endpoint.bEndpointAddress == self.endpoint_out:
                    self.max_packet = endpoint.wMaxPacketSize
        log.info("%s HotSync port: in %#04x, out %#04x", self.name, self.endpoint_in, self.endpoint_out)

    async def read(self):
        core, _ = require_pyusb()
        while not self.closed:
            try:
                return bytes(await asyncio.to_thread(self.device.read, self.endpoint_in, READ_SIZE, READ_TIMEOUT_MS))
            except core.USBTimeoutError:
                continue
            except core.USBError as error:
                log.info("%s read failed: %s", self.name, error)
                return b""
        return b""

    def write(self, data):
        self.pending.append(bytes(data))

    async def drain(self):
        transfers, self.pending = self.pending, []
        await asyncio.to_thread(self._write_transfers, transfers)

    def _write_transfers(self, transfers):
        for data in transfers:
            self.device.write(self.endpoint_out, data, timeout=WRITE_TIMEOUT_MS)
            if data and len(data) % self.max_packet == 0:
                self.device.write(self.endpoint_out, b"", timeout=WRITE_TIMEOUT_MS)

    async def close(self):
        self.closed = True
        _, util = require_pyusb()
        await asyncio.to_thread(util.dispose_resources, self.device)
