import asyncio

import pytest

from classicsync.gui import service as service_module
from classicsync.gui.service import STATE_WAITING, DeviceService
from classicsync.gui.settings import Settings

USB_SPEC = "usb:03f0:2016"


class FakeUsb:
    def __init__(self, available=True):
        self.available = available
        self.attached = []
        self.scans = 0

    def usb_available(self):
        return self.available

    def attached_devices(self):
        self.scans += 1
        return [(spec, None) for spec in self.attached]


@pytest.fixture
def fake_usb(monkeypatch):
    fake = FakeUsb()
    monkeypatch.setattr(service_module, "usb_available", fake.usb_available)
    monkeypatch.setattr(service_module, "attached_devices", fake.attached_devices)
    monkeypatch.setattr(service_module, "USB_POLL_SECONDS", 0.01)
    monkeypatch.setattr(service_module, "RESTART_SECONDS", 0.05)
    return fake


def make_service(**settings):
    device_service = DeviceService(Settings(**settings), lambda state, announcement, error: None)
    device_service.sessions = []

    async def fake_session(port):
        device_service.sessions.append(port)
        device_service._set_state(STATE_WAITING)
        try:
            await asyncio.Event().wait()
        finally:
            device_service.sessions.append(f"closed {port}")
    device_service._run_session = fake_session
    return device_service


async def wait_until(condition):
    while not condition():
        await asyncio.sleep(0.01)


def test_usb_device_replaces_a_waiting_serial_session(run, fake_usb):
    async def scenario():
        device_service = make_service(serial_port="/dev/cu.usbserial-10")
        supervisor = asyncio.create_task(device_service._supervise())
        await wait_until(lambda: device_service.sessions == ["/dev/cu.usbserial-10"])
        fake_usb.attached = [USB_SPEC]
        await wait_until(lambda: USB_SPEC in device_service.sessions)
        supervisor.cancel()
        assert device_service.sessions[:3] == ["/dev/cu.usbserial-10", "closed /dev/cu.usbserial-10", USB_SPEC]
    run(scenario)


def test_usb_only_waits_for_a_device(run, fake_usb):
    async def scenario():
        device_service = make_service(serial_enabled=False)
        supervisor = asyncio.create_task(device_service._supervise())
        await wait_until(lambda: fake_usb.scans > 3)
        assert device_service.sessions == []
        assert device_service.state == STATE_WAITING
        fake_usb.attached = [USB_SPEC]
        await wait_until(lambda: device_service.sessions == [USB_SPEC])
        supervisor.cancel()
    run(scenario)


def test_usb_disabled_never_scans(run, fake_usb):
    async def scenario():
        device_service = make_service(serial_port="/dev/cu.usbserial-10", usb_enabled=False)
        fake_usb.attached = [USB_SPEC]
        supervisor = asyncio.create_task(device_service._supervise())
        await wait_until(lambda: device_service.sessions == ["/dev/cu.usbserial-10"])
        await asyncio.sleep(0.05)
        supervisor.cancel()
        assert fake_usb.scans == 0
    run(scenario)


def test_missing_libusb_falls_back_to_serial(run, fake_usb):
    fake_usb.available = False

    async def scenario():
        device_service = make_service(serial_port="/dev/cu.usbserial-10")
        fake_usb.attached = [USB_SPEC]
        supervisor = asyncio.create_task(device_service._supervise())
        await wait_until(lambda: device_service.sessions == ["/dev/cu.usbserial-10"])
        supervisor.cancel()
        assert fake_usb.scans == 0
    run(scenario)


def test_missing_serial_adapter_is_not_an_error_while_usb_is_enabled(run, fake_usb):
    async def scenario():
        device_service = make_service(serial_port="/dev/cu.usbserial-110")
        states = []
        device_service.notify = lambda state, announcement, error: states.append((state, error))

        async def missing_port(port):
            raise OSError(2, f"could not open port {port}: [Errno 2]")
        device_service._run_session = missing_port
        supervisor = asyncio.create_task(device_service._supervise())
        await wait_until(lambda: len(states) >= 2)
        supervisor.cancel()
        assert all(error is None for state, error in states)
    run(scenario)


class FakeNetwork:
    def __init__(self):
        self.arrived = asyncio.Event()
        self.closed = False

    async def wait_for_device(self):
        await self.arrived.wait()
        return "network device"

    async def close(self):
        self.closed = True


def with_fake_network(device_service, network):
    async def open_network():
        return network if device_service.settings.network_enabled else None

    async def network_session(opened):
        device_service.sessions.append("network")
        await asyncio.Event().wait()
    device_service._open_network = open_network
    device_service._run_network_session = network_session


def test_network_device_replaces_a_waiting_serial_session(run, fake_usb):
    async def scenario():
        device_service = make_service(serial_port="/dev/cu.usbserial-10", usb_enabled=False, network_enabled=True)
        network = FakeNetwork()
        with_fake_network(device_service, network)
        supervisor = asyncio.create_task(device_service._supervise())
        await wait_until(lambda: device_service.sessions == ["/dev/cu.usbserial-10"])
        network.arrived.set()
        await wait_until(lambda: "network" in device_service.sessions)
        supervisor.cancel()
        assert device_service.sessions == ["/dev/cu.usbserial-10", "closed /dev/cu.usbserial-10", "network"]
    run(scenario)


def test_network_only_waits_for_a_device(run, fake_usb):
    async def scenario():
        device_service = make_service(serial_enabled=False, usb_enabled=False, network_enabled=True)
        network = FakeNetwork()
        with_fake_network(device_service, network)
        supervisor = asyncio.create_task(device_service._supervise())
        await wait_until(lambda: device_service.state == STATE_WAITING)
        assert device_service.sessions == []
        network.arrived.set()
        await wait_until(lambda: device_service.sessions == ["network"])
        supervisor.cancel()
    run(scenario)


def test_unavailable_network_alone_is_reported(run, fake_usb):
    async def scenario():
        device_service = make_service(serial_enabled=False, usb_enabled=False, network_enabled=True)
        errors = []
        device_service.notify = lambda state, announcement, error: errors.append(error)

        async def no_network():
            return None
        device_service._open_network = no_network
        supervisor = asyncio.create_task(device_service._supervise())
        await wait_until(lambda: any(errors))
        supervisor.cancel()
    run(scenario)


def test_gui_sync_reports_to_a_remote_device(run):
    import struct
    from types import SimpleNamespace

    from classicsync.connection.status_channel import StatusChannel

    async def scenario():
        device_service = make_service()
        status = StatusChannel("127.0.0.1", 0)
        await status.start()
        device_service.network = device_service.desktop = SimpleNamespace(status=status)
        device_service.announcement = SimpleNamespace(info=SimpleNamespace(remote_sync=True, os_major=3))
        reader, writer = await asyncio.open_connection("127.0.0.1", status.listening_port())
        assert await status.wait_for_device(5)

        async def operation():
            return SimpleNamespace(errors=[], actions=[], unresolved=[], summary=lambda: "nothing to do")
        await device_service.with_sync_status(operation)
        final = "$UPTODATE$\0".encode("utf-16-le")
        expected = struct.pack("<II", 0x005A0000, 0x005B0000) + struct.pack("<I", 0x00010000 | len(final)) + final
        assert await asyncio.wait_for(reader.readexactly(len(expected)), 5) == expected
        writer.close()
        status.close()
    run(scenario)
