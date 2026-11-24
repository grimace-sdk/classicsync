import wx

from ....i18n import _
from ...common.layout import dialog_size


class PropertySheet(wx.Dialog):
    def __init__(self, parent, title):
        super().__init__(parent, title=title)
        self.notebook = wx.Notebook(self)
        self.apply_button = None

    def add_page(self, label, width, height):
        page = wx.Panel(self.notebook)
        page.SetMinSize(dialog_size(page, width, height))
        self.notebook.AddPage(page, label)
        return page

    def finish(self, with_apply=True):
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        button_size = dialog_size(self, 50, 14)
        ok = wx.Button(self, wx.ID_OK, _("OK"), size=button_size)
        ok.SetDefault()
        buttons.Add(ok, 0, wx.LEFT, 6)
        buttons.Add(wx.Button(self, wx.ID_CANCEL, _("Cancel"), size=button_size), 0, wx.LEFT, 6)
        if with_apply:
            self.apply_button = wx.Button(self, wx.ID_APPLY, _("&Apply"), size=button_size)
            self.apply_button.Enable(False)
            buttons.Add(self.apply_button, 0, wx.LEFT, 6)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.notebook, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 7)
        sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 7)
        self.SetSizerAndFit(sizer)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self.Bind(wx.EVT_BUTTON, self._on_apply, id=wx.ID_APPLY)
        if self.GetParent():
            self.CentreOnParent()
        else:
            self.CentreOnScreen()

    def changed(self, event=None):
        if self.apply_button:
            self.apply_button.Enable(True)
        if event:
            event.Skip()

    def apply(self):
        pass

    def _on_ok(self, event):
        self.apply()
        self.EndModal(wx.ID_OK)

    def _on_apply(self, event):
        self.apply()
        self.apply_button.Enable(False)
