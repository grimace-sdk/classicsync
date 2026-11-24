import json
import os
import sys
from pathlib import Path

import wx

home = Path(os.environ["CLASSICSYNC_HOME"])
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
home.mkdir(parents=True, exist_ok=True)
(home / "settings.json").write_text(json.dumps({"serial_port": sys.argv[1], "language": os.environ.get("CLASSICSYNC_LANGUAGE", ""), "rapi_proxy": "127.0.0.1:19989",
                                                "show_tray_icon": True, "frontend": "hpcexplorer11"}))

from classicsync.gui.app import Application
from partnership_prompts import answer_partnership_prompts
from classicsync.gui.common.sync_runner import EVENT_FAILED, EVENT_FINISHED, EVENT_PROGRESS, EVENT_STOPPED
from classicsync.gui.frontends.hpcexplorer11.commands import ID_SYNCHRONIZATION_MANAGER, ID_SYNCHRONIZE_NOW
from classicsync.gui.frontends.hpcexplorer11.synchronization import DatabaseOptionsDialog, SynchronizationManagerSheet
from classicsync.gui.service import STATE_CONNECTED


def capture(window, name):
    window.Update()
    bitmap = wx.WindowDC(window).GetAsBitmap()
    if bitmap.IsOk():
        bitmap.SaveFile(str(out / f"{name}.png"), wx.BITMAP_TYPE_PNG)
        print("captured", name, bitmap.GetSize(), flush=True)


def menu_state(window, identifier):
    item = window.GetMenuBar().FindItemById(identifier)
    window.UpdateWindowUI()
    return f"{item.GetItemLabelText()} enabled={item.IsEnabled()}"


application = Application(False)
answer_partnership_prompts(create=True)
progress_captured = []


def frontend():
    return application.frontend


def window():
    return frontend().explorer_window


def wait_connected(attempts=[0]):
    attempts[0] += 1
    if application.service.state == STATE_CONNECTED and application.device_details and application.partnership:
        wx.CallLater(6000, connected)
    elif attempts[0] > 240:
        print("never connected", flush=True)
        application.quit()
    else:
        wx.CallLater(500, wait_connected)


def connected():
    print("status bar:", window().status_bar.GetStatusText(1), flush=True)
    print("menu:", menu_state(window(), ID_SYNCHRONIZE_NOW), "|", menu_state(window(), ID_SYNCHRONIZATION_MANAGER), flush=True)
    capture(window(), "main-before-sync")
    show_manager("manager", database_options)


def show_manager(prefix, then):
    sheet = SynchronizationManagerSheet(window(), frontend())
    sheet.Show()

    def general():
        capture(sheet, f"{prefix}-general")
        sheet.notebook.SetSelection(1)
        wx.CallLater(500, databases)

    def databases():
        capture(sheet, f"{prefix}-databases")
        list_control = sheet.databases.list
        print(prefix, "databases:", [(list_control.GetItemText(index, 0), list_control.GetItemText(index, 1))
                                     for index in range(list_control.GetItemCount())], flush=True)
        sheet.Destroy()
        then()
    wx.CallLater(600, general)


def database_options():
    object_type = next(object_type for object_type, _ in frontend().sync.object_types() if object_type.key == "files")
    dialog = DatabaseOptionsDialog(window(), object_type, True)
    dialog.Show()
    wx.CallLater(400, lambda: (capture(dialog, "database-options-files"), dialog.Destroy(), start_sync()))


def start_sync():
    application.sync.add_listener(on_sync)
    window().ProcessEvent(wx.CommandEvent(wx.wxEVT_MENU, ID_SYNCHRONIZE_NOW))
    print("running:", application.sync.running, flush=True)


def on_sync(kind, payload):
    if kind == EVENT_PROGRESS and payload.total and not progress_captured:
        progress_captured.append(True)

        def grab():
            dialog = frontend().sync_progress_dialog
            if dialog:
                capture(dialog, "progress")
            capture(window(), "main-syncing")
            print("status bar while syncing:", window().status_bar.GetStatusText(1), flush=True)
        wx.CallLater(100, grab)
    elif kind in (EVENT_FINISHED, EVENT_FAILED, EVENT_STOPPED):
        print("sync", kind, payload.summary() if kind == EVENT_FINISHED else payload, flush=True)
        if kind == EVENT_FINISHED:
            for line in payload.errors:
                print("  error:", line, flush=True)
        application.sync.remove_listener(on_sync)
        wx.CallLater(1500, after_sync)


def after_sync():
    print("status bar after:", window().status_bar.GetStatusText(1), flush=True)
    capture(window(), "main-after-sync")
    show_manager("manager-after", application.quit)


wx.CallLater(1500, wait_connected)
wx.CallLater(900000, application.quit)
application.MainLoop()
