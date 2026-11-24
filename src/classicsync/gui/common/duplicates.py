import wx

from ...i18n import N_, _
from ..branding import rebrand
from .layout import dialog_size, place

FOUND_TEXT = N_("ActiveSync has found duplicate items in your desktop data. Choose Remove All (recommended) to remove all duplicate "
                "items. The original copy of each item will be kept; only the duplicate copies will be removed.")


class RemoveDuplicatesDialog(wx.Dialog):
    def __init__(self, parent, duplicates, frontend_key):
        super().__init__(parent, title=_("Remove Duplicate Items"))
        self.SetClientSize(dialog_size(self, 286, 176))
        place(self, wx.StaticText, 7, 7, 272, 25, rebrand(_(FOUND_TEXT), frontend_key))
        self.items = place(self, wx.ListCtrl, 7, 38, 272, 110, style=wx.LC_REPORT)
        self.items.InsertColumn(0, _("Name"), width=dialog_size(self, 180, 0).width)
        self.items.InsertColumn(1, _("Duplicate of"), width=dialog_size(self, 86, 0).width)
        self.extras = []
        type_name = _(duplicates.object_type.display_name)
        for group in duplicates.groups:
            for item_id, description in group.extras:
                index = self.items.InsertItem(len(self.extras), description)
                self.items.SetItem(index, 1, group.keep_description or type_name)
                self.extras.append(item_id)
        self.chosen = []
        for x, label, handler in ((38, _("Remove &All"), self.remove_all), (112, _("Remove &Selected"), self.remove_selected),
                                  (187, _("&Keep All"), self.keep_all)):
            button = place(self, wx.Button, x, 155, 64, 14, label)
            button.Bind(wx.EVT_BUTTON, handler)
            if x == 38:
                button.SetDefault()
        self.Bind(wx.EVT_CLOSE, self.keep_all)
        self.CentreOnParent() if parent else self.CentreOnScreen()

    def remove_all(self, event):
        self.chosen = list(self.extras)
        self.EndModal(wx.ID_OK)

    def remove_selected(self, event):
        indices = []
        index = self.items.GetFirstSelected()
        while index != -1:
            indices.append(index)
            index = self.items.GetNextSelected(index)
        self.chosen = [self.extras[index] for index in indices]
        self.EndModal(wx.ID_OK)

    def keep_all(self, event):
        self.chosen = []
        self.EndModal(wx.ID_CANCEL)


def ask_remove_duplicates(parent, duplicates, frontend_key):
    with RemoveDuplicatesDialog(parent, duplicates, frontend_key) as dialog:
        dialog.ShowModal()
        return dialog.chosen
