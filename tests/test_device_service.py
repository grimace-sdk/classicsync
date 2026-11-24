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
