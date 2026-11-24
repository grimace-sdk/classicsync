import pytest

from classicsync.link import usb
from classicsync.link.transport import open_transport, port_has_baud


def test_known_device_table_has_period_cradles():
    assert (0x049F, 0x0003) in usb.KNOWN_DEVICES
    assert (0x03F0, 0x1016) in usb.KNOWN_DEVICES
    assert len(usb.KNOWN_DEVICES) == 453
    assert usb.KNOWN_DEVICES[(0x1114, 0x0004)].source.startswith("Linux")
    assert usb.KNOWN_DEVICES[(0x049F, 0x0003)].source.startswith("wceusbsh.inf")


def test_usb_and_tcp_ports_take_no_baud():
    assert not port_has_baud("usb")
    assert not port_has_baud("usb:049f:0003")
    assert not port_has_baud("tcp:127.0.0.1:9991")
    assert port_has_baud("/dev/ttyUSB0")
    assert port_has_baud("COM1")


def test_usb_spec_parsing_and_transport_selection():
    assert usb.parse_spec("usb:049f:0003") == (0x049F, 0x0003)
    assert isinstance(open_transport("usb:049f:0003"), usb.UsbSerialTransport)


def test_missing_device_is_reported(run):
    pytest.importorskip("usb.core")

    async def scenario():
        transport = open_transport("usb:049f:0003")
        with pytest.raises(OSError):
            await transport.open()

    run(scenario)
