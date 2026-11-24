from dataclasses import dataclass
from pathlib import Path

import wx

from ...install import DesktopAppRecords, InstallError, list_installed_apps, read_device_profile, select_package, uninstall_app
from ...install.installer import copy_cab, ensure_wceload_shortcut, refuse_hpc1, run_wceload
from ...rapi.client import RapiError
from ..service import STATE_CONNECTED
from ...i18n import N_, _, format_original
from .layout import dialog_size, place

TITLE = N_("Add/Remove Programs")
SIZE_FORMAT = N_("%s K")
REMOVE_TITLE = N_("Remove Application")
REMOVE_PROMPT = N_("This will remove the application \"%s\" from your mobile device and this desktop computer.\n\n"
                   "If you need this application in the future, you will have to reinstall it.")
REMOVING_TITLE = N_("Removing Applications")
REMOVING_STATUS = N_("Removing %s...")
INSTALLING_TITLE = N_("Installing Applications")
INSTALLING_STATUS = N_("Installing %s...")
CANCEL_TITLE = N_("Cancel Application Installation")
CANCEL_PROMPT = N_("Applications installed in this session will be automatically removed if you choose to cancel Setup now.\n\n"
                   "Do you want to continue with Setup?")
FAILED_TITLE = N_("Failed to Install Application")
NO_SPACE_TITLE = N_("Not Enough Space On Device")
NO_SPACE_PROMPT = N_("There is not enough space on the mobile device.\n\n   Required:\t%1\n   Available:\t%2\n\nDo you want to continue anyway?")
NOT_CONNECTED_TITLE = N_("Device Not Connected")
NOT_CONNECTED_TEXT = N_("Application Manager can run only when a mobile device is connected.")
DISCONNECTED_TITLE = N_("Device Disconnected")
DISCONNECTED_TEXT = N_("The mobile device is no longer connected.  Please connect the device and run Application Manager again.")
RETRIEVING_TEXT = N_("Retrieving application data from the mobile device...")
NO_PROGRAMS_TEXT = N_("There are no device-compatible programs available.")
UNKNOWN_DEVICE_TITLE = N_("Device Information Unknown")
UNKNOWN_DEVICE_TEXT = N_("Unable to retrieve the mobile device information.  Please reconnect and try again.")
INITIALIZING_TEXT = N_("Initializing...")
HPC1_TITLE = N_("Handheld PC 1.0 Device Connected")
HPC1_TEXT = N_("Application Manager cannot install applications on a Handheld PC 1.0 device.")
COMPLETE_TITLE = N_("Application Downloading Complete")
COMPLETE_TEXT = N_("Please check your mobile device screen to see if additional steps are necessary to complete this installation.")
UNAVAILABLE = N_("<unavailable>")
INTRODUCTION = N_("Select a program's check box if you want to install it on your mobile device, "
                  "or clear the check box if you want to remove the program from your device.")
NOTE = N_("Note:  If a program that you installed is not listed, the program was not designed to be used on your mobile device.")
DESCRIPTION_LABEL = N_("Program description")
REQUIRED_LABEL = N_("Space required for selected programs:")
AVAILABLE_LABEL = N_("Space available on device:")
DEFAULT_FOLDER_LABEL = N_("&Install program into the default installation folder")
REMOVE_GROUP_LABEL = N_("Remove from both locations")
REMOVE_TEXT = N_("To remove the selected program from both your device and this computer, click Remove.")
HELP_TEXT = N_("Programs listed here were added to this computer from a CeAppMgr .ini or a Windows CE .cab file. "
               "Checked programs are installed on the device: check one to install it, clear one to remove it, then click OK. "
               "Drop a .ini or .cab file on the list to add a program.")

PROGRESS_STEPS = 1000


def format_kilobytes(size):
    return format_original(_(SIZE_FORMAT), f"{size / 1024:,.1f}")


@dataclass
class ProgramRow:
    name: str
    description: str
    record: object = None
    package: object = None
    installed_name: str = ""

    @property
    def installed(self):
        return bool(self.installed_name)

    @property
    def size(self):
        return self.package.installed_size if self.package else 0


class ProgressDialog(wx.Dialog):
    def __init__(self, parent, title):
        super().__init__(parent, title=title, style=wx.CAPTION)
        self.SetClientSize(dialog_size(self, 216, 63))
        self.status = place(self, wx.StaticText, 7, 6, 202, 11, _(INITIALIZING_TEXT), style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
        self.gauge = place(self, wx.Gauge, 7, 22, 202, 14, PROGRESS_STEPS)
        place(self, wx.Button, 82, 42, 50, 14, _("Cancel"), id=wx.ID_CANCEL)
        self.cancelled = False
        self.Bind(wx.EVT_BUTTON, self.on_cancel, id=wx.ID_CANCEL)
        self.CentreOnParent()

    def on_cancel(self, event):
        if wx.MessageBox(_(CANCEL_PROMPT), _(CANCEL_TITLE), wx.YES_NO | wx.ICON_QUESTION, self) == wx.NO:
            self.cancelled = True

    def update(self, title, status, fraction):
        if not self:
            return
        self.SetTitle(title)
        self.status.SetLabel(status)
        self.gauge.SetValue(max(0, min(PROGRESS_STEPS, int(fraction * PROGRESS_STEPS))))


class FileDrop(wx.FileDropTarget):
    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog

    def OnDropFiles(self, x, y, filenames):
        wx.CallAfter(self.dialog.add_files, filenames)
        return True


class AppManagerDialog(wx.Dialog):
    def __init__(self, parent, application, title=None, records=None):
        super().__init__(parent, title=title or _(TITLE))
        self.application = application
        self.service = application.service
        self.records = records or DesktopAppRecords()
        self.rows = []
        self.profile = None
        self.free_space = None
        self.filling = False
        self.SetClientSize(dialog_size(self, 221, 259))

        place(self, wx.StaticText, 7, 7, 207, 25, _(INTRODUCTION))
        place(self, wx.StaticText, 7, 36, 207, 17, _(NOTE))
        self.list = place(self, wx.ListCtrl, 7, 56, 207, 55,
                          style=wx.LC_REPORT | wx.LC_NO_HEADER | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN)
        self.list.EnableCheckBoxes(True)
        self.list.InsertColumn(0, _("Name"))
        self.list.InsertColumn(1, _("Size"), wx.LIST_FORMAT_RIGHT)
        list_width = self.list.GetClientSize().width
        self.list.SetColumnWidth(0, list_width * 7 // 10)
        self.list.SetColumnWidth(1, list_width - list_width * 7 // 10 - 4)
        self.list.SetDropTarget(FileDrop(self))
        place(self, wx.StaticBox, 7, 114, 207, 41, _(DESCRIPTION_LABEL))
        self.description = place(self, wx.StaticText, 13, 125, 195, 27, _(RETRIEVING_TEXT), style=wx.ST_NO_AUTORESIZE)
        place(self, wx.StaticText, 10, 159, 130, 8, _(REQUIRED_LABEL))
        self.required = place(self, wx.StaticText, 147, 159, 47, 8, format_kilobytes(0), style=wx.ALIGN_RIGHT | wx.ST_NO_AUTORESIZE)
        place(self, wx.StaticText, 10, 169, 130, 9, _(AVAILABLE_LABEL))
        self.available = place(self, wx.StaticText, 147, 169, 47, 9, "", style=wx.ALIGN_RIGHT | wx.ST_NO_AUTORESIZE)
        self.default_folder = place(self, wx.CheckBox, 13, 180, 197, 15, _(DEFAULT_FOLDER_LABEL))
        self.default_folder.SetValue(True)
        place(self, wx.StaticBox, 7, 199, 207, 34, _(REMOVE_GROUP_LABEL))
        place(self, wx.StaticText, 13, 210, 144, 17, _(REMOVE_TEXT))
        self.remove_button = place(self, wx.Button, 162, 212, 48, 14, _("&Remove..."))
        self.ok_button = place(self, wx.Button, 49, 238, 50, 14, _("OK"), id=wx.ID_OK)
        self.ok_button.SetDefault()
        place(self, wx.Button, 105, 238, 50, 14, _("Cancel"), id=wx.ID_CANCEL)
        help_button = place(self, wx.Button, 161, 238, 53, 14, _("&Help"))

        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_selected)
        self.list.Bind(wx.EVT_LIST_ITEM_CHECKED, self.on_checked)
        self.list.Bind(wx.EVT_LIST_ITEM_UNCHECKED, self.on_checked)
        self.remove_button.Bind(wx.EVT_BUTTON, self.on_remove)
        self.ok_button.Bind(wx.EVT_BUTTON, self.on_ok)
        help_button.Bind(wx.EVT_BUTTON, lambda event: wx.MessageBox(_(HELP_TEXT), self.GetTitle(), wx.OK | wx.ICON_INFORMATION, self))
        self.set_busy(True)
        self.CentreOnParent()

    def set_busy(self, busy):
        for control in (self.list, self.remove_button, self.ok_button, self.default_folder):
            control.Enable(not busy)

    def run(self, operation, on_success, on_error=None):
        def finished(future):
            error = future.exception()
            if error:
                wx.CallAfter(on_error or self.show_error, error)
            else:
                wx.CallAfter(on_success, future.result())
        self.service.submit(self.service.with_rapi(operation)).add_done_callback(finished)

    def show_error(self, error):
        if not self:
            return
        if isinstance(error, ConnectionError):
            wx.MessageBox(_(DISCONNECTED_TEXT), _(DISCONNECTED_TITLE), wx.OK | wx.ICON_WARNING, self)
            self.EndModal(wx.ID_CANCEL)
            return
        wx.MessageBox(str(error), self.GetTitle(), wx.OK | wx.ICON_WARNING, self)
        self.set_busy(False)

    def load(self):
        async def read(client):
            profile = await read_device_profile(client)
            installed = await list_installed_apps(client)
            try:
                store = await client.get_store_information()
            except RapiError:
                store = None
            return profile, installed, store

        def failed(error):
            if not self:
                return
            if isinstance(error, ConnectionError):
                self.show_error(error)
                return
            wx.MessageBox(_(UNKNOWN_DEVICE_TEXT), _(UNKNOWN_DEVICE_TITLE), wx.OK | wx.ICON_WARNING, self)
            self.EndModal(wx.ID_CANCEL)

        self.run(read, self.loaded, failed)

    def loaded(self, result):
        if not self:
            return
        self.profile, installed, store = result
        try:
            refuse_hpc1(self.profile)
        except InstallError:
            wx.MessageBox(_(HPC1_TEXT), _(HPC1_TITLE), wx.OK | wx.ICON_WARNING, self)
            self.EndModal(wx.ID_CANCEL)
            return
        self.free_space = store.free_size if store else None
        self.available.SetLabel(format_kilobytes(self.free_space) if self.free_space is not None else _(UNAVAILABLE))
        self.rows = self.build_rows(installed)
        self.fill()
        self.set_busy(False)

    def build_rows(self, installed):
        installed_by_name = {app.name.lower(): app for app in installed}
        rows = []
        for record in self.records.all():
            component = record.to_component()
            try:
                package = select_package(component.packages(), self.profile)
            except (InstallError, OSError):
                package = None
            names = [record.uninstall, package.uninstall_name if package else "", record.name]
            installed_app = next((installed_by_name.pop(name.lower()) for name in names if name and name.lower() in installed_by_name), None)
            if package is None and installed_app is None:
                continue
            rows.append(ProgramRow(record.name, record.description, record, package, installed_app.name if installed_app else ""))
        for app in installed_by_name.values():
            rows.append(ProgramRow(app.name, app.install_directory, installed_name=app.name))
        return sorted(rows, key=lambda row: row.name.lower())

    def fill(self):
        self.filling = True
        self.list.DeleteAllItems()
        for index, row in enumerate(self.rows):
            self.list.InsertItem(index, row.name)
            self.list.SetItem(index, 1, format_kilobytes(row.size) if row.package else "")
            self.list.CheckItem(index, row.installed)
        self.filling = False
        if self.rows:
            self.list.Select(0)
        else:
            self.description.SetLabel(NO_PROGRAMS_TEXT)
        self.update_required()

    def checked_rows(self):
        return [(row, self.list.IsItemChecked(index)) for index, row in enumerate(self.rows)]

    def update_required(self):
        required = sum(row.size for row, checked in self.checked_rows() if checked and not row.installed)
        self.required.SetLabel(format_kilobytes(required))
        return required

    def on_selected(self, event):
        row = self.rows[event.GetIndex()]
        self.description.SetLabel(row.description or row.name)
        self.description.Wrap(self.description.GetSize().width)

    def on_checked(self, event):
        if not self.filling:
            self.update_required()

    def selected_row(self):
        index = self.list.GetFirstSelected()
        return self.rows[index] if index >= 0 else None

    def add_files(self, paths):
        problems = []
        for path in paths:
            try:
                self.records.add_file(Path(path))
            except (InstallError, OSError) as error:
                problems.append(str(error))
        if problems:
            wx.MessageBox("\n".join(problems), self.GetTitle(), wx.OK | wx.ICON_WARNING, self)
        self.set_busy(True)
        self.load()

    def on_remove(self, event):
        row = self.selected_row()
        if row is None:
            return
        if wx.MessageBox(format_original(_(REMOVE_PROMPT), row.name), _(REMOVE_TITLE), wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            return
        if row.record:
            self.records.remove(row.record.name)
        if not row.installed:
            self.rows.remove(row)
            self.fill()
            return
        self.apply([], [row], close=False)

    def on_ok(self, event):
        to_install = [row for row, checked in self.checked_rows() if checked and not row.installed and row.package]
        to_remove = [row for row, checked in self.checked_rows() if not checked and row.installed]
        if not to_install and not to_remove:
            self.EndModal(wx.ID_OK)
            return
        required = self.update_required()
        if self.free_space is not None and required > self.free_space:
            prompt = format_original(_(NO_SPACE_PROMPT), format_kilobytes(required), format_kilobytes(self.free_space))
            if wx.MessageBox(prompt, _(NO_SPACE_TITLE), wx.YES_NO | wx.ICON_WARNING, self) != wx.YES:
                return
        self.apply(to_install, to_remove, close=True)

    def apply(self, to_install, to_remove, close):
        progress = ProgressDialog(self, _(INSTALLING_TITLE) if to_install else _(REMOVING_TITLE))
        progress.Show()
        self.set_busy(True)
        default_folder = self.default_folder.GetValue()
        total_bytes = sum(row.package.size for row in to_install) or 1

        def report(title, status, fraction):
            wx.CallAfter(progress.update, title, status, fraction)
            if progress.cancelled:
                raise InterruptedError("cancelled")

        async def change(client):
            for index, row in enumerate(to_remove):
                report(_(REMOVING_TITLE), format_original(_(REMOVING_STATUS), row.name), index / len(to_remove))
                await uninstall_app(client, row.installed_name)
            copied = 0
            for row in to_install:
                status = format_original(_(INSTALLING_STATUS), row.name)
                report(_(INSTALLING_TITLE), status, copied / total_bytes)
                await copy_cab(client, row.package, lambda written, total, base=copied, status=status:
                               report(_(INSTALLING_TITLE), status, (base + written) / total_bytes))
                copied += row.package.size
            if to_install:
                await ensure_wceload_shortcut(client)
                await run_wceload(client, default_folder)
            return bool(to_install)

        def finished(installed_any):
            progress.Destroy()
            if not self:
                return
            if installed_any:
                wx.MessageBox(_(COMPLETE_TEXT), _(COMPLETE_TITLE), wx.OK | wx.ICON_INFORMATION, self)
            if close:
                self.EndModal(wx.ID_OK)
            else:
                self.load()

        def failed(error):
            progress.Destroy()
            if not self:
                return
            if isinstance(error, InterruptedError):
                self.load()
                return
            if isinstance(error, ConnectionError):
                self.show_error(error)
                return
            wx.MessageBox(str(error), _(FAILED_TITLE), wx.OK | wx.ICON_WARNING, self)
            self.load()

        self.run(change, finished, failed)


def show_app_manager(parent, application, paths=(), title=None):
    title = title or _(TITLE)
    if application.service.state != STATE_CONNECTED:
        wx.MessageBox(_(NOT_CONNECTED_TEXT), _(NOT_CONNECTED_TITLE), wx.OK | wx.ICON_WARNING, parent)
        return
    records = DesktopAppRecords()
    problems = []
    for path in paths:
        try:
            records.add_file(Path(path))
        except (InstallError, OSError) as error:
            problems.append(str(error))
    if problems:
        wx.MessageBox("\n".join(problems), title, wx.OK | wx.ICON_WARNING, parent)
    with AppManagerDialog(parent, application, title, records) as dialog:
        dialog.load()
        dialog.ShowModal()
