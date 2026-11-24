import hashlib
import json
import os
import sys
from pathlib import Path

import wx

home = Path(os.environ["CLASSICSYNC_HOME"])
output = Path(sys.argv[2])
output.mkdir(parents=True, exist_ok=True)
home.mkdir(parents=True, exist_ok=True)
FRONTEND = os.environ.get("CLASSICSYNC_FRONTEND", "activesync31")
(home / "settings.json").write_text(json.dumps({"serial_port": sys.argv[1], "language": os.environ.get("CLASSICSYNC_LANGUAGE", ""),
                                                "rapi_proxy": "127.0.0.1:19985", "show_tray_icon": True, "frontend": FRONTEND}))

from classicsync.gui.app import Application
from partnership_prompts import answer_partnership_prompts
from classicsync.gui.common.backup import BackupSettings
from classicsync.gui.common.backup_dialogs import (
    BackupProgressDialog, ConfirmCancelDialog, ConfirmDialog, FilesNotCopiedDialog, MessageDialog, PartnershipSelectionDialog,
    ProceedRestoreDialog,
)
from classicsync.gui.service import STATE_CONNECTED

TEST_FILE = "\\My Documents\\gui-backup.txt"
SHEETS = {
    "activesync31": "classicsync.gui.frontends.activesync31.backup",
    "ceservices22": "classicsync.gui.frontends.ceservices22.backup",
    "hpcexplorer11": "classicsync.gui.frontends.hpcexplorer11.backup",
}

application = Application(False)
answer_partnership_prompts(create=True, skip_backup=False)
seen = []
names = {}
state = {"cancel_next_backup": False, "progress_captured": set()}


def capture(window, name):
    window.Update()
    bitmap = wx.WindowDC(window).GetAsBitmap()
    if bitmap.IsOk():
        bitmap.SaveFile(str(output / f"{name}.png"), wx.BITMAP_TYPE_PNG)
        print("captured", name, bitmap.GetSize(), flush=True)


def unique(name):
    names[name] = names.get(name, 0) + 1
    return name if names[name] == 1 else f"{name}-{names[name]}"


def slug(text):
    return "".join(character if character.isalnum() else "-" for character in text.lower()).strip("-")[:40]


def handle(window):
    title = window.GetTitle()
    if isinstance(window, BackupProgressDialog):
        stage = "cancel" if state["cancel_next_backup"] else title
        if stage not in state["progress_captured"]:
            state["progress_captured"].add(stage)
            wx.CallLater(2500, lambda: window and capture(window, unique("progress-" + slug(title))))
        if state["cancel_next_backup"]:
            state["cancel_next_backup"] = False
            wx.CallLater(3000, lambda: window and window.on_cancel(None))
        return
    name = unique(slug(type(window).__name__ + "-" + title))
    if isinstance(window, MessageDialog):
        answer = wx.ID_NO if window.FindWindow(wx.ID_NO) else wx.ID_OK
        print("message:", title, flush=True)
    elif isinstance(window, ConfirmCancelDialog):
        answer = wx.ID_CANCEL
    elif isinstance(window, (ConfirmDialog, ProceedRestoreDialog)):
        answer = wx.ID_OK
    elif isinstance(window, FilesNotCopiedDialog):
        answer = wx.ID_IGNORE
    elif isinstance(window, PartnershipSelectionDialog):
        window.list.SetSelection(0)
        answer = None
    elif type(window).__name__ == "BackupNotCompleteDialog":
        answer = wx.ID_CANCEL
    else:
        return

    def respond():
        if not window:
            return
        capture(window, name)
        if answer is None:
            window.on_ok(None)
        else:
            window.EndModal(answer)
    wx.CallLater(700, respond)


def poll():
    for window in wx.GetTopLevelWindows():
        if window.IsShown() and not any(window is known for known in seen):
            seen.append(window)
            handle(window)
    wx.CallLater(200, poll)


def run(operation, then):
    def finished(result, error):
        if error:
            print("device operation failed:", error, flush=True)
        then(result)
    application.run_on_device(operation, finished)


def write_test_file(text, then):
    async def write(client):
        await client.write_file_contents(TEST_FILE, text.encode())
    run(write, lambda result: then())


def read_test_file(then):
    async def read(client):
        return await client.read_file_contents(TEST_FILE)
    run(read, then)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def wait_until(condition, then, attempts=600):
    if condition():
        wx.CallLater(500, then)
    elif attempts <= 0:
        print("timed out", flush=True)
        application.quit()
    else:
        wx.CallLater(500, lambda: wait_until(condition, then, attempts - 1))


def idle():
    return not application.sync.running and not application.backup.running and not any(
        isinstance(window, wx.Dialog) and window.IsModal() for window in wx.GetTopLevelWindows())


def sheet_module():
    import importlib
    return importlib.import_module(SHEETS[FRONTEND])


def parent_window():
    frontend = application.frontend
    return getattr(frontend, "main_window", None) or getattr(frontend, "explorer_window", None)


def connected():
    print("partnership", application.partnership, flush=True)
    write_test_file("original\r\n", open_sheet)


def open_sheet():
    module = sheet_module()
    sheet = module.BackupRestoreSheet(parent_window(), application.frontend)
    sheet.Show()
    state["sheet"] = sheet
    notebook = sheet.backup_page.GetParent()

    def grab_restore_page():
        notebook.SetSelection(1)
        wx.CallLater(400, lambda: (capture(sheet, "sheet-restore"), notebook.SetSelection(0), wx.CallLater(300, back_up)))
    wx.CallLater(800, lambda: (capture(sheet, "sheet-backup"), grab_restore_page()))


def back_up():
    sheet = state["sheet"]
    sheet.backup_page.full.SetValue(True)
    sheet.back_up_now()
    wait_until(idle, after_backup)


def after_backup():
    path = BackupSettings.load(application.partnership).path
    state["digest"] = digest(path)
    print("backup file", path, path.stat().st_size if path.exists() else None, flush=True)
    state["cancel_next_backup"] = True
    sheet = state["sheet"]
    sheet.backup_page.incremental.SetValue(True)
    sheet.back_up_now()
    wait_until(idle, after_cancel)


def after_cancel():
    path = BackupSettings.load(application.partnership).path
    print("backup file unchanged after cancel:", digest(path) == state["digest"], flush=True)
    write_test_file("changed\r\n", restore)


def restore():
    state["sheet"].restore_now()
    wait_until(idle, after_restore, attempts=1800)


def after_restore():
    def show(contents):
        print("test file after restore:", contents, flush=True)
        state["sheet"].Destroy()
        wx.CallLater(500, application.quit)
    read_test_file(show)


wx.CallLater(200, poll)
wait_until(lambda: application.service.state == STATE_CONNECTED and application.device_details and application.partnership
           and idle(), connected, attempts=900)
wx.CallLater(3000000, application.quit)
application.MainLoop()
