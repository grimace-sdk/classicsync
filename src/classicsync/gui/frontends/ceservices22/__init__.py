import wx

from .... import __version__
from ....i18n import N_, _
from ...branding import PRODUCT_NAME, about_headline, authentic, disclaimer, rebrand, style_name, title
from ...common.layout import dialog_size, place
from ...common.sync_runner import EVENT_FAILED, EVENT_FINISHED, EVENT_PROGRESS, EVENT_STARTED, EVENT_STOPPED
from ...service import STATE_CONNECTED
from ..base import Frontend
from .activesync import (
    ActiveSyncOptionsSheet, SyncDisplaySettings, SynchronizationProgressDialog, device_status_text, partnership_status,
)
from .artwork import CeServicesArtwork
from .device_properties import DevicePropertiesSheet
from .get_connected import GetConnectedDialog
from .mobile_devices import MobileDevicesWindow
from .properties import PropertiesSheet
from .sync_status import SyncStatusWindow
from .tray import TrayIcon

TITLE = title("ceservices22")
VERSION_ONE_FRONTEND = "hpcexplorer11"
SYNC_MANAGER_MODULE = "SyncMgr.exe"
COMBINE_INTRO = N_("Some mobile device items already exist on your mobile device. You can keep this data, or discard and replace "
                   "it with the items on your desktop computer. Please choose one of the following options to select what you "
                   "want to do with the items currently on your mobile device.")
PARTNERSHIP_FAILED = N_("Failed to setup the partnership between this device and the desktop computer. Establishing a Guest "
                        "connection.")
FRONTEND_KEY = "ceservices22"


class AboutDialog(wx.Dialog):
    def __init__(self, parent, artwork):
        super().__init__(parent, title=rebrand(_("About Microsoft Windows CE Services"), FRONTEND_KEY))
        self.SetClientSize(dialog_size(self, 289, 179))
        wx.StaticBitmap(self, bitmap=artwork.mobile_devices_bitmap(32), pos=self.ConvertDialogToPixels(wx.Point(8, 11)))
        place(self, wx.StaticText, 53, 11, 192, 10, about_headline(FRONTEND_KEY, __version__),
              style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
        place(self, wx.StaticText, 53, 21, 192, 10, f"{PRODUCT_NAME} {__version__}" if authentic() else "")
        place(self, wx.StaticText, 53, 37, 230, 20,
              _("Desktop connectivity for Windows CE 1.x, 2.x and 3.x devices on Linux, macOS and Windows."))
        place(self, wx.StaticBox, 44, 58, 238, 39, "")
        place(self, wx.StaticText, 53, 68, 214, 24,
              _("A recreation of the {style} desktop software.").format(style=style_name(FRONTEND_KEY)))
        place(self, wx.StaticLine, 8, 114, 274, 1)
        place(self, wx.StaticText, 9, 120, 184, 50, disclaimer())
        place(self, wx.Button, 206, 130, 76, 16, _("OK"), id=wx.ID_OK).SetDefault()
        self.CentreOnParent()


class CeServicesFrontend(Frontend):
    key = FRONTEND_KEY
    title = TITLE
    device_versions = (2,)

    def __init__(self, application):
        super().__init__(application)
        self.artwork = CeServicesArtwork()
        self.main_window = None
        self.sync_status_window = None
        self.properties_sheet = None
        self.get_connected_dialog = None
        self.sync_display = SyncDisplaySettings.load()
        self.sync_failed = False
        self.sync_progress_dialog = None
        self.first_sync_answer = None
        self.device_prompt_open = False

    def start(self, initial=False):
        self.apply_tray_setting()
        if initial or not self.tray or (self.service.state == STATE_CONNECTED and self.settings.open_on_connect):
            self.show_main_window()
        if initial and not self.settings.serial_port:
            wx.CallAfter(self.show_get_connected, self.main_window)

    def stop(self):
        super().stop()
        self._close_sync_progress()
        for window in (self.sync_status_window, self.main_window):
            if window:
                try:
                    window.Destroy()
                except RuntimeError:
                    pass
        self.sync_status_window = None
        self.main_window = None

    def apply_tray_setting(self):
        if self.tray_available():
            if not self.tray:
                self.tray = TrayIcon(self)
            self.tray.update_state(self.service.state)
        elif self.tray:
            super().stop()

    def on_state(self, state, announcement, error):
        self.play_transition_sound(state)
        if state == STATE_CONNECTED and self.settings.open_on_connect and not self.version_one_connected():
            self.show_main_window()
        if self.tray:
            self.tray.update_state(state)
        for window in (self.main_window, self.sync_status_window, self.properties_sheet):
            if not window:
                continue
            try:
                if window is self.main_window:
                    window.update_state(state, announcement)
                else:
                    window.update_state(state)
            except RuntimeError:
                pass

    def on_details(self, announcement):
        if self.tray:
            self.tray.update_state(self.service.state)
        if self.main_window:
            self.main_window.details_changed()
        if self.sync_status_window:
            self.sync_status_window.update_state(self.service.state)

    def on_sync_event(self, kind, payload):
        if kind == EVENT_STARTED:
            self.sync_failed = False
            self.first_sync_answer = None
            if self.sync_display.show_progress:
                self._open_sync_progress()
        elif kind == EVENT_PROGRESS:
            if self.sync_progress_dialog:
                self.sync_progress_dialog.update(payload)
        elif kind in (EVENT_FINISHED, EVENT_FAILED, EVENT_STOPPED):
            self.sync_failed = kind == EVENT_FAILED
            self._close_sync_progress()
            if kind == EVENT_FAILED and self.sync_display.show_errors:
                wx.CallAfter(self._report_sync_failure, payload)
            if kind == EVENT_FINISHED:
                wx.CallAfter(self.prompt_for_conflicts, self.main_window, self.conflict_wording())
        self.sync_settings_changed(payload if kind == EVENT_PROGRESS else None)

    def conflict_wording(self):
        from ...common.conflicts import DEVICE_MOBILE, ConflictWording
        return ConflictWording(DEVICE_MOBILE)

    def offer_partnership(self, announcement):
        if self.device_prompt_open or self.version_one_connected() or self.service.announcement is not announcement:
            return
        wx.CallAfter(self._ask_new_device, announcement)

    def _ask_new_device(self, announcement):
        from ...common.new_device import CHOICE_GUEST, CHOICE_PARTNERSHIP, CHOICE_RESTORE, DeviceChoice, ask_new_device
        if self.device_prompt_open or self.service.announcement is not announcement or self.application.partnership:
            return
        self.device_prompt_open = True
        try:
            choice = ask_new_device(
                self.main_window, title=_("New Mobile Device Detected"), size=(296, 141), intro_height=24, separator_top=40,
                intro=_("The connected device has not established a partnership with this computer.  Click Synchronize to "
                      "establish a partnership or click one of the other connection options below."),
                choices=[
                    DeviceChoice(CHOICE_PARTNERSHIP, _("&Synchronize"), _("I want to synchronize my device.  Create a partnership "
                                 "for me and save my synchronization information for future connections."), 53),
                    DeviceChoice(CHOICE_GUEST, _("&Browse"), _("I want to view and transfer files with my device.  I do not need "
                                 "to synchronize."), 83),
                    DeviceChoice(CHOICE_RESTORE, _("&Restore"), _("I want to restore data to my device from a backup file stored "
                                 "on this computer."), 113),
                ],
                button_width=62, icon=self.artwork.mobile_devices_bitmap(32))
        finally:
            self.device_prompt_open = False
        if choice == CHOICE_PARTNERSHIP and self.service.announcement is announcement:
            self.set_up_partnership(_("New Partnership Wizard"), _(PARTNERSHIP_FAILED))
        elif choice == CHOICE_RESTORE and self.service.announcement is announcement:
            from .backup import restore_guest
            restore_guest(self, self.main_window)

    def ask_first_sync(self, question):
        from ...common.conflicts import DEVICE_MOBILE, ask_combine_or_discard
        if self.first_sync_answer is None:
            icon = self.artwork.icon_as_bitmap(SYNC_MANAGER_MODULE, 141, 32)
            self.first_sync_answer = ask_combine_or_discard(self.main_window, _("ActiveSync"), DEVICE_MOBILE, _(COMBINE_INTRO), icon)
        return self.first_sync_answer

    def _open_sync_progress(self):
        self._close_sync_progress()
        self.sync_progress_dialog = SynchronizationProgressDialog(None, self)
        self.sync_progress_dialog.start()

    def _close_sync_progress(self):
        if self.sync_progress_dialog:
            try:
                self.sync_progress_dialog.finish()
            except RuntimeError:
                pass
            self.sync_progress_dialog = None

    def _report_sync_failure(self, error):
        message = _("An error has occurred in synchronization. Please correct at the desktop computer.")
        wx.MessageBox(f"{message}\n\n{error}", _("ActiveSync Error:"), wx.OK | wx.ICON_ERROR, self.main_window)

    def sync_settings_changed(self, progress=None):
        if self.tray:
            self.tray.update_state(self.service.state)
        if self.main_window:
            self.main_window.details_changed()
        if self.sync_status_window:
            self.sync_status_window.refresh(progress)

    def connected(self):
        return self.service.state == STATE_CONNECTED and not self.version_one_connected()

    def can_synchronize(self):
        return (self.connected() and not self.sync.running and not self.application.backup.running
                and self.sync.partnership() is not None)

    def can_back_up(self):
        return self.connected() and not self.application.backup.busy

    def show_backup_restore(self, parent):
        from .backup import show_backup_restore
        if self.can_back_up():
            show_backup_restore(parent, self)

    def back_up_now(self, parent):
        from .backup import back_up_now
        back_up_now(self, parent)

    def run_automatic_backup(self):
        from .backup import run_automatic_backup
        run_automatic_backup(self, self.main_window)

    def backup_state_changed(self):
        self.sync_settings_changed()

    def synchronize_now(self):
        if self.can_synchronize():
            self.sync.start()

    def show_activesync_options(self, parent):
        if not self.connected() or not self.sync.partnership():
            wx.MessageBox(_("A Guest device does not have this service available."), _("ActiveSync Options:"),
                          wx.OK | wx.ICON_INFORMATION, parent)
            return
        with ActiveSyncOptionsSheet(parent, self) as sheet:
            sheet.ShowModal()

    def device_sync_status(self):
        if not self.connected():
            return _("Guest")
        return device_status_text(partnership_status(self.sync, self.sync_failed))

    def toggle_show_progress(self):
        self.sync_display.show_progress = not self.sync_display.show_progress
        self.sync_display.save()

    def toggle_show_errors(self):
        self.sync_display.show_errors = not self.sync_display.show_errors
        self.sync_display.save()

    def connected_name(self):
        return self.application.device_name(self.service.announcement) or _("Guest")

    def version_one_connected(self):
        announcement = self.service.announcement
        return self.service.state == STATE_CONNECTED and self.application.device_major_version(announcement) == 1

    def version_one_available(self):
        return VERSION_ONE_FRONTEND in self.application.frontend_classes

    def open_version_one(self):
        if self.version_one_available():
            self.application.switch_frontend(VERSION_ONE_FRONTEND)

    def show_main_window(self):
        if not self.main_window:
            self.main_window = MobileDevicesWindow(self)
        self.main_window.Show()
        self.main_window.Raise()

    def show_sync_status(self):
        if not self.sync_status_window:
            self.sync_status_window = SyncStatusWindow(self)
        self.sync_status_window.Show()
        self.sync_status_window.Raise()

    def show_connection_settings(self, parent, page=0):
        if self.properties_sheet:
            self.properties_sheet.select_page(page)
            self.properties_sheet.Raise()
            return
        self.properties_sheet = PropertiesSheet(parent, self)
        self.properties_sheet.select_page(page)
        try:
            self.properties_sheet.ShowModal()
        finally:
            self.properties_sheet.Destroy()
            self.properties_sheet = None
        if self.main_window:
            self.main_window.update_state(self.service.state, self.service.announcement)

    def show_get_connected(self, parent):
        if self.get_connected_dialog:
            self.get_connected_dialog.Raise()
            return
        self.get_connected_dialog = GetConnectedDialog(parent, self)
        try:
            self.get_connected_dialog.ShowModal()
        finally:
            self.get_connected_dialog.Destroy()
            self.get_connected_dialog = None

    def toggle_serial_connection(self):
        self.settings.serial_enabled = not self.settings.serial_enabled
        self.settings.save()
        self.application.apply_settings(True)

    def show_device_properties(self, parent, name):
        with DevicePropertiesSheet(parent, self, self.service.announcement, name) as dialog:
            dialog.ShowModal()

    def show_about(self, parent):
        with AboutDialog(parent, self.artwork) as dialog:
            dialog.ShowModal()

    def show_preferences(self, parent):
        from ...common.preferences import show_preferences
        show_preferences(parent, self.application)
