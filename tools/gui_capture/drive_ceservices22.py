import json
import os
import sys
from pathlib import Path

import wx

home = Path(os.environ["CLASSICSYNC_HOME"])
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
home.mkdir(parents=True, exist_ok=True)
(home / "settings.json").write_text(json.dumps({"serial_port": sys.argv[1], "language": os.environ.get("CLASSICSYNC_LANGUAGE", ""), "rapi_proxy": "127.0.0.1:19992", "show_tray_icon": True,
                                                "frontend": "ceservices22"}))

from classicsync.gui.app import Application
from partnership_prompts import answer_partnership_prompts
from classicsync.gui.frontends.ceservices22 import AboutDialog
from classicsync.gui.frontends.ceservices22.device_properties import DevicePropertiesSheet
from classicsync.gui.frontends.ceservices22.get_connected import GetConnectedDialog
from classicsync.gui.frontends.ceservices22.properties import AutoConnectDialog, PropertiesSheet
from classicsync.gui.frontends.ceservices22.mobile_devices import ID_VIEW_DETAILS, ID_VIEW_LARGE
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
    event = wx.CommandEvent(wx.wxEVT_MENU, identifier)
    window.on_command(event)


def capture_dialog(dialog, name, then, delay=700):
    dialog.Show()

    def grab():
        capture(dialog, name)
        dialog.Destroy()
        then()
    wx.CallLater(delay, grab)


app = Application(False)
answer_partnership_prompts(create=False)
frontend = app.frontend


def window():
    return frontend.main_window


def step_waiting():
    command(window(), ID_VIEW_DETAILS)
    capture(window(), "mobile-devices-waiting")
    print("tray waiting:\n" + "\n".join(menu_labels(frontend.tray.CreatePopupMenu())), flush=True)
    sheet = PropertiesSheet(window(), frontend)
    capture_dialog(sheet, "properties-communications", step_preferences)


def step_preferences():
    sheet = PropertiesSheet(window(), frontend)
    sheet.select_page(1)
    capture_dialog(sheet, "properties-preferences", step_auto_connect)


def step_auto_connect():
    capture_dialog(AutoConnectDialog(window()), "auto-connect", step_get_connected_intro)


def step_get_connected_intro():
    capture_dialog(GetConnectedDialog(window(), frontend), "get-connected-intro", step_about, delay=1200)


def step_about():
    capture_dialog(AboutDialog(window(), frontend.artwork), "about", wait_connected)


def wait_connected():
    if app.service.state == STATE_CONNECTED and app.device_details:
        wx.CallLater(800, step_connected)
    else:
        wx.CallLater(500, wait_connected)


def step_connected():
    capture(window(), "mobile-devices-connected-details")
    print("tray connected:\n" + "\n".join(menu_labels(frontend.tray.CreatePopupMenu())), flush=True)
    print("menu bar:", flush=True)
    menu_bar = window().GetMenuBar()
    for index in range(menu_bar.GetMenuCount()):
        print(menu_bar.GetMenuLabelText(index))
        print("\n".join(menu_labels(menu_bar.GetMenu(index), "    ")), flush=True)
    command(window(), ID_VIEW_LARGE)
    window().device_list.Select(0)
    wx.CallLater(400, step_large)


def step_large():
    capture(window(), "mobile-devices-connected-large")
    print("device context:\n" + "\n".join(menu_labels(window()._device_context_menu())), flush=True)
    sheet = DevicePropertiesSheet(window(), frontend, app.service.announcement, window().rows[0]["name"])
    capture_dialog(sheet, "device-properties", step_open_device)


def step_open_device():
    window().open_device()
    wx.CallLater(6000, step_device_root)


def step_device_root():
    capture(window(), "device-root")
    window().browser.navigate("\\Windows")
    wx.CallLater(8000, step_device_windows)


def step_device_windows():
    capture(window(), "device-windows")
    print("history:", window().history, window().history_index, flush=True)
    window().go_up()
    wx.CallLater(4000, step_up_once)


def step_up_once():
    capture(window(), "device-up-root")
    window().go_up()
    wx.CallLater(800, step_back_at_devices)


def step_back_at_devices():
    capture(window(), "mobile-devices-after-up")
    frontend.show_sync_status()
    wx.CallLater(800, step_sync_status)


def step_sync_status():
    capture(frontend.sync_status_window, "sync-status")
    frontend.sync_status_window.Close()
    dialog = GetConnectedDialog(window(), frontend)
    dialog.Show()
    dialog.on_start(None)

    def progress():
        capture(dialog, "get-connected-scanning")
        wx.CallLater(20000, lambda: finish(dialog))
    wx.CallLater(3000, progress)


def finish(dialog):
    if dialog:
        capture(dialog, "get-connected-result")
        print("get connected:", repr(dialog.message.GetLabel()), "settings:", app.settings.serial_port, app.settings.last_baud, flush=True)
        dialog.on_cancel(None)
    wx.CallLater(1000, lambda: wait_reconnected(60))


def wait_reconnected(remaining):
    if app.service.state == STATE_CONNECTED or remaining <= 0:
        print("after get connected:", app.service.state, flush=True)
        capture(window(), "mobile-devices-after-get-connected")
        wx.CallLater(500, app.quit)
    else:
        wx.CallLater(1000, lambda: wait_reconnected(remaining - 1))


wx.CallLater(1500, step_waiting)
wx.CallLater(150000, app.quit)
app.MainLoop()
