import wx

from ....i18n import _
from ...common.layout import place
from .browser import HIDDEN_TYPE_LABELS
from .sheet import PropertySheet


class OptionsSheet(PropertySheet):
    def __init__(self, parent, view_settings, on_apply):
        super().__init__(parent, _("Options"))
        self.view_settings = view_settings
        self.on_apply = on_apply
        page = self.add_page(_("View"), 224, 215)
        place(page, wx.StaticBox, 7, 7, 205, 111, _("Hidden files:"))
        self.show_all = place(page, wx.RadioButton, 18, 19, 180, 12, _("&Show all files"), style=wx.RB_GROUP)
        self.hide_types = place(page, wx.RadioButton, 18, 36, 180, 12, _("Hide files of these &types:"))
        self.types = place(page, wx.ListBox, 28, 56, 175, 55, choices=[_(label) for label in HIDDEN_TYPE_LABELS])
        self.full_path = place(page, wx.CheckBox, 7, 131, 210, 14, _("Display the full &path in the title bar"))
        self.description_bars = place(page, wx.CheckBox, 7, 149, 210, 14, _("Include &description bar for right and left panes"))
        self.show_all.SetValue(not view_settings.hide_system_files)
        self.hide_types.SetValue(view_settings.hide_system_files)
        self.full_path.SetValue(view_settings.full_path_in_title)
        self.description_bars.SetValue(view_settings.description_bars)
        for control in (self.show_all, self.hide_types):
            control.Bind(wx.EVT_RADIOBUTTON, self.changed)
        for control in (self.full_path, self.description_bars):
            control.Bind(wx.EVT_CHECKBOX, self.changed)
        self.finish()

    def apply(self):
        self.view_settings.hide_system_files = self.hide_types.GetValue()
        self.view_settings.full_path_in_title = self.full_path.GetValue()
        self.view_settings.description_bars = self.description_bars.GetValue()
        self.view_settings.save()
        self.on_apply()
