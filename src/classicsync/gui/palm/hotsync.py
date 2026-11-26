import wx
import wx.adv

from ... import __version__
from ...i18n import _
from ...palm.sync import palm_partnerships
from ..branding import about_headline, palm_disclaimer, rebrand, title
from ..common.artwork import Artwork, draw_sync_badge, drawn_icon
from ..common.layout import dialog_size, place
from .hotsync_log import read_log
from .service import (
    EVENT_FINISHED, EVENT_STAGE, EVENT_STARTED, EVENT_STATUS, EVENT_USER, STAGE_CONNECTING, STAGE_IDENTIFIED, STAGE_SYNCHRONIZING,
)

KEY = "hotsync40"
PRODUCT = "hotsync-4.0.1"
MODULE = "Hotsync.exe"
TITLE = title(KEY)
FRAME_SIZE = 48
ARROW_FRAMES = 12
ANIMATION_MILLISECONDS = 120
LOGO_HEIGHT = 21
USER_NAME_LIMIT = 15
ILLEGAL_NAME_CHARACTERS = set('*+,./:;<=>?[]|\\^"')

ORIGINAL_ID_OFFSET = 30000
ID_LOCAL_SERIAL = 32774 - ORIGINAL_ID_OFFSET
ID_LOCAL_USB = 32790 - ORIGINAL_ID_OFFSET
ID_MODEM = 32775 - ORIGINAL_ID_OFFSET
ID_NETWORK = 32781 - ORIGINAL_ID_OFFSET
ID_INFRARED = 32784 - ORIGINAL_ID_OFFSET
ID_SETUP = 32776 - ORIGINAL_ID_OFFSET
ID_CUSTOM = 32778 - ORIGINAL_ID_OFFSET
ID_FILE_LINK = 32782 - ORIGINAL_ID_OFFSET
ID_VIEW_LOG = 32779 - ORIGINAL_ID_OFFSET
ID_ABOUT = 57664 - ORIGINAL_ID_OFFSET
ID_HELP = 57667 - ORIGINAL_ID_OFFSET
ID_EXIT = 57665 - ORIGINAL_ID_OFFSET


class HotSyncArtwork(Artwork):
    def __init__(self):
        super().__init__(PRODUCT)

    def tray_icon(self):
        return self.cached("tray", lambda: self.icon(MODULE, 1, 16, lambda: drawn_icon(32, "connected")))

    def icon_bitmap(self, number, size=32):
        return self.icon_as_bitmap(MODULE, number, size, lambda: draw_sync_badge(size, wx.Colour(200, 30, 30)))

    def frames(self, name, count):
        return self.cached(("frames", name), lambda: self.strip(MODULE, name, FRAME_SIZE, count,
                                                               lambda: [draw_sync_badge(FRAME_SIZE, wx.Colour(160, 160, 160))] * count))

    def logo(self):
        return self.bitmap(MODULE, "bitmap_165.bmp")


class ProgressDialog(wx.Dialog):
    def __init__(self, manager):
        super().__init__(None, title=_("HotSync Progress"), style=wx.CAPTION | wx.STAY_ON_TOP)
        self.manager = manager
        artwork = manager.artwork
        self.SetClientSize(dialog_size(self, 182, 103))
        place(self, wx.StaticText, 12, 6, 24, 8, _("Status:"))
        self.status = place(self, wx.StaticText, 39, 6, 136, 8, "", style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
        place(self, wx.StaticText, 17, 20, 19, 8, _("User:"))
        self.user = place(self, wx.StaticText, 39, 20, 136, 8, "", style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
        self.handheld_frames = artwork.frames("bitmap_10015.bmp", 2)
        self.user_frames = artwork.frames("bitmap_10018.bmp", 2)
        self.arrow_frames = artwork.frames("bitmap_10020.bmp", ARROW_FRAMES)
        self.images = []
        for x in (26, 73, 120):
            position = self.ConvertDialogToPixels(wx.Point(x, 37))
            self.images.append(wx.StaticBitmap(self, bitmap=self.handheld_frames[0], pos=position))
        logo = artwork.logo()
        if logo.IsOk():
            height = dialog_size(self, 0, LOGO_HEIGHT).height
            image = logo.ConvertToImage()
            image.Rescale(max(1, image.GetWidth() * height // image.GetHeight()), height, wx.IMAGE_QUALITY_HIGH)
            wx.StaticBitmap(self, bitmap=wx.Bitmap(image), pos=self.ConvertDialogToPixels(wx.Point(7, 75)))
        self.cancel = place(self, wx.Button, 125, 82, 50, 14, _("Cancel"), id=wx.ID_CANCEL)
        self.cancel.Bind(wx.EVT_BUTTON, self.on_cancel)
        self.arrow_index = 1
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_timer, self.timer)
        self.set_stage(STAGE_CONNECTING)
        self.CentreOnScreen()

    def set_stage(self, stage):
        self.images[0].SetBitmap(self.handheld_frames[1 if stage >= STAGE_CONNECTING else 0])
        self.images[1].SetBitmap(self.user_frames[1 if stage >= STAGE_IDENTIFIED else 0])
        self.images[2].SetBitmap(self.arrow_frames[0])
        if stage >= STAGE_SYNCHRONIZING and not self.timer.IsRunning():
            self.timer.Start(ANIMATION_MILLISECONDS)

    def on_timer(self, event):
        self.arrow_index = self.arrow_index % (ARROW_FRAMES - 1) + 1
        self.images[2].SetBitmap(self.arrow_frames[self.arrow_index])

    def on_cancel(self, event):
        message = _("If you cancel this HotSync operation now, some of your data will not be synchronized. You will need to "
                    "perform a complete HotSync operation later to insure all your data is safely backed up.\n\n"
                    "Cancel this HotSync operation?")
        if wx.MessageBox(message, _("Cancel HotSync operation"), wx.YES_NO | wx.ICON_WARNING, self) == wx.YES:
            self.status.SetLabel(_("Canceling - this may take 1 minute"))
            self.cancel.Disable()
            self.manager.service.cancel()

    def close(self):
        self.timer.Stop()
        self.Destroy()


class UserNameDialog(wx.Dialog):
    def __init__(self, parent, prompt, caption):
        super().__init__(parent, title=caption)
        self.SetClientSize(dialog_size(self, 134, 55))
        place(self, wx.StaticText, 10, 5, 110, 8, prompt)
        self.name = place(self, wx.TextCtrl, 10, 15, 110, 12, "")
        self.name.SetMaxLength(USER_NAME_LIMIT)
        place(self, wx.Button, 30, 35, 41, 14, _("OK"), id=wx.ID_OK).SetDefault()
        place(self, wx.Button, 80, 35, 41, 14, _("Cancel"), id=wx.ID_CANCEL)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.CentreOnScreen()

    def on_ok(self, event):
        name = self.name.GetValue().strip()
        if not name:
            wx.MessageBox(_("Please enter a user name."), TITLE, wx.OK | wx.ICON_WARNING, self)
            return
        if set(name) & ILLEGAL_NAME_CHARACTERS or any(partnership.name.lower() == name.lower() for partnership in palm_partnerships()):
            wx.MessageBox(name + _(" is already in use as a user or profile name.") if not set(name) & ILLEGAL_NAME_CHARACTERS
                          else _("Could not add user '{name}'. '{name}' is an illegal user name.").format(name=name),
                          _("User Name Exists"), wx.OK | wx.ICON_WARNING, self)
            return
        self.EndModal(wx.ID_OK)


class UsersDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Users"), style=wx.CAPTION | wx.STAY_ON_TOP)
        self.SetClientSize(dialog_size(self, 175, 137))
        place(self, wx.StaticText, 10, 5, 52, 8, _("Select a user:"))
        self.partnerships = sorted(palm_partnerships(), key=lambda partnership: partnership.name.lower())
        self.users = place(self, wx.ListBox, 10, 15, 100, 113, choices=[partnership.name for partnership in self.partnerships])
        if self.partnerships:
            self.users.SetSelection(0)
        place(self, wx.Button, 120, 15, 45, 14, _("OK"), id=wx.ID_OK).SetDefault()
        place(self, wx.Button, 120, 39, 45, 14, _("&New..."), id=wx.ID_NEW)
        place(self, wx.Button, 120, 55, 45, 14, _("Cancel"), id=wx.ID_CANCEL)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.Bind(wx.EVT_BUTTON, self.on_new, id=wx.ID_NEW)
        self.users.Bind(wx.EVT_LISTBOX_DCLICK, self.on_ok)
        self.chosen = None
        self.CentreOnScreen()

    def on_new(self, event):
        with UserNameDialog(self, _("Enter a new user name:"), _("New User")) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.chosen = (dialog.name.GetValue().strip(), None)
                self.EndModal(wx.ID_OK)

    def on_ok(self, event):
        index = self.users.GetSelection()
        if index == wx.NOT_FOUND:
            wx.MessageBox(_("Please select a user name."), TITLE, wx.OK | wx.ICON_WARNING, self)
            return
        partnership = self.partnerships[index]
        self.chosen = (partnership.name, partnership.partner_id)
        self.EndModal(wx.ID_OK)


class LogDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("HotSync Log"))
        self.SetClientSize(dialog_size(self, 374, 221))
        self.partnerships = sorted(palm_partnerships(), key=lambda partnership: partnership.name.lower())
        self.users = place(self, wx.Choice, 10, 5, 135, 70, choices=[partnership.name for partnership in self.partnerships])
        self.text = place(self, wx.TextCtrl, 10, 25, 354, 171, "", style=wx.TE_MULTILINE | wx.TE_READONLY)
        place(self, wx.Button, 162, 202, 50, 14, _("OK"), id=wx.ID_OK).SetDefault()
        self.users.Bind(wx.EVT_CHOICE, self.on_user)
        self.Bind(wx.EVT_ACTIVATE, lambda event: (self.on_user(None), event.Skip()))
        if self.partnerships:
            self.users.SetSelection(0)
            self.on_user(None)
        self.CentreOnScreen()

    def on_user(self, event):
        index = self.users.GetSelection()
        if index != wx.NOT_FOUND:
            self.text.SetValue(read_log(self.partnerships[index]))


class AboutDialog(wx.Dialog):
    def __init__(self, parent, artwork):
        super().__init__(parent, title=rebrand(_("About HotSync Manager"), KEY))
        self.SetClientSize(dialog_size(self, 230, 110))
        wx.StaticBitmap(self, bitmap=artwork.icon_bitmap(1), pos=self.ConvertDialogToPixels(wx.Point(8, 10)))
        place(self, wx.StaticText, 40, 10, 180, 9, about_headline(KEY, __version__))
        place(self, wx.StaticText, 40, 24, 180, 18, _("HotSync for Palm OS handhelds on Linux, macOS and Windows."))
        place(self, wx.StaticLine, 40, 48, 182, 1)
        place(self, wx.StaticText, 40, 55, 180, 30, palm_disclaimer())
        place(self, wx.Button, 172, 90, 50, 14, _("OK"), id=wx.ID_OK).SetDefault()
        self.CentreOnScreen()


class HotSyncTray(wx.adv.TaskBarIcon):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.SetIcon(manager.artwork.tray_icon(), TITLE)
        self.Bind(wx.EVT_MENU, self.on_menu)

    def CreatePopupMenu(self):
        settings = self.manager.settings
        menu = wx.Menu()
        menu.AppendCheckItem(ID_LOCAL_SERIAL, _("&Local Serial")).Enable(False)
        menu.AppendCheckItem(ID_LOCAL_USB, _("Local &USB")).Check(settings.palm_usb_enabled)
        menu.AppendCheckItem(ID_MODEM, _("&Modem")).Enable(False)
        menu.AppendCheckItem(ID_NETWORK, _("&Network")).Enable(False)
        menu.AppendCheckItem(ID_INFRARED, _("&InfraRed")).Enable(False)
        menu.AppendSeparator()
        menu.Append(ID_SETUP, _("&Setup..."))
        menu.AppendSeparator()
        menu.Append(ID_CUSTOM, _("&Custom...")).Enable(False)
        menu.Append(ID_FILE_LINK, _("&File Link...")).Enable(False)
        menu.Append(ID_VIEW_LOG, _("&View Log..."))
        menu.AppendSeparator()
        menu.Append(ID_ABOUT, _("&About..."))
        menu.Append(ID_HELP, _("&Help...")).Enable(False)
        menu.AppendSeparator()
        menu.Append(ID_EXIT, _("E&xit"))
        return menu

    def on_menu(self, event):
        identifier = event.GetId()
        if identifier == ID_LOCAL_USB:
            self.manager.toggle_usb()
        elif identifier == ID_SETUP:
            self.manager.show_setup()
        elif identifier == ID_VIEW_LOG:
            self.manager.show_log()
        elif identifier == ID_ABOUT:
            self.manager.show_about()
        elif identifier == ID_EXIT:
            self.manager.application.quit()


class HotSyncManager:
    def __init__(self, application, service):
        self.application = application
        self.settings = application.settings
        self.service = service
        self.artwork = HotSyncArtwork()
        self.tray = None
        self.progress = None
        service.ask_user_name = lambda reply: wx.CallAfter(self.ask_user_name, reply)

    def start(self):
        self.apply_tray_setting()

    def stop(self):
        if self.tray:
            self.tray.RemoveIcon()
            wx.CallAfter(self.tray.Destroy)
            self.tray = None
        if self.progress:
            self.progress.close()
            self.progress = None

    def apply_tray_setting(self):
        wanted = self.settings.show_hotsync_tray and self.settings.palm_usb_enabled and wx.adv.TaskBarIcon.IsAvailable()
        if wanted and not self.tray:
            self.tray = HotSyncTray(self)
        elif not wanted and self.tray:
            self.tray.RemoveIcon()
            wx.CallAfter(self.tray.Destroy)
            self.tray = None

    def toggle_usb(self):
        self.settings.palm_usb_enabled = not self.settings.palm_usb_enabled
        self.settings.save()
        self.service.restart()
        self.apply_tray_setting()

    def on_event(self, kind, payload):
        if kind == EVENT_STARTED:
            if self.progress is None:
                self.progress = ProgressDialog(self)
                self.progress.Show()
        elif self.progress is None:
            return
        elif kind == EVENT_STATUS:
            self.progress.status.SetLabel(payload)
        elif kind == EVENT_USER:
            self.progress.user.SetLabel(payload)
        elif kind == EVENT_STAGE:
            self.progress.set_stage(payload)
        elif kind == EVENT_FINISHED:
            self.progress.close()
            self.progress = None
            succeeded, message, logged = payload
            if succeeded and logged:
                self.show_problem(_("Synchronization generated one or more messages. Please see the HotSync Log for details."))
            elif not succeeded and logged:
                self.show_problem(_("The HotSync operation was interrupted. Some of your data was NOT backed up.\n\n"
                                    "For details, click 'View Log' below."))
            elif not succeeded and message:
                wx.MessageBox(_("The HotSync operation was interrupted. Some of your data was NOT backed up.\n\n{error}").format(
                    error=message), _("HotSync Problem"), wx.OK | wx.ICON_WARNING)

    def show_problem(self, text):
        with wx.MessageDialog(None, text, _("HotSync Problem"), wx.YES_NO | wx.ICON_WARNING) as dialog:
            dialog.SetYesNoLabels(_("OK"), _("&View Log"))
            if dialog.ShowModal() == wx.ID_NO:
                self.show_log()

    def ask_user_name(self, reply):
        try:
            with UsersDialog(self.progress) as dialog:
                reply(dialog.chosen if dialog.ShowModal() == wx.ID_OK else None)
        except Exception:
            reply(None)
            raise

    def show_setup(self):
        from ..common.preferences import show_preferences
        show_preferences(None, self.application, page="palm")

    def show_log(self):
        with LogDialog(None) as dialog:
            dialog.ShowModal()

    def show_about(self):
        with AboutDialog(None, self.artwork) as dialog:
            dialog.ShowModal()
