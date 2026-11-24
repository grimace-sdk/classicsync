from dataclasses import dataclass
from datetime import datetime

import wx

from ...i18n import _, format_original
from .layout import dialog_size, place
from .transfers import REPLACE_ALL, REPLACE_CANCEL, REPLACE_KEEP_BOTH, REPLACE_OVERWRITE, REPLACE_SKIP

REPLACE_ICONS = {
    "activesync-3.1": ("Wcesview.dll", 129, 130),
    "ce-services-2.2": ("HPCView.dll", 129, 130),
    "hpc-explorer-1.1": ("hpcexpl.exe", 183, 182),
}


@dataclass
class FileFacts:
    size: int
    modified: datetime = None
    bitmap: wx.Bitmap = None


def dialog_icon(artwork, folder):
    def fallback():
        return wx.ArtProvider.GetBitmap(wx.ART_QUESTION, wx.ART_MESSAGE_BOX, wx.Size(32, 32))
    entry = REPLACE_ICONS.get(getattr(artwork, "product", None))
    if artwork is None or entry is None:
        return fallback()
    module, file_number, folder_number = entry
    return artwork.icon_as_bitmap(module, folder_number if folder else file_number, 32, fallback)


def describe_modified(moment):
    if moment is None:
        return ""
    return format_original(_("modified on %s"), moment.astimezone().strftime("%A, %B %d, %Y %H:%M:%S"))


class ChoiceDialog(wx.Dialog):
    def add_buttons(self, buttons, top, width):
        self.choice = REPLACE_CANCEL
        for index, (x, label, choice) in enumerate(buttons):
            button = place(self, wx.Button, x, top, width, 14, label)
            button.Bind(wx.EVT_BUTTON, lambda event, choice=choice: self.choose(choice))
            if index == 0:
                button.SetDefault()
                button.SetFocus()
        self.SetEscapeId(wx.ID_NONE)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key)
        self.Bind(wx.EVT_CLOSE, lambda event: self.choose(REPLACE_CANCEL))

    def on_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.choose(REPLACE_CANCEL)
        else:
            event.Skip()

    def choose(self, choice):
        self.choice = choice
        self.EndModal(wx.ID_OK)


class FileReplaceDialog(ChoiceDialog):
    def __init__(self, parent, artwork, name, existing, incoming, keep_both=False):
        super().__init__(parent, title=_("Confirm File Replace"))
        self.SetClientSize(dialog_size(self, 257, 179))
        wx.StaticBitmap(self, bitmap=dialog_icon(artwork, False), pos=self.ConvertDialogToPixels(wx.Point(7, 7)))
        place(self, wx.StaticText, 37, 7, 213, 42,
              format_original(_("This folder already contains a %sfile called '%s'.\r\n\r\nWould you like to replace the existing file"),
                              "", name).replace("\r\n", "\n"))
        self.facts(existing, 54)
        place(self, wx.StaticText, 27, 87, 74, 8, _("with this one?"))
        self.facts(incoming, 108)
        if keep_both:
            buttons = [(5, _("&Yes"), REPLACE_OVERWRITE), (55, _("Yes To &All"), REPLACE_ALL), (105, _("&Keep Both"), REPLACE_KEEP_BOTH),
                       (155, _("&No"), REPLACE_SKIP), (205, _("Cancel"), REPLACE_CANCEL)]
            self.add_buttons(buttons, 158, 47)
        else:
            buttons = [(35, _("&Yes"), REPLACE_OVERWRITE), (89, _("Yes To &All"), REPLACE_ALL), (145, _("&No"), REPLACE_SKIP),
                       (200, _("Cancel"), REPLACE_CANCEL)]
            self.add_buttons(buttons, 158, 50)
        self.CentreOnParent()

    def facts(self, facts, top):
        if facts is None:
            return
        if facts.bitmap and facts.bitmap.IsOk():
            wx.StaticBitmap(self, bitmap=facts.bitmap, pos=self.ConvertDialogToPixels(wx.Point(41, top)))
        place(self, wx.StaticText, 74, top, 82, 8, format_original(_("%d bytes"), facts.size))
        place(self, wx.StaticText, 74, top + 11, 168, 8, describe_modified(facts.modified))


class FolderReplaceDialog(ChoiceDialog):
    def __init__(self, parent, artwork, name):
        super().__init__(parent, title=_("Confirm Folder Replace"))
        self.SetClientSize(dialog_size(self, 275, 85))
        wx.StaticBitmap(self, bitmap=dialog_icon(artwork, True), pos=self.ConvertDialogToPixels(wx.Point(10, 10)))
        place(self, wx.StaticText, 41, 10, 222, 53,
              format_original(_("This folder already contains a folder called '%s'.\n\nIf the files in the existing folder have the same name "
                                "as files in the folder you are moving, do you want to replace the existing files?"), name))
        buttons = [(41, _("&Yes"), REPLACE_OVERWRITE), (99, _("Yes to &All"), REPLACE_ALL), (157, _("&No"), REPLACE_SKIP),
                   (215, _("Cancel"), REPLACE_CANCEL)]
        self.add_buttons(buttons, 64, 53)
        self.CentreOnParent()


class ReplacePrompt:
    def __init__(self, parent, artwork, keep_both=False):
        self.parent = parent
        self.artwork = artwork
        self.keep_both = keep_both
        self.replace_all = False

    def ask_file(self, name, existing=None, incoming=None):
        if self.replace_all:
            return REPLACE_OVERWRITE
        with FileReplaceDialog(self.parent, self.artwork, name, existing, incoming, self.keep_both) as dialog:
            dialog.ShowModal()
            choice = dialog.choice
        if choice == REPLACE_ALL:
            self.replace_all = True
            return REPLACE_OVERWRITE
        return choice

    def ask_folder(self, name):
        if self.replace_all:
            return REPLACE_OVERWRITE
        with FolderReplaceDialog(self.parent, self.artwork, name) as dialog:
            dialog.ShowModal()
            choice = dialog.choice
        if choice == REPLACE_ALL:
            self.replace_all = True
            return REPLACE_OVERWRITE
        return choice
