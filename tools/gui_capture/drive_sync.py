import json
import os
import sys
from pathlib import Path

import wx

home = Path(os.environ["CLASSICSYNC_HOME"])
output = Path(sys.argv[2])
home.mkdir(parents=True, exist_ok=True)
(home / "settings.json").write_text(json.dumps({"serial_port": sys.argv[1], "language": os.environ.get("CLASSICSYNC_LANGUAGE", ""), "rapi_proxy": "127.0.0.1:19997",
                                                "frontend": os.environ.get("CLASSICSYNC_FRONTEND", "activesync31")}))

from classicsync.gui.app import Application
from partnership_prompts import answer_partnership_prompts
from classicsync.gui.common.sync_runner import EVENT_FAILED, EVENT_FINISHED, EVENT_PROGRESS
from classicsync.gui.service import STATE_CONNECTED


def capture(window, name):
    window.Update()
    bitmap = wx.WindowDC(window).GetAsBitmap()
    if bitmap.IsOk():
        bitmap.SaveFile(str(output / f"{name}.png"), wx.BITMAP_TYPE_PNG)
        print("captured", name, flush=True)


application = Application(False)
answer_partnership_prompts(create=True)
captured_progress = []


def on_sync(kind, payload):
    frontend = application.frontend
    window = getattr(frontend, "main_window", None) or getattr(frontend, "window", None)
    if kind == EVENT_PROGRESS and not captured_progress and payload.total:
        captured_progress.append(True)
        wx.CallLater(50, lambda: capture(window, "syncing"))
    elif kind in (EVENT_FINISHED, EVENT_FAILED):
        print("sync", kind, payload.summary() if kind == EVENT_FINISHED else payload, flush=True)
        wx.CallLater(800, lambda: (capture(window, "synchronized"), application.quit()))


def wait_connected(attempts=[0]):
    attempts[0] += 1
    if application.service.state == STATE_CONNECTED and application.device_details and application.partnership:
        wx.CallLater(500, show_options)
    elif attempts[0] > 120:
        print("never connected", flush=True)
        application.quit()
    else:
        wx.CallLater(500, wait_connected)


def show_options():
    from classicsync.gui.frontends.activesync31.options import OptionsSheet
    sheet = OptionsSheet(application.frontend.main_window, application.frontend)
    sheet.Show()
    notebook = sheet.pages[0].GetParent()

    def grab(index=0):
        notebook.SetSelection(index)
        wx.CallLater(300, lambda: (capture(sheet, f"options-{index}"), grab(index + 1) if index < 2 else finish()))

    def finish():
        sheet.Destroy()
        capture(application.frontend.main_window, "before-sync")
        application.sync.add_listener(on_sync)
        application.sync.start()

    wx.CallLater(500, grab)


wx.CallLater(1000, wait_connected)
wx.CallLater(150000, application.quit)
application.MainLoop()
