import wx

from .... import __version__
from ....i18n import _
from ...branding import about_headline, disclaimer, rebrand, title
from ...common.artwork import icon_bitmap
from ...common.layout import dialog_size, place
from ...service import STATE_CONNECTED
from ..base import Frontend
from .artwork import ActiveSyncArtwork
from .connection_settings import ConnectionSettingsDialog
from .explore import ExploreWindow
from .main_window import MainWindow
from .tray import TrayIcon

FRONTEND_KEY = "activesync31"
TITLE = title(FRONTEND_KEY)


class AboutDialog(wx.Dialog):
    def __init__(self, parent, artwork):
        super().__init__(parent, title=rebrand(_("About Microsoft ActiveSync"), FRONTEND_KEY))
        self.SetClientSize(dialog_size(self, 286, 120))
        icon = artwork.application_icons().GetIcon(wx.Size(32, 32))
        wx.StaticBitmap(self, bitmap=icon_bitmap(icon), pos=self.ConvertDialogToPixels(wx.Point(8, 11)))
        place(self, wx.StaticText, 45, 11, 230, 9, about_headline(FRONTEND_KEY, __version__))
        place(self, wx.StaticText, 45, 24, 230, 18,
              _("Desktop connectivity for Windows CE 1.x, 2.x and 3.x devices on Linux, macOS and Windows."))
        place(self, wx.StaticLine, 45, 50, 233, 1)
        place(self, wx.StaticText, 45, 58, 230, 36, disclaimer())
        place(self, wx.Button, 229, 100, 50, 14, _("OK"), id=wx.ID_OK).SetDefault()
        self.CentreOnParent()


class ActiveSyncFrontend(Frontend):
    key = FRONTEND_KEY
    title = TITLE

    def __init__(self, application):
        super().__init__(application)
        self.artwork = ActiveSyncArtwork()
        self.main_window = None
        self.explore_window = None
        self.connection_dialog = None
        self.wizard_open = False

    def start(self, initial=False):
        self.apply_tray_setting()
        if initial or self.service.state == STATE_CONNECTED:
            self.show_main_window()
        if initial and not self.settings.serial_port:
            wx.CallAfter(self.show_connection_settings, self.main_window)

    def stop(self):
        super().stop()
        for window in (self.explore_window, self.main_window):
            if window:
                try:
                    window.Destroy()
                except RuntimeError:
                    pass
        self.explore_window = None
        self.main_window = None

    def apply_tray_setting(self):
        if self.tray_available():
            if not self.tray:
                self.tray = TrayIcon(self)
            self.tray.update_state(self.service.state)
        elif self.tray:
            super().stop()

    def on_state(self, state, announcement, error):
        if state == STATE_CONNECTED:
            if self.settings.open_on_connect:
                self.show_main_window()
            if self.explore_window:
                try:
                    if not self.explore_window.browser.connected:
                        self.explore_window.device_connected()
                except RuntimeError:
                    self.explore_window = None
        elif self.explore_window:
            try:
                self.explore_window.device_disconnected()
            except RuntimeError:
                self.explore_window = None
        if self.tray:
            self.tray.update_state(state)
        if self.main_window:
            self.main_window.update_state(state, announcement, error)
        if self.connection_dialog:
            self.connection_dialog.update_state(state)

    def on_details(self, announcement):
        if self.main_window:
            self.main_window.update_state(self.service.state, announcement, None)

    def on_sync_event(self, kind, payload):
        from ...common.sync_runner import EVENT_FAILED, EVENT_PROGRESS
        if self.tray:
            self.tray.update_state(self.service.state, syncing=self.sync.running)
        if not self.main_window or self.service.state != STATE_CONNECTED:
            return
        if kind == EVENT_FAILED:
            self.main_window.show_sync_failure(payload)
        else:
            self.main_window.update_connected(self.service.announcement, payload if kind == EVENT_PROGRESS else None)

    def offer_partnership(self, announcement):
        if self.wizard_open or self.service.announcement is not announcement:
            return
        self.show_main_window()
        wx.CallAfter(self._run_wizard, announcement)

    def _run_wizard(self, announcement):
        from .partnership_wizard import run_partnership_wizard
        if self.wizard_open or self.service.announcement is not announcement or self.application.partnership:
            return
        self.wizard_open = True
        try:
            partnership = run_partnership_wizard(self.main_window, self)
        finally:
            self.wizard_open = False
        if self.main_window:
            self.main_window.update_state(self.service.state, self.service.announcement, None)
        if partnership and self.service.announcement is announcement:
            self.sync.start()

    def can_synchronize(self):
        return self.service.state == STATE_CONNECTED and not self.sync.running and self.sync.partnership() is not None

    def backup_state_changed(self):
        if self.main_window and self.service.state == STATE_CONNECTED:
            self.main_window.update_state(self.service.state, self.service.announcement, None)

    def run_automatic_backup(self):
        from .backup import run_automatic_backup
        run_automatic_backup(self, self.main_window)

    def ask_first_sync(self, question):
        from ...common.conflicts import ask_combine_or_replace
        icon = self.artwork.icon_as_bitmap("WCESMgr.exe", 88, 32)
        return ask_combine_or_replace(self.main_window, question, icon)

    def show_resolve_items(self, parent):
        from ...common.conflicts import resolve_items
        resolve_items(parent, self.sync)
        if self.main_window:
            self.main_window.update_state(self.service.state, self.service.announcement, None)

    def show_main_window(self):
        if not self.main_window:
            self.main_window = MainWindow(self)
        self.main_window.Show()
        self.main_window.Raise()

    def show_connection_settings(self, parent):
        if self.connection_dialog:
            self.connection_dialog.Raise()
            return
        self.connection_dialog = ConnectionSettingsDialog(parent, self)
        try:
            self.connection_dialog.ShowModal()
        finally:
            self.connection_dialog.Destroy()
            self.connection_dialog = None
        if self.main_window:
            self.main_window.update_state(self.service.state, self.service.announcement, self.service.error)

    def show_get_connected(self, parent):
        from .get_connected import show_get_connected
        show_get_connected(parent, self)

    def show_explore(self):
        if self.service.state != STATE_CONNECTED:
            return
        if self.explore_window:
            try:
                if self.explore_window.browser.connected:
                    self.explore_window.Raise()
                    return
                self.explore_window.Destroy()
            except RuntimeError:
                pass
        self.explore_window = ExploreWindow(self)
        self.explore_window.Show()

    def show_about(self, parent):
        with AboutDialog(parent, self.artwork) as dialog:
            dialog.ShowModal()

    def password_icon(self):
        return self.artwork.icon_as_bitmap("wcescomm.exe", 157, 32)

    def show_preferences(self, parent):
        from ...common.preferences import show_preferences
        show_preferences(parent, self.application)
