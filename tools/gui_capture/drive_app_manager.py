import json
import os
import sys
from pathlib import Path

import wx

home = Path(os.environ["CLASSICSYNC_HOME"])
output = Path(sys.argv[2])
home.mkdir(parents=True, exist_ok=True)
(home / "settings.json").write_text(json.dumps({"serial_port": sys.argv[1], "language": os.environ.get("CLASSICSYNC_LANGUAGE", ""), "rapi_proxy": "127.0.0.1:19996",
                                                "frontend": os.environ.get("CLASSICSYNC_FRONTEND", "activesync31")}))

from classicsync.gui.app import Application
from partnership_prompts import answer_partnership_prompts
from classicsync.gui.common.app_manager import AppManagerDialog, show_app_manager
from classicsync.gui.service import STATE_CONNECTED


def capture(window, name):
    window.Update()
    bitmap = wx.WindowDC(window).GetAsBitmap()
    if bitmap.IsOk():
        bitmap.SaveFile(str(output / f"{name}.png"), wx.BITMAP_TYPE_PNG)
        print("captured", name, flush=True)


application = Application(False)
answer_partnership_prompts(create=False)


def wait_connected(attempts=[0]):
    attempts[0] += 1
    if application.service.state == STATE_CONNECTED and application.device_details:
        wx.CallLater(500, open_dialog)
    elif attempts[0] > 120:
        print("never connected", flush=True)
        application.quit()
    else:
        wx.CallLater(500, wait_connected)


def open_dialog():
    def grab():
        dialog = next(window for window in wx.GetTopLevelWindows() if isinstance(window, AppManagerDialog))
        capture(dialog, "app-manager")
        dialog.EndModal(wx.ID_CANCEL)
    wx.CallLater(6000, grab)
    show_app_manager(None, application.frontend, paths=[path for path in os.environ.get("APP_PATHS", "").split(os.pathsep) if path])
    wx.CallLater(300, application.quit)


wx.CallLater(1000, wait_connected)
wx.CallLater(90000, application.quit)
application.MainLoop()
