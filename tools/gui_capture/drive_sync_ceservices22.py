import json
import os
import sys
from pathlib import Path

import wx

home = Path(os.environ["CLASSICSYNC_HOME"])
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
home.mkdir(parents=True, exist_ok=True)
(home / "settings.json").write_text(json.dumps({"serial_port": sys.argv[1], "language": os.environ.get("CLASSICSYNC_LANGUAGE", ""), "rapi_proxy": "127.0.0.1:19988", "show_tray_icon": True,
                                                "frontend": "ceservices22"}))

from classicsync.gui.app import Application
from partnership_prompts import answer_partnership_prompts
from classicsync.gui.common.sync_runner import EVENT_FAILED, EVENT_FINISHED, EVENT_PROGRESS, EVENT_STOPPED
from classicsync.gui.frontends.ceservices22.activesync import ActiveSyncOptionsSheet, AdvancedOptionsDialog
from classicsync.gui.frontends.ceservices22.mobile_devices import ID_SYNCHRONIZE_NOW, ID_VIEW_DETAILS
from classicsync.gui.service import STATE_CONNECTED


def capture(window, name):
    window.Update()
    bitmap = wx.WindowDC(window).GetAsBitmap()
    if bitmap.IsOk():
        bitmap.SaveFile(str(out / f"{name}.png"), wx.BITMAP_TYPE_PNG)
        print("captured", name, bitmap.GetSize(), flush=True)


def menu_labels(menu, indent=""):
    lines = []
    for item in menu.GetMenuItems():
        if item.IsSeparator():
            lines.append(indent + "----")
            continue
        flags = ("" if item.IsEnabled() else " [disabled]") + (" [checked]" if item.IsCheckable() and item.IsChecked() else "")
        lines.append(f"{indent}{item.GetItemLabel()}{flags}")
        if item.GetSubMenu():
            lines += menu_labels(item.GetSubMenu(), indent + "    ")
    return lines


def command(window, identifier):
    window.on_command(wx.CommandEvent(wx.wxEVT_MENU, identifier))


def device_rows():
    return [(row["name"], row["synchronization"]) for row in window().rows]


def status_rows():
    status = frontend.sync_status_window
    return [tuple(status.list.GetItemText(index, column) for column in range(3)) for index in range(status.list.GetItemCount())]


app = Application(False)
answer_partnership_prompts(create=True)
frontend = app.frontend
progress_captured = []


def window():
    return frontend.main_window


def wait_connected(attempts=[0]):
    attempts[0] += 1
    if app.service.state == STATE_CONNECTED and app.device_details and app.partnership:
        wx.CallLater(1500, step_connected)
    elif attempts[0] > 240:
        print("never connected", flush=True)
        app.quit()
    else:
        wx.CallLater(500, wait_connected)


def step_connected():
    command(window(), ID_VIEW_DETAILS)
    window().device_list.Select(0)
    print("devices before:", device_rows(), flush=True)
    print("tray connected:\n" + "\n".join(menu_labels(frontend.tray.CreatePopupMenu())), flush=True)
    print("device context:\n" + "\n".join(menu_labels(window()._device_context_menu())), flush=True)
    tools = window().GetMenuBar().GetMenu(window().GetMenuBar().FindMenu("Tools"))
    print("tools menu:\n" + "\n".join(menu_labels(tools)), flush=True)
    wx.CallLater(400, lambda: (capture(window(), "mobile-devices-before-sync"), step_options()))


def step_options():
    sheet = ActiveSyncOptionsSheet(window(), frontend)
    sheet.Show()

    def grab():
        capture(sheet, "activesync-options")
        sheet.Destroy()
        advanced = AdvancedOptionsDialog(window(), app.device_name(app.service.announcement), app.sync.conflict_policy(),
                                         frontend.sync_display)
        advanced.Show()
        wx.CallLater(500, lambda: (capture(advanced, "activesync-advanced"), advanced.Destroy(), step_status()))
    wx.CallLater(600, grab)


def step_status():
    frontend.show_sync_status()
    status = frontend.sync_status_window
    status.SetSize(wx.Size(560, 320))
    print("status window menus:", flush=True)
    menu_bar = status.GetMenuBar()
    status.update_commands()
    for index in range(menu_bar.GetMenuCount()):
        print(menu_bar.GetMenuLabelText(index))
        print("\n".join(menu_labels(menu_bar.GetMenu(index), "    ")), flush=True)
    print("status rows before:", status_rows(), flush=True)
    wx.CallLater(600, lambda: (capture(status, "activesync-status-before"), start_sync()))


def start_sync():
    app.sync.add_listener(on_sync)
    command(window(), ID_SYNCHRONIZE_NOW)
    print("running:", app.sync.running, flush=True)


def on_sync(kind, payload):
    if kind == EVENT_PROGRESS and payload.total and not progress_captured:
        progress_captured.append(True)

        def grab():
            dialog = frontend.sync_progress_dialog
            if dialog:
                capture(dialog, "progress")
            capture(frontend.sync_status_window, "activesync-status-syncing")
            print("status rows syncing:", status_rows(), flush=True)
            print("devices syncing:", device_rows(), flush=True)
        wx.CallLater(100, grab)
    elif kind in (EVENT_FINISHED, EVENT_FAILED, EVENT_STOPPED):
        print("sync", kind, payload.summary() if kind == EVENT_FINISHED else payload, flush=True)
        if kind == EVENT_FINISHED:
            for line in payload.errors:
                print("  error:", line, flush=True)
        app.sync.remove_listener(on_sync)
        wx.CallLater(1500, after_sync)


def after_sync():
    print("devices after:", device_rows(), flush=True)
    print("status rows after:", status_rows(), flush=True)
    print("status header after:", frontend.sync_status_window.status.GetLabel(), flush=True)
    capture(frontend.sync_status_window, "activesync-status-after")
    capture(window(), "mobile-devices-after-sync")
    print("device context after:\n" + "\n".join(menu_labels(window()._device_context_menu())), flush=True)
    wx.CallLater(500, app.quit)


wx.CallLater(1500, wait_connected)
wx.CallLater(900000, app.quit)
app.MainLoop()
