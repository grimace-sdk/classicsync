import asyncio

import pytest

from classicsync.link.ppp import ROLE_DESKTOP, ROLE_DEVICE, PppLink
from classicsync.link.transport import MemoryTransport
from classicsync.net.stack import NetworkStack

DESKTOP_IP = "192.168.55.100"
DEVICE_IP = "192.168.55.101"


class LinkedPair:
    def __init__(self):
        desktop_transport, device_transport = MemoryTransport.pair()
        self.desktop_link = PppLink(desktop_transport, ROLE_DESKTOP, local_ip=DESKTOP_IP, peer_ip=DEVICE_IP, dns_ip=DESKTOP_IP)
        self.device_link = PppLink(device_transport, ROLE_DEVICE)
        self.desktop = NetworkStack(self.desktop_link)
        self.device = NetworkStack(self.device_link)

    async def start(self):
        await self.desktop.start()
        await self.device.start()
        await self.desktop_link.start()
        await self.device_link.start()
        await asyncio.wait_for(asyncio.gather(self.desktop_link.wait_up(), self.device_link.wait_up()), 10)

    async def close(self):
        await self.device_link.close()
        await self.desktop_link.close(terminate=False)


@pytest.fixture
def run():
    def runner(coroutine_function):
        return asyncio.run(asyncio.wait_for(coroutine_function(), 30))
    return runner


@pytest.fixture
def linked_pair():
    return LinkedPair
