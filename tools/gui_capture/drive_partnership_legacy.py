import json
import os
import sys
from pathlib import Path

import wx

home = Path(os.environ["CLASSICSYNC_HOME"])
output = Path(sys.argv[2])
frontend_key = os.environ.get("CLASSICSYNC_FRONTEND", "ceservices22")
home.mkdir(parents=True, exist_ok=True)
(home / "settings.json").write_text(json.dumps({"serial_port": sys.argv[1], "language": os.environ.get("CLASSICSYNC_LANGUAGE", ""), "rapi_proxy": "127.0.0.1:19995",
                                                "frontend": frontend_key, "sync_mode": "manual"}))

from classicsync.gui.app import Application
from classicsync.gui.common.conflicts import CombineDiscardDialog, ResolveConflictDialog
from classicsync.gui.common.new_device import CHOICE_PARTNERSHIP, NewDeviceDialog
from classicsync.gui.common.sync_runner import EVENT_FAILED, EVENT_FINISHED
from classicsync.gui.service import STATE_CONNECTED
from classicsync.rapi import cedb
from classicsync.sync.partners import read_device_partners

SURNAME = (0x3A11, cedb.CEVT_LPWSTR)
GIVEN_NAME = (0x3A06, cedb.CEVT_LPWSTR)


def capture(window, name):
    window.Update()
    bitmap = wx.WindowDC(window).GetAsBitmap()
    if bitmap.IsOk():
        bitmap.SaveFile(str(output / f"{name}.png"), wx.BITMAP_TYPE_PNG)
        print("captured", name, flush=True)


def log(*parts):
    print(*parts, flush=True)


application = Application(False)


def main_window():
    frontend = application.frontend
    return getattr(frontend, "main_window", None) or getattr(frontend, "explorer_window", None)


def top_level(kind):
    return next((window for window in wx.GetTopLevelWindows() if isinstance(window, kind) and window.IsShown()), None)


def wait_for(condition, then, name, attempts=240):
    def poll(remaining=attempts):
        found = condition()
        if found:
            wx.CallLater(400, then, found)
        elif remaining <= 0:
            log("timed out waiting for", name)
            application.quit()
        else:
            wx.CallLater(250, poll, remaining - 1)
    poll()


def on_device(operation, then):
    future = application.service.submit(application.service.with_rapi(operation))
    future.add_done_callback(lambda done: wx.CallAfter(then, done.exception() or done.result()))


async def add_contact(client):
    handle, _ = await client.open_database("Contacts Database")
    oid = await client.write_record(handle, 0, [cedb.PropertyValue(*GIVEN_NAME, "Ada"), cedb.PropertyValue(*SURNAME, "Lovelace")])
    await client.close_handle(handle)
    return oid


def start():
    wait_for(lambda: application.service.state == STATE_CONNECTED and application.device_details.get("partnership"),
             connected, "connection")


def connected(_):
    folder = home / "data" / application.device_details["name"] / "Contacts"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "grace.vcf").write_text("BEGIN:VCARD\nVERSION:4.0\nN:Hopper;Grace;;;\nFN:Grace Hopper\nEND:VCARD\n")
    on_device(add_contact, lambda result: wait_for(lambda: top_level(NewDeviceDialog), new_device, "new device dialog"))


def new_device(dialog):
    capture(dialog, "new-device")
    application.sync.add_listener(on_sync)
    wait_for(lambda: top_level(CombineDiscardDialog), combine, "combine dialog")
    dialog.choose(CHOICE_PARTNERSHIP)


def combine(dialog):
    capture(dialog, "combine-discard")
    dialog.EndModal(wx.ID_YES)


finished = []


def on_sync(kind, payload):
    if kind not in (EVENT_FINISHED, EVENT_FAILED):
        return
    log("sync", kind, payload.summary() if kind == EVENT_FINISHED else payload)
    finished.append(kind)
    if len(finished) == 1:
        wx.CallLater(1500, make_conflict)
    elif len(finished) == 2:
        wait_for(lambda: top_level(ResolveConflictDialog), resolve, "resolve dialog")
    elif len(finished) == 3:
        wx.CallLater(1500, delete)


def make_conflict():
    capture(main_window(), "synchronized")
    partnership = application.partnership
    log("partnership", partnership.name, partnership.label)
    application.sync.set_conflict_prompt("desktop")
    contacts = partnership.load_state()["types"]["contacts"]["items"]
    entry = next(item for item in contacts if "Ada" in item["desktop_id"])
    card = home / "data" / application.device_details["name"] / "Contacts" / (entry["desktop_id"] + ".vcf")
    card.write_text(card.read_text().replace("Lovelace", "King"))

    async def edit(client):
        handle, _ = await client.open_database("Contacts Database")
        try:
            await client.write_record(handle, int(entry["device_id"], 16), [cedb.PropertyValue(*SURNAME, "Byron")])
        finally:
            await client.close_handle(handle)

    on_device(edit, lambda result: application.sync.start())


def resolve(dialog):
    capture(dialog, "resolve-conflict")
    log("prompt default", [item.resolution for item in dialog.items])
    dialog.EndModal(wx.ID_OK)


def delete():
    capture(main_window(), "resolved")
    log("unresolved after", application.sync.unresolved_items())

    def deleted(result, error):
        log("deleted", error)
        on_device(read_device_partners, lambda partners: (log("device partners", partners), wx.CallLater(1500, finish)))

    application.delete_partnership(application.partnership, deleted)


def finish():
    capture(main_window(), "guest-after-delete")
    application.quit()


wx.CallLater(1000, start)
wx.CallLater(400000, application.quit)
application.MainLoop()
