import json
import os
import sys
from pathlib import Path

import logging

import wx

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

home = Path(os.environ["CLASSICSYNC_HOME"])
output = Path(sys.argv[2])
home.mkdir(parents=True, exist_ok=True)
(home / "settings.json").write_text(json.dumps({"serial_port": sys.argv[1], "language": os.environ.get("CLASSICSYNC_LANGUAGE", ""), "rapi_proxy": "127.0.0.1:19996",
                                                "frontend": "activesync31", "sync_mode": "manual"}))

from classicsync.gui.app import Application
from classicsync.gui.common.conflicts import CombineReplaceDialog, ResolveConflictDialog
from classicsync.gui.common.sync_runner import EVENT_FAILED, EVENT_FINISHED
from classicsync.gui.frontends.activesync31 import partnership_wizard
from classicsync.gui.service import STATE_CONNECTED
from classicsync.rapi import cedb
from classicsync.sync.partners import DevicePartner, DevicePartners, read_device_partners

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
steps = []


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
    future.add_done_callback(lambda done: wx.CallAfter(then, done.result() if not done.exception() else done.exception()))


async def prepare_device(client):
    handle, _ = await client.open_database("Contacts Database")
    oid = await client.write_record(handle, 0, [cedb.PropertyValue(*GIVEN_NAME, "Ada"), cedb.PropertyValue(*SURNAME, "Lovelace")])
    await client.close_handle(handle)
    return oid


def start():
    wait_for(lambda: application.service.state == STATE_CONNECTED and application.device_details and
             application.device_details.get("partnership") is not None, connected, "connection")


def connected(_):
    log("partnership on connect:", application.partnership)
    name = application.device_details.get("name")
    folder = home / "data" / name / "Contacts"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "grace.vcf").write_text("BEGIN:VCARD\nVERSION:4.0\nN:Hopper;Grace;;;\nFN:Grace Hopper\nEND:VCARD\n")
    on_device(prepare_device, lambda oid: wait_for(lambda: top_level(partnership_wizard.NewPartnershipWizard),
                                                   capture_wizard, "wizard"))


def capture_wizard(wizard):
    original_flags, original_partners = wizard.flags, wizard.partners
    wizard.flags |= partnership_wizard.FLAG_NAME | partnership_wizard.FLAG_HAS_PARTNERSHIP | partnership_wizard.FLAG_TWO_PARTNERSHIPS
    wizard.partners = DevicePartners(partners=[DevicePartner(1, 0x1234, "OFFICE"), DevicePartner(2, 0x5678, "HOME")],
                                     services_version=0x20000)
    pages = [partnership_wizard.PAGE_START, partnership_wizard.PAGE_NAME, partnership_wizard.PAGE_COUNT,
             partnership_wizard.PAGE_DELETE, partnership_wizard.PAGE_TYPES, partnership_wizard.PAGE_COMPLETE]

    def grab(index=0):
        if index == len(pages):
            wizard.flags, wizard.partners = original_flags, original_partners
            wizard.history = []
            wizard.show_page(partnership_wizard.PAGE_START)
            wx.CallLater(300, click_through, wizard)
            return
        wizard.show_page(pages[index])
        wx.CallLater(300, lambda: (capture(wizard, f"wizard-{pages[index]}"), grab(index + 1)))

    grab()


def click_through(wizard):
    visited = [wizard.current]
    while wizard.current != partnership_wizard.PAGE_COMPLETE:
        wizard.on_next(None)
        visited.append(wizard.current)
    log("wizard pages", visited)
    application.sync.add_listener(on_sync)
    wait_for(lambda: top_level(CombineReplaceDialog), answer_combine, "combine dialog")
    wizard.on_next(None)


def answer_combine(dialog):
    capture(dialog, "combine-or-replace")
    dialog.EndModal(wx.ID_OK)


finished = []


def on_sync(kind, payload):
    if kind not in (EVENT_FINISHED, EVENT_FAILED):
        return
    log("sync", kind, payload.summary() if kind == EVENT_FINISHED else payload)
    finished.append(payload)
    wx.CallLater(800, [after_first_sync, after_conflict_sync, after_resolved_sync][len(finished) - 1]
                 if len(finished) <= 3 else application.quit)


def after_first_sync():
    capture(application.frontend.main_window, "synchronized")
    partnership = application.partnership
    log("partnership", partnership.name, partnership.label)
    options = partnership.load_options()
    options.conflict["*"] = "skip"
    partnership.save_options(options)
    contacts = partnership.load_state()["types"]["contacts"]["items"]
    entry = next(item for item in contacts if "Lovelace" in item["desktop_id"] or "Ada" in item["desktop_id"])
    card = home / "data" / application.device_details["name"] / "Contacts" / (entry["desktop_id"] + ".vcf")
    card.write_text(card.read_text().replace("Lovelace", "King"))

    async def edit(client):
        handle, _ = await client.open_database("Contacts Database")
        try:
            await client.write_record(handle, int(entry["device_id"], 16), [cedb.PropertyValue(*SURNAME, "Byron")])
        finally:
            await client.close_handle(handle)

    on_device(edit, lambda result: application.sync.start())


def after_conflict_sync():
    window = application.frontend.main_window
    capture(window, "unresolved")
    log("unresolved", [(item.desktop, item.device) for item in application.sync.unresolved_items()])
    wait_for(lambda: top_level(ResolveConflictDialog), resolve, "resolve dialog")
    application.frontend.show_resolve_items(window)


def resolve(dialog):
    capture(dialog, "resolve-items")
    dialog.set_resolution(0, "device")
    wx.CallLater(300, lambda: (capture(dialog, "resolve-items-chosen"), dialog.EndModal(wx.ID_OK)))


def after_resolved_sync():
    capture(application.frontend.main_window, "resolved")
    log("unresolved after", application.sync.unresolved_items())
    menu = application.frontend.main_window.mobile_device_menu
    log("mobile device menu", [item.GetItemLabelText() for item in menu.GetMenuItems()])

    def deleted(result, error):
        log("deleted", error)
        on_device(read_device_partners, lambda partners: (log("device partners", partners),
                                                          wx.CallLater(500, finish)))

    application.delete_partnership(application.partnership, deleted)


def finish():
    capture(application.frontend.main_window, "guest-after-delete")
    application.quit()


wx.CallLater(1000, start)
wx.CallLater(400000, application.quit)
application.MainLoop()
