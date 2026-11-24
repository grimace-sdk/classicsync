import getpass
import socket

import wx
import wx.adv

from .... import __version__
from ....i18n import N_, _
from ...branding import about_headline, disclaimer, rebrand, title
from ...common.layout import dialog_size, place
from ...common.sync_runner import EVENT_FAILED, EVENT_FINISHED, EVENT_PROGRESS, EVENT_STARTED, EVENT_STOPPED
from ...service import STATE_CONNECTED, STATE_CONNECTING
from ..base import Frontend
from .artwork import HpcExplorerArtwork
from .communications import CommunicationsSheet
from .explorer import ExplorerWindow
from .synchronization import SynchronizationManagerSheet, SynchronizationProgressDialog, overall_status, status_bar_text
from .tray import TrayIcon
from .view_settings import ViewSettings

FRONTEND_KEY = "hpcexplorer11"
TITLE = title(FRONTEND_KEY)
REPLICATION_MODULE = "replui.dll"
COMBINE_INTRO = N_("Information Manager items already exist on your H/PC. You can keep this data, or discard and replace it with "
                   "the items on your desktop computer. Please choose one of the following options to select what you want to do "
                   "with the items currently on your H/PC.")
PARTNERSHIP_FAILED = N_("Failed to setup the primary partnership between this H/PC and desktop computer. Establishing a Guest connection.")
HPC_COMBINE_BUTTONS = (99, 132, 164)


class AboutDialog(wx.Dialog):
    def __init__(self, parent, artwork):
        super().__init__(parent, title=rebrand(_("About Microsoft H/PC Explorer"), FRONTEND_KEY))
        self.SetClientSize(dialog_size(self, 289, 172))
        wx.StaticBitmap(self, bitmap=artwork.about_icon(), pos=self.ConvertDialogToPixels(wx.Point(8, 11)))
        place(self, wx.StaticText, 53, 11, 192, 10, about_headline(FRONTEND_KEY, __version__),
              style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
        place(self, wx.StaticText, 53, 37, 192, 10, _("Desktop software for Windows CE 1.0 Handheld PCs."),
              style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
        place(self, wx.StaticText, 53, 47, 192, 10, _("This product is licensed to:"), style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
        frame = place(self, wx.Panel, 44, 62, 238, 37, style=wx.BORDER_SUNKEN)
        place(frame, wx.StaticText, 8, 3, 214, 10, getpass.getuser())
        place(frame, wx.StaticText, 8, 12, 218, 10, socket.gethostname())
        place(self, wx.StaticLine, 8, 106, 274, 1)
        place(self, wx.StaticText, 9, 113, 184, 34, disclaimer())
        place(self, wx.Button, 206, 131, 76, 16, _("OK"), id=wx.ID_OK).SetDefault()
        self.CentreOnParent()


class ConnectingDialog(wx.Dialog):
    def __init__(self, artwork):
        super().__init__(None, title=_("Now Connecting H/PC"), style=wx.CAPTION | wx.STAY_ON_TOP)
        self.SetClientSize(dialog_size(self, 142, 50))
        wx.StaticBitmap(self, bitmap=artwork.state_bitmap("connecting"), pos=self.ConvertDialogToPixels(wx.Point(7, 14)))
        place(self, wx.StaticText, 37, 15, 98, 16, _("Establishing connection to H/PC..."))
        self.CentreOnScreen()


class HpcExplorerFrontend(Frontend):
    key = "hpcexplorer11"
    title = TITLE
    device_versions = (1,)

    def __init__(self, application):
        super().__init__(application)
        self.artwork = HpcExplorerArtwork()
        self.view_settings = ViewSettings.load()
        self.explorer_window = None
        self.communications_sheet = None
        self.connecting_dialog = None
        self.previous_state = None
        self.sound = None
        self.sync_failed = False
        self.sync_progress_dialog = None
        self.first_sync_answer = None
        self.device_prompt_open = False

    def start(self, initial=False):
        self.apply_tray_setting()
        if initial or self.service.state == STATE_CONNECTED:
            self.show_main_window()
        if initial and not self.settings.serial_port:
            wx.CallAfter(self.show_connection_settings, self.explorer_window)

    def stop(self):
        super().stop()
        self._close_connecting_dialog()
        self._close_sync_progress()
        if self.explorer_window:
            try:
                self.explorer_window.Destroy()
            except RuntimeError:
                pass
        self.explorer_window = None

    def apply_tray_setting(self):
        if self.tray_available():
            if not self.tray:
                self.tray = TrayIcon(self)
            self.tray.update_state(self.service.state)
        elif self.tray:
            super().stop()

    def on_state(self, state, announcement, error):
        self._update_connecting_dialog(state)
        self.play_transition_sound(state)
        self.previous_state = state
        if self.tray:
            self.tray.update_state(state)
        if self.explorer_window:
            self.explorer_window.update_state(state, announcement, error)
        if state == STATE_CONNECTED and self.settings.open_on_connect:
            self.show_main_window()
        if self.communications_sheet:
            self.communications_sheet.update_state(state)

    def on_details(self, announcement):
        if self.explorer_window:
            self.explorer_window.update_sync_status()

    def on_sync_event(self, kind, payload):
        if kind == EVENT_STARTED:
            self.sync_failed = False
            self.first_sync_answer = None
            self._open_sync_progress()
        elif kind == EVENT_PROGRESS:
            if self.sync_progress_dialog:
                self.sync_progress_dialog.update(payload)
        elif kind in (EVENT_FINISHED, EVENT_FAILED, EVENT_STOPPED):
            self.sync_failed = kind == EVENT_FAILED
            self._close_sync_progress()
            if kind == EVENT_FAILED:
                wx.CallAfter(self._report_sync_failure, payload)
            if kind == EVENT_FINISHED:
                wx.CallAfter(self.prompt_for_conflicts, self.explorer_window, self.conflict_wording())
        if self.explorer_window:
            self.explorer_window.update_sync_status()

    def conflict_wording(self):
        from ...common.conflicts import DEVICE_HPC, ConflictWording
        return ConflictWording(DEVICE_HPC)

    def offer_partnership(self, announcement):
        if self.device_prompt_open or self.service.announcement is not announcement:
            return
        wx.CallAfter(self._ask_new_device, announcement)

    def _ask_new_device(self, announcement):
        from ...common.new_device import CHOICE_GUEST, CHOICE_PARTNERSHIP, CHOICE_RESTORE, DeviceChoice, ask_new_device
        if self.device_prompt_open or self.service.announcement is not announcement or self.application.partnership:
            return
        self.device_prompt_open = True
        try:
            choice = ask_new_device(
                self.explorer_window, title=_("Guest H/PC Detected"), size=(290, 153), intro_height=16, separator_top=32,
                intro=_("A guest H/PC has been connected. You may proceed as a guest, restore from a previous backup file, or "
                      "set up a new partnership."),
                choices=[
                    DeviceChoice(CHOICE_GUEST, _("&Guest"), _("View files and folders on this H/PC. Choose this option to view and "
                                 "transfer files with this H/PC (data synchronization disabled)."), 45),
                    DeviceChoice(CHOICE_RESTORE, _("&Restore"), _("Select a backup file to restore. Choose this option if you have "
                                 "lost your data (due to power failure) or if this is a replacement H/PC."), 82),
                    DeviceChoice(CHOICE_PARTNERSHIP, _("&New Partner"), _("Establish this H/PC as the new partner. Choose this option "
                                 "if you have taken over this desktop computer and wish to establish a new partnership."), 119),
                ],
                button_width=50, icon=self.artwork.about_icon())
        finally:
            self.device_prompt_open = False
        if choice == CHOICE_PARTNERSHIP and self.service.announcement is announcement:
            self.set_up_partnership(_("Setup New Partner Wizard"), _(PARTNERSHIP_FAILED), exclusive=True)
        elif choice == CHOICE_RESTORE and self.service.announcement is announcement:
            from .backup import restore_guest
            restore_guest(self, self.explorer_window)

    def partnership_created(self):
        from .backup import offer_full_backup
        self.application.backup.after_sync(lambda: self.connected() and offer_full_backup(self, self.explorer_window))

    def can_back_up(self):
        return self.connected() and not self.application.backup.busy

    def show_backup_restore(self, parent):
        from .backup import show_backup_restore
        if self.connected():
            show_backup_restore(parent, self)

    def back_up_now(self, parent):
        from .backup import back_up_now
        back_up_now(self, parent)

    def run_automatic_backup(self):
        from .backup import run_automatic_backup
        run_automatic_backup(self, self.explorer_window)

    def backup_state_changed(self):
        if self.explorer_window:
            self.explorer_window.update_sync_status()

    def ask_first_sync(self, question):
        from ...common.conflicts import DEVICE_HPC, ask_combine_or_discard
        if self.first_sync_answer is None:
            icon = self.artwork.icon_as_bitmap(REPLICATION_MODULE, 141, 32)
            self.first_sync_answer = ask_combine_or_discard(self.explorer_window, _("Synchronization Manager"), DEVICE_HPC,
                                                            _(COMBINE_INTRO), icon, HPC_COMBINE_BUTTONS)
        return self.first_sync_answer

    def _open_sync_progress(self):
        self._close_sync_progress()
        self.sync_progress_dialog = SynchronizationProgressDialog(self.explorer_window, self)
        self.sync_progress_dialog.start()

    def _close_sync_progress(self):
        if self.sync_progress_dialog:
            try:
                self.sync_progress_dialog.finish()
            except RuntimeError:
                pass
            self.sync_progress_dialog = None

    def _report_sync_failure(self, error):
        wx.MessageBox(_("Synchronization did not complete.\n\n{error}").format(error=error), _("Synchronization Manager"),
                      wx.OK | wx.ICON_ERROR, self.explorer_window)

    def connected(self):
        return self.service.state == STATE_CONNECTED

    def can_synchronize(self):
        return (self.connected() and not self.sync.running and not self.application.backup.running
                and self.sync.partnership() is not None)

    def synchronize_now(self):
        if self.can_synchronize():
            self.sync.start()

    def sync_status_bar_text(self):
        return status_bar_text(overall_status(self.sync, self.connected(), self.sync_failed))

    def sync_settings_changed(self):
        if self.explorer_window:
            self.explorer_window.update_sync_status()

    def show_synchronization_manager(self, parent):
        if not self.sync.partnership():
            wx.MessageBox(_("Synchronization Manager is available once the H/PC has connected."), _("Synchronization Manager"),
                          wx.OK | wx.ICON_INFORMATION, parent)
            return
        with SynchronizationManagerSheet(parent, self) as sheet:
            sheet.ShowModal()

    def _update_connecting_dialog(self, state):
        if state == STATE_CONNECTING:
            if not self.connecting_dialog:
                self.connecting_dialog = ConnectingDialog(self.artwork)
                self.connecting_dialog.Show()
        else:
            self._close_connecting_dialog()

    def _close_connecting_dialog(self):
        if self.connecting_dialog:
            self.connecting_dialog.Destroy()
            self.connecting_dialog = None

    def show_main_window(self):
        if not self.explorer_window:
            self.explorer_window = ExplorerWindow(self)
        self.explorer_window.Show()
        self.explorer_window.Raise()

    def show_connection_settings(self, parent):
        if self.communications_sheet:
            self.communications_sheet.Raise()
            return
        self.communications_sheet = CommunicationsSheet(parent, self)
        try:
            self.communications_sheet.ShowModal()
        finally:
            self.communications_sheet.Destroy()
            self.communications_sheet = None

    def close_communications(self):
        self.service.suspend()

    def show_about(self, parent):
        with AboutDialog(parent, self.artwork) as dialog:
            dialog.ShowModal()

    def show_preferences(self, parent):
        from ...common.preferences import show_preferences
        show_preferences(parent, self.application)
