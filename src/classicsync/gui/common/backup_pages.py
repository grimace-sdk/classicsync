from dataclasses import dataclass
from pathlib import Path

import wx

from ...i18n import _
from .backup import BACKUP_FILE_NAME
from .backup_dialogs import choose_backup_file
from .layout import dialog_size, place

PAGE_WIDTH = 210
PAGE_HEIGHT = 169


@dataclass
class ExplorerPageText:
    back_up_group: str
    full: str
    incremental: str
    automatic_group: str
    automatic: str
    path_label: str
    restore_texts: tuple


class ExplorerBackupPage(wx.Panel):
    def __init__(self, parent, settings, texts, wording, guest, on_back_up, on_change=None):
        super().__init__(parent)
        self.wording = wording
        self.on_change = on_change or (lambda: None)
        self.SetMinSize(dialog_size(self, PAGE_WIDTH, PAGE_HEIGHT))
        place(self, wx.StaticBox, 7, 7, 196, 71, _(texts.back_up_group))
        self.full = place(self, wx.RadioButton, 15, 21, 180, 9, _(texts.full), style=wx.RB_GROUP)
        self.incremental = place(self, wx.RadioButton, 15, 33, 180, 18, _(texts.incremental))
        (self.incremental if settings.incremental else self.full).SetValue(True)
        back_up = place(self, wx.Button, 73, 57, 60, 14, _("Back Up &Now"))
        back_up.SetDefault()
        self.automatic_group = place(self, wx.StaticBox, 7, 85, 196, 76, _(texts.automatic_group))
        self.automatic = place(self, wx.CheckBox, 15, 99, 180, 9, _(texts.automatic))
        self.automatic.SetValue(settings.automatic and not guest)
        self.path_label = place(self, wx.StaticText, 28, 112, 120, 9, _(texts.path_label))
        self.path = place(self, wx.TextCtrl, 27, 123, 169, 14, str(settings.path), style=wx.TE_READONLY)
        self.browse = place(self, wx.Button, 146, 141, 50, 14, _("&Browse..."))
        self.guest = guest
        self.default_path = settings.directory / BACKUP_FILE_NAME
        back_up.Bind(wx.EVT_BUTTON, lambda event: on_back_up())
        self.browse.Bind(wx.EVT_BUTTON, self.on_browse)
        self.automatic.Bind(wx.EVT_CHECKBOX, self.on_automatic)
        for control in (self.full, self.incremental):
            control.Bind(wx.EVT_RADIOBUTTON, lambda event: self.on_change())
        self.update_enabled()

    def update_enabled(self):
        self.automatic_group.Enable(not self.guest)
        self.automatic.Enable(not self.guest)
        path_enabled = not self.guest and self.automatic.GetValue()
        for control in (self.path_label, self.path, self.browse):
            control.Enable(path_enabled)

    def on_automatic(self, event):
        self.update_enabled()
        self.on_change()

    def on_browse(self, event):
        chosen = choose_backup_file(self, self.wording, Path(self.path.GetValue()), True)
        if chosen:
            self.path.SetValue(str(chosen))
            self.on_change()

    def apply(self, settings):
        settings.incremental = self.incremental.GetValue()
        if not self.guest:
            settings.automatic = self.automatic.GetValue()
            path = Path(self.path.GetValue())
            settings.file = "" if path == self.default_path else str(path)


class ExplorerRestorePage(wx.Panel):
    def __init__(self, parent, texts, on_restore):
        super().__init__(parent)
        self.SetMinSize(dialog_size(self, PAGE_WIDTH, PAGE_HEIGHT))
        about, quit_programs, wait = texts.restore_texts
        place(self, wx.StaticText, 7, 7, 196, 32, _(about))
        place(self, wx.StaticText, 7, 47, 196, 16, _(quit_programs))
        place(self, wx.StaticText, 7, 71, 196, 16, _(wait))
        restore = place(self, wx.Button, 75, 95, 60, 14, _("Restore &Now"))
        restore.SetDefault()
        restore.Bind(wx.EVT_BUTTON, lambda event: on_restore())
