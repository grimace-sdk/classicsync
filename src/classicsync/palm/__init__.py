from contextlib import asynccontextmanager

from .dlp import DatabaseInfo, DlpClient, DlpCommand, DlpError, DlpStatus, SysInfo, UserInfo
from .netsync import NetSyncError, NetSyncLink
from .usb import PalmUsbTransport, wait_for_palm


@asynccontextmanager
async def palm_usb_session(wait=None):
    transport = PalmUsbTransport(await wait_for_palm(wait))
    await transport.open()
    try:
        link = NetSyncLink(transport)
        await link.accept()
        yield DlpClient(link)
    finally:
        await transport.close()


__all__ = ["DatabaseInfo", "DlpClient", "DlpCommand", "DlpError", "DlpStatus", "NetSyncError", "NetSyncLink",
           "PalmUsbTransport", "SysInfo", "UserInfo", "palm_usb_session", "wait_for_palm"]
