import wx

from ....i18n import _
from ...common.layout import dialog_size


def lay_out_property_sheet(dialog, notebook, apply_enabled=True):
    buttons = wx.BoxSizer(wx.HORIZONTAL)
    button_size = dialog_size(dialog, 50, 14)
    gap = dialog_size(dialog, 4, 0).width
    ok = wx.Button(dialog, wx.ID_OK, _("OK"), size=button_size)
    ok.SetDefault()
    buttons.Add(ok)
    buttons.Add(wx.Button(dialog, wx.ID_CANCEL, _("Cancel"), size=button_size), 0, wx.LEFT, gap)
    apply = wx.Button(dialog, wx.ID_APPLY, _("&Apply"), size=button_size)
    apply.Enable(apply_enabled)
    buttons.Add(apply, 0, wx.LEFT, gap)
    margin = dialog_size(dialog, 7, 7).width
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(notebook, 1, wx.EXPAND | wx.ALL, margin)
    sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, margin)
    dialog.SetSizerAndFit(sizer)
