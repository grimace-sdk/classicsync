import wx

from ...i18n import N_, _, plain_newlines
from .layout import dialog_size, place

INCORRECT_TITLE = N_("Password Incorrect")
INCORRECT_TEXT = N_("The password you typed is incorrect.\r\nPlease retype your password.")
PROTECTED_TITLE = N_("Password Protected")
PROTECTED_TEXT = N_("This mobile device is password protected. In order to connect to the device, you must enter its password.")


class PasswordDialog(wx.Dialog):
    def __init__(self, parent, icon=None, title=None, text=None):
        super().__init__(parent, title=title or _(PROTECTED_TITLE), style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP)
        self.SetClientSize(dialog_size(self, 222, 101))
        bitmap = icon if icon and icon.IsOk() else wx.ArtProvider.GetBitmap(wx.ART_QUESTION, wx.ART_MESSAGE_BOX, wx.Size(32, 32))
        wx.StaticBitmap(self, bitmap=bitmap, pos=self.ConvertDialogToPixels(wx.Point(11, 7)))
        place(self, wx.StaticText, 46, 7, 166, 25, text or _(PROTECTED_TEXT))
        place(self, wx.StaticText, 46, 43, 34, 8, _("&Password:"))
        self.password = place(self, wx.TextCtrl, 83, 40, 90, 14, style=wx.TE_PASSWORD)
        self.save = place(self, wx.CheckBox, 83, 60, 90, 10, _("&Save password"))
        place(self, wx.Button, 85, 79, 50, 14, _("OK"), id=wx.ID_OK).SetDefault()
        self.SetEscapeId(wx.ID_CANCEL)
        self.password.SetFocus()
        self.CentreOnScreen()


def ask_device_password(parent, attempt, icon=None):
    if attempt:
        wx.MessageBox(plain_newlines(_(INCORRECT_TEXT)), _(INCORRECT_TITLE), wx.OK | wx.ICON_WARNING, parent)
    with PasswordDialog(parent, icon) as dialog:
        if dialog.ShowModal() != wx.ID_OK:
            return None
        return dialog.password.GetValue(), dialog.save.GetValue()
