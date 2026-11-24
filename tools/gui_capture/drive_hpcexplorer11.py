import json
import os
import sys
from pathlib import Path

import wx

home = Path(os.environ["CLASSICSYNC_HOME"])
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
home.mkdir(parents=True, exist_ok=True)
(home / "settings.json").write_text(json.dumps({"serial_port": sys.argv[1], "language": os.environ.get("CLASSICSYNC_LANGUAGE", ""), "rapi_proxy": "127.0.0.1:19994",
                                                "show_tray_icon": True, "frontend": "hpcexplorer11"}))

from classicsync.gui.app import Application
from partnership_prompts import answer_partnership_prompts
from classicsync.gui.frontends.hpcexplorer11 import AboutDialog, ConnectingDialog
from classicsync.gui.frontends.hpcexplorer11.browser import TransferProgressDialog
from classicsync.gui.frontends.hpcexplorer11.commands import ID_COPY, ID_DETAILS, ID_FOLDERS, ID_LIST, ID_PASTE, ID_SMALL_ICONS
from classicsync.gui.frontends.hpcexplorer11.options import OptionsSheet
from classicsync.gui.frontends.hpcexplorer11.properties import EntryPropertiesSheet
from classicsync.gui.service import STATE_CONNECTED


def capture(window, name):
    window.Update()
    bitmap = wx.WindowDC(window).GetAsBitmap()
    if bitmap.IsOk():
        bitmap.SaveFile(str(out / f"{name}.png"), wx.BITMAP_TYPE_PNG)
        print("captured", name, bitmap.GetSize())


def command(window, identifier):
    window.ProcessEvent(wx.CommandEvent(wx.wxEVT_MENU, identifier))


application = Application(False)
answer_partnership_prompts(create=False)


def frontend():
    return application.frontend


def window():
    return frontend().explorer_window


def first():
    capture(window(), "main-waiting")
    dialog = ConnectingDialog(frontend().artwork)
    dialog.Show()
    wx.CallLater(400, lambda: (capture(dialog, "connecting"), dialog.Destroy(), wait_connected()))


def wait_connected():
    if application.service.state == STATE_CONNECTED and application.device_details:
        wx.CallLater(6000, connected)
    else:
        wx.CallLater(500, wait_connected)


def connected():
    capture(window(), "main-root-large")
    tray_menu = frontend().tray.CreatePopupMenu() if frontend().tray else None
    if tray_menu:
        print("tray menu:", [item.GetItemLabel() for item in tray_menu.GetMenuItems()])
    window().browser.navigate("\\Windows")
    wx.CallLater(8000, windows_folder)


def windows_folder():
    command(window(), ID_DETAILS)
    wx.CallLater(800, lambda: (capture(window(), "main-windows-details"), properties()))


def properties():
    browser = window().browser
    file_entry = next(entry for entry in browser.entries_view if not entry.is_directory)
    folder_entry = next((entry for entry in browser.entries_view if entry.is_directory), None)
    sheet = EntryPropertiesSheet(window(), file_entry, browser.location_label(), frontend().artwork, lambda entry, attributes: None)
    sheet.Show()

    def folder_sheet():
        capture(sheet, "properties-file")
        sheet.Destroy()
        if folder_entry:
            other = EntryPropertiesSheet(window(), folder_entry, browser.location_label(), frontend().artwork)
            other.Show()
            wx.CallLater(500, lambda: (capture(other, "properties-folder"), other.Destroy(), options()))
        else:
            options()
    wx.CallLater(500, folder_sheet)


def options():
    sheet = OptionsSheet(window(), window().view_settings, lambda: None)
    sheet.Show()
    wx.CallLater(500, lambda: (capture(sheet, "options"), sheet.Destroy(), communications()))


def communications():
    def grab():
        capture(frontend().communications_sheet, "communications")
        frontend().communications_sheet.EndModal(wx.ID_CANCEL)
        wx.CallLater(300, about)
    wx.CallLater(800, grab)
    frontend().show_connection_settings(window())


def about():
    dialog = AboutDialog(window(), frontend().artwork)
    dialog.Show()
    wx.CallLater(500, lambda: (capture(dialog, "about"), dialog.Destroy(), progress()))


def progress():
    dialog = TransferProgressDialog(window(), frontend().artwork, 148, "Copying...")
    dialog.start()
    dialog.update(0.4, "Copying:  ctlpnl.exe", "From 'Windows' to 'Desktop'")
    wx.CallLater(900, lambda: (capture(dialog, "progress"), dialog.finish(), views()))


def views():
    command(window(), ID_SMALL_ICONS)
    wx.CallLater(600, lambda: (capture(window(), "main-small"), command(window(), ID_FOLDERS),
                               wx.CallLater(600, no_folders)))


def no_folders():
    command(window(), ID_LIST)
    wx.CallLater(600, lambda: (capture(window(), "main-list-no-folders"), command(window(), ID_FOLDERS),
                               command(window(), ID_DETAILS), wx.CallLater(300, copy_file)))


def copy_file():
    browser = window().browser
    index = next(index for index, entry in enumerate(browser.entries_view) if entry.name == "ab_add.htp")
    browser.list.Select(index)
    command(window(), ID_COPY)
    browser.navigate("\\My Documents")
    wx.CallLater(4000, paste_file)


def paste_file():
    command(window(), ID_PASTE)
    wx.CallLater(4000, upload_file)


def upload_file():
    sample = out / "upload-sample.txt"
    sample.write_text("classicsync upload test\n" * 200)
    window().browser.upload([str(sample)])
    wx.CallLater(5000, transferred)


def transferred():
    print("my documents:", [entry.name for entry in window().browser.entries_view])
    capture(window(), "main-after-transfers")
    close_communications()


def close_communications():
    frontend().close_communications()
    wx.CallLater(2000, lambda: (capture(window(), "main-closed"), application.quit()))


wx.CallLater(1500, first)
wx.CallLater(150000, application.quit)
application.MainLoop()
