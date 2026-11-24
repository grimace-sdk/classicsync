import wx

from .layout import dialog_size, place

CHOICE_PARTNERSHIP = "partnership"
CHOICE_GUEST = "guest"
CHOICE_RESTORE = "restore"


class DeviceChoice:
    def __init__(self, choice, label, description, top, enabled=True):
        self.choice = choice
        self.label = label
        self.description = description
        self.top = top
        self.enabled = enabled


class NewDeviceDialog(wx.Dialog):
    def __init__(self, parent, title, size, intro, intro_height, separator_top, choices, button_width, icon=None):
        super().__init__(parent, title=title)
        self.chosen = CHOICE_GUEST
        width, height = size
        self.SetClientSize(dialog_size(self, width, height))
        if icon is not None and icon.IsOk():
            wx.StaticBitmap(self, bitmap=icon, pos=self.ConvertDialogToPixels(wx.Point(7, 7)))
        place(self, wx.StaticText, 44, 7, width - 53, intro_height, intro)
        place(self, wx.StaticLine, 7, separator_top, width - 14, 1)
        description_left = 8 + button_width + 7
        for index, entry in enumerate(choices):
            button = place(self, wx.Button, 8, entry.top, button_width, 14, entry.label)
            button.Enable(entry.enabled)
            if index == 0:
                button.SetDefault()
            button.Bind(wx.EVT_BUTTON, lambda event, chosen=entry.choice: self.choose(chosen))
            place(self, wx.StaticText, description_left, entry.top, width - description_left - 7, 24, entry.description)
        self.CentreOnScreen()

    def choose(self, choice):
        self.chosen = choice
        self.EndModal(wx.ID_OK)


def ask_new_device(parent, **arguments):
    with NewDeviceDialog(parent, **arguments) as dialog:
        dialog.ShowModal()
        return dialog.chosen
