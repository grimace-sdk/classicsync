import asyncio
import logging
import threading
from dataclasses import dataclass
from importlib import resources

from .transport import Transport

log = logging.getLogger("classicsync.usb")

REQUEST_TYPE_CLASS_INTERFACE_OUT = 0x21
REQUEST_SET_CONTROL_LINE_STATE = 0x22
LINE_STATE_DTR = 0x01
LINE_STATE_DTR_RTS = 0x03
READY_ATTEMPTS = 100
CONTROL_TIMEOUT_MS = 100
READ_TIMEOUT_MS = 200
WRITE_TIMEOUT_MS = 5000
READ_SIZE = 4096


@dataclass(frozen=True)
class KnownDevice:
    vendor_id: int
    product_id: int
    interface: int
    manufacturer: str
    description: str
    source: str = ""


def _load_known_devices():
    devices = {}
    text = resources.files(__package__).joinpath("wceusb_ids.tsv").read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        vendor, product, interface, manufacturer, description, source = (line.split("\t") + [""] * 6)[:6]
        key = (int(vendor, 16), int(product, 16))
        devices.setdefault(key, KnownDevice(key[0], key[1], int(interface, 16) if interface else -1, manufacturer, description, source))
    return devices


KNOWN_DEVICES = _load_known_devices()


def require_pyusb():
    try:
        import usb.core
        import usb.util
    except ImportError as error:
        raise OSError("USB connections need pyusb and libusb: pip install 'classicsync[usb]'") from error
    return usb.core, usb.util


def usb_available():
    try:
        core, _ = require_pyusb()
        list(core.find(find_all=True))
    except Exception as error:
        log.info("USB connections unavailable: %s", error)
        return False
    return True


def attached_devices():
    try:
        core, _ = require_pyusb()
        found = list(core.find(find_all=True))
    except Exception as error:
        log.info("USB enumeration unavailable: %s", error)
        return []
    matches = []
    for device in found:
        known = KNOWN_DEVICES.get((device.idVendor, device.idProduct))
        if known:
            matches.append((f"usb:{device.idVendor:04x}:{device.idProduct:04x}", known))
    return matches


def parse_spec(spec):
    parts = spec.split(":")[1:]
    if len(parts) >= 2 and parts[0] and parts[1]:
        return int(parts[0], 16), int(parts[1], 16)
    attached = attached_devices()
    if not attached:
        raise OSError("no Windows CE USB device found")
    known = attached[0][1]
    return known.vendor_id, known.product_id


def _bulk_interface(configuration, preferred_number, util):
    candidates = []
    for interface in configuration:
        endpoint_in = util.find_descriptor(interface, custom_match=lambda endpoint: util.endpoint_type(endpoint.bmAttributes) == util.ENDPOINT_TYPE_BULK
                                           and util.endpoint_direction(endpoint.bEndpointAddress) == util.ENDPOINT_IN)
        endpoint_out = util.find_descriptor(interface, custom_match=lambda endpoint: util.endpoint_type(endpoint.bmAttributes) == util.ENDPOINT_TYPE_BULK
                                            and util.endpoint_direction(endpoint.bEndpointAddress) == util.ENDPOINT_OUT)
        if endpoint_in and endpoint_out:
            candidates.append((interface, endpoint_in, endpoint_out))
    if not candidates:
        raise OSError("USB device has no interface with bulk IN and OUT endpoints")
    for candidate in candidates:
        if candidate[0].bInterfaceNumber == preferred_number:
            return candidate
    return max(candidates, key=lambda candidate: candidate[0].bInterfaceNumber)


class UsbSerialTransport(Transport):
    def __init__(self, spec, line_state=LINE_STATE_DTR, coalesce_writes=True):
        self.spec = spec
        self.line_state = line_state
        self.coalesce_writes = coalesce_writes
        self.name = spec
        self.device = None
        self.interface_number = None
        self.endpoint_in = None
        self.endpoint_out = None
        self.loop = None
        self.queue = None
        self.reader = None
        self.writer = None
        self.outgoing = None
        self.stopping = threading.Event()
        self.detached_kernel_driver = False

    async def open(self):
        await asyncio.to_thread(self._open_device)
        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue()
        self.outgoing = []
        self.outgoing_ready = threading.Condition()
        self.stopping.clear()
        self.reader = threading.Thread(target=self._read_loop, name=f"usb-read-{self.spec}", daemon=True)
        self.writer = threading.Thread(target=self._write_loop, name=f"usb-write-{self.spec}", daemon=True)
        self.reader.start()
        self.writer.start()

    def _open_device(self):
        core, util = require_pyusb()
        vendor_id, product_id = parse_spec(self.spec)
        self.name = f"usb:{vendor_id:04x}:{product_id:04x}"
        try:
            device = core.find(idVendor=vendor_id, idProduct=product_id)
        except core.NoBackendError as error:
            raise OSError("USB connections need libusb, which was not found (see the README)") from error
        if device is None:
            raise OSError(f"USB device {vendor_id:04x}:{product_id:04x} is not attached")
        try:
            configuration = device.get_active_configuration()
        except core.USBError:
            device.set_configuration()
            configuration = device.get_active_configuration()
        known = KNOWN_DEVICES.get((vendor_id, product_id))
        interface, self.endpoint_in, self.endpoint_out = _bulk_interface(configuration, known.interface if known else -1, util)
        self.interface_number = interface.bInterfaceNumber
        try:
            if device.is_kernel_driver_active(self.interface_number):
                device.detach_kernel_driver(self.interface_number)
                self.detached_kernel_driver = True
        except (NotImplementedError, core.USBError):
            pass
        util.claim_interface(device, self.interface_number)
        self.device = device
        self._signal_ready(core)

    def _signal_ready(self, core):
        for _ in range(READY_ATTEMPTS):
            try:
                self._set_line_state(self.line_state)
                return
            except core.USBError:
                continue
        log.info("%s never acknowledged SET_CONTROL_LINE_STATE; continuing", self.name)

    def _set_line_state(self, value):
        self.device.ctrl_transfer(REQUEST_TYPE_CLASS_INTERFACE_OUT, REQUEST_SET_CONTROL_LINE_STATE, value, self.interface_number,
                                  None, CONTROL_TIMEOUT_MS)

    def _read_loop(self):
        core, _ = require_pyusb()
        while not self.stopping.is_set():
            try:
                data = bytes(self.endpoint_in.read(READ_SIZE, READ_TIMEOUT_MS))
            except core.USBTimeoutError:
                continue
            except core.USBError as error:
                if self.stopping.is_set():
                    return
                log.info("%s read failed: %s", self.name, error)
                self.loop.call_soon_threadsafe(self.queue.put_nowait, b"")
                return
            if data:
                self.loop.call_soon_threadsafe(self.queue.put_nowait, data)

    def _write_loop(self):
        core, _ = require_pyusb()
        while True:
            with self.outgoing_ready:
                while not self.outgoing and not self.stopping.is_set():
                    self.outgoing_ready.wait(0.5)
                if self.stopping.is_set():
                    return
                transfers = [b"".join(self.outgoing)] if self.coalesce_writes else list(self.outgoing)
                self.outgoing.clear()
            try:
                for data in transfers:
                    self.endpoint_out.write(data, WRITE_TIMEOUT_MS)
            except core.USBError as error:
                log.info("%s write failed: %s", self.name, error)
                self.loop.call_soon_threadsafe(self.queue.put_nowait, b"")
                return

    async def read(self):
        return await self.queue.get()

    def write(self, data):
        with self.outgoing_ready:
            self.outgoing.append(bytes(data))
            self.outgoing_ready.notify()

    async def set_dtr(self, active):
        if self.device:
            await asyncio.to_thread(self._set_line_state, self.line_state if active else 0)

    async def reset_device(self):
        await asyncio.to_thread(self._reset_device)

    def _reset_device(self):
        core, util = require_pyusb()
        vendor_id, product_id = parse_spec(self.spec)
        device = core.find(idVendor=vendor_id, idProduct=product_id)
        if device is None:
            return False
        try:
            device.reset()
        except core.USBError as error:
            log.info("%s reset failed: %s", self.name, error)
        util.dispose_resources(device)
        return True

    async def close(self):
        self.stopping.set()
        if self.outgoing is not None:
            with self.outgoing_ready:
                self.outgoing_ready.notify()
        for thread in (self.reader, self.writer):
            if thread:
                await asyncio.to_thread(thread.join, 1)
        if self.device:
            await asyncio.to_thread(self._release)

    def _release(self):
        core, util = require_pyusb()
        try:
            self._set_line_state(0)
        except core.USBError:
            pass
        try:
            util.release_interface(self.device, self.interface_number)
            if self.detached_kernel_driver:
                self.device.attach_kernel_driver(self.interface_number)
        except (NotImplementedError, core.USBError):
            pass
        util.dispose_resources(self.device)
        self.device = None
