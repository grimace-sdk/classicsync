import json
import os
import sys
from pathlib import Path

import wx

home = Path(os.environ["CLASSICSYNC_HOME"])
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
home.mkdir(parents=True, exist_ok=True)
frontend_key = os.environ.get("CLASSICSYNC_FRONTEND", "hpcexplorer11")
folder = os.environ.get("CLASSICSYNC_CAPTURE_FOLDER", "\\My Documents\\Samples")
(home / "settings.json").write_text(json.dumps({"serial_port": sys.argv[1], "language": os.environ.get("CLASSICSYNC_LANGUAGE", ""),
                                                "rapi_proxy": "127.0.0.1:19995", "show_tray_icon": False, "frontend": frontend_key}))

from classicsync.gui.app import Application
from partnership_prompts import answer_partnership_prompts
from classicsync.gui.service import STATE_CONNECTED

application = Application(False)
answer_partnership_prompts(create=False)


def capture(window, name):
    window.Update()
    bitmap = wx.WindowDC(window).GetAsBitmap()
    if bitmap.IsOk():
        bitmap.SaveFile(str(out / f"{name}.png"), wx.BITMAP_TYPE_PNG)
        print("captured", name, bitmap.GetSize())


def command(window, identifier):
    window.ProcessEvent(wx.CommandEvent(wx.wxEVT_MENU, identifier))


def frontend():
    return application.frontend


def window():
    if frontend_key == "hpcexplorer11":
        return frontend().explorer_window
    return frontend().main_window


def browser():
    return window().browser


def wait_connected():
    if application.service.state == STATE_CONNECTED and application.device_details:
        wx.CallLater(5000, connected)
    else:
        wx.CallLater(500, wait_connected)


def connected():
    target = window()
    target.SetSize(wx.Size(640, 420))
    if frontend_key == "hpcexplorer11":
        browser_ready()
        return
    from classicsync.gui.frontends.ceservices22.mobile_devices import ID_VIEW_LARGE
    command(target, ID_VIEW_LARGE)
    wx.CallLater(800, lambda: (capture(target, "devices-large"), target.open_device(), wx.CallLater(8000, browser_ready)))


def browser_ready():
    browser().navigate(folder)
    wx.CallLater(2000, wait_for_folder)


def wait_for_folder(attempts=40):
    status_bar = window().GetStatusBar()
    reading = bool(status_bar) and "Reading" in status_bar.GetStatusText(0)
    if attempts and (not browser().entries or reading):
        wx.CallLater(1000, lambda: wait_for_folder(attempts - 1))
    else:
        wx.CallLater(1000, show_views)


def view_commands():
    if frontend_key == "hpcexplorer11":
        from classicsync.gui.frontends.hpcexplorer11.commands import ID_DETAILS, ID_LARGE_ICONS, ID_SMALL_ICONS
        return [(ID_LARGE_ICONS, "large"), (ID_SMALL_ICONS, "small"), (ID_DETAILS, "details")]
    from classicsync.gui.frontends.ceservices22.mobile_devices import ID_VIEW_DETAILS, ID_VIEW_LARGE, ID_VIEW_SMALL
    return [(ID_VIEW_LARGE, "large"), (ID_VIEW_SMALL, "small"), (ID_VIEW_DETAILS, "details")]


def show_views(remaining=None):
    if remaining is None:
        print("entries:", [entry.name for entry in browser().entries_view])
        remaining = view_commands()
    if not remaining:
        select_and_narrow()
        return
    identifier, name = remaining[0]
    command(window(), identifier)
    wx.CallLater(800, lambda: (capture(window(), f"{frontend_key}-{name}"), show_views(remaining[1:])))


def select_and_narrow():
    identifier = view_commands()[0][0]
    command(window(), identifier)
    if browser().list.GetItemCount() > 1:
        browser().list.Select(1)
    window().SetSize(wx.Size(420, 360))
    wx.CallLater(800, lambda: (capture(window(), f"{frontend_key}-large-narrow-selected"), application.quit()))


wx.CallLater(1500, wait_connected)
wx.CallLater(120000, application.quit)
application.MainLoop()
