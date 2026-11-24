import faulthandler
import json
import os
import sys
from pathlib import Path

import wx

home = Path(os.environ["CLASSICSYNC_HOME"])
output = Path(sys.argv[2])
home.mkdir(parents=True, exist_ok=True)
(home / "settings.json").write_text(json.dumps({"serial_port": sys.argv[1], "language": os.environ.get("CLASSICSYNC_LANGUAGE", ""), "serial_enabled": True, "rapi_proxy": "127.0.0.1:19992",
                                                "frontend": "activesync31"}))

from classicsync.gui.app import Application
from partnership_prompts import answer_partnership_prompts
from classicsync.gui.frontends.activesync31.get_connected import GetConnectedWizard, show_get_connected
from classicsync.gui.service import STATE_CONNECTED


def capture(window, name):
    window.Update()
    bitmap = wx.WindowDC(window).GetAsBitmap()
    if bitmap.IsOk():
        bitmap.SaveFile(str(output / f"{name}.png"), wx.BITMAP_TYPE_PNG)
        print("captured", name)


def wizard():
    return next(window for window in wx.GetTopLevelWindows() if isinstance(window, GetConnectedWizard))


faulthandler.dump_traceback_later(45, exit=False)
application = Application(False)
answer_partnership_prompts(create=False)
frontend = application.frontend


def open_wizard():
    wx.CallLater(800, welcome)
    result = show_get_connected(frontend.main_window, frontend)
    print("wizard result", result, application.settings.serial_port)
    wx.CallLater(500, wait_connected)


def welcome():
    capture(wizard(), "get-connected-welcome")
    wizard().start_scan()
    wx.CallLater(1500, lambda: capture(wizard(), "get-connected-progress") if any(isinstance(window, GetConnectedWizard) for window in wx.GetTopLevelWindows()) else None)


def wait_connected(attempts=[0]):
    attempts[0] += 1
    if application.service.state == STATE_CONNECTED:
        print("reconnected after wizard")
        capture(frontend.main_window, "main-after-get-connected")
        wx.CallLater(300, application.quit)
    elif attempts[0] > 120:
        print("never reconnected", application.service.state)
        application.quit()
    else:
        wx.CallLater(500, wait_connected)


wx.CallLater(1500, open_wizard)
wx.CallLater(60000, application.quit)
application.MainLoop()
