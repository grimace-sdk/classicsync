import json
import os
import sys
import wx
from pathlib import Path

home = Path(os.environ["CLASSICSYNC_HOME"])
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
home.mkdir(parents=True, exist_ok=True)
(home / "settings.json").write_text(json.dumps({"serial_port": sys.argv[1], "language": os.environ.get("CLASSICSYNC_LANGUAGE", ""), "rapi_proxy": "127.0.0.1:19991", "show_tray_icon": True, "frontend": os.environ.get("CLASSICSYNC_FRONTEND", "activesync31")}))

from classicsync.gui.app import Application
from partnership_prompts import answer_partnership_prompts
from classicsync.gui.service import STATE_CONNECTED

def capture(window, name):
    window.Update()
    dc = wx.WindowDC(window)
    bitmap = dc.GetAsBitmap()
    if bitmap.IsOk():
        bitmap.SaveFile(str(out / f"{name}.png"), wx.BITMAP_TYPE_PNG)
        print("captured", name, bitmap.GetSize())

app = Application(False)
answer_partnership_prompts(create=False)
steps = []

def wait_connected():
    if app.service.state == STATE_CONNECTED and app.device_details:
        wx.CallLater(500, connected)
    else:
        wx.CallLater(500, wait_connected)

def connected():
    capture(app.frontend.main_window, "main-connected")
    app.frontend.show_explore()
    wx.CallLater(6000, explored)

def explored():
    capture(app.frontend.explore_window, "explore-root")
    app.frontend.explore_window.browser.navigate("\\Windows")
    wx.CallLater(8000, explored_windows)

def explored_windows():
    capture(app.frontend.explore_window, "explore-windows")
    from classicsync.gui.common.device_browser import PropertiesDialog
    entry = app.frontend.explore_window.browser.entries_view[0]
    dialog = PropertiesDialog(app.frontend.explore_window, entry, "\\Windows")
    dialog.Show()
    wx.CallLater(800, lambda: (capture(dialog, "properties"), dialog.Destroy(), settings_dialog()))

def settings_dialog():
    def grab():
        capture(app.frontend.connection_dialog, "connection-settings")
        app.frontend.connection_dialog.EndModal(wx.ID_CANCEL)
        wx.CallLater(300, about)
    wx.CallLater(800, grab)
    app.frontend.show_connection_settings(app.frontend.main_window)

def about():
    from classicsync.gui.frontends.activesync31 import AboutDialog
    dialog = AboutDialog(app.frontend.main_window, app.frontend.artwork)
    dialog.Show()
    wx.CallLater(500, lambda: (capture(dialog, "about"), dialog.Destroy(), app.frontend.main_window.on_command(type("E", (), {"GetId": lambda self: 10024, "Skip": lambda self: None})()), wx.CallLater(800, simple)))

def simple():
    capture(app.frontend.main_window, "main-simple")
    app.frontend.main_window.on_command(type("E", (), {"GetId": lambda self: 10024, "Skip": lambda self: None})())
    wx.CallLater(300, app.quit)

def first():
    capture(app.frontend.main_window, "main-waiting")
    wait_connected()

wx.CallLater(1200, first)
wx.CallLater(120000, app.quit)
app.MainLoop()
