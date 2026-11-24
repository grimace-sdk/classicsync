import copy

import wx

from ...i18n import N_, _
from ...sync import FIRST_SYNC_COMBINE, FIRST_SYNC_REPLACE, FIRST_SYNC_SKIP
from .layout import dialog_size, place

RESOLVE_WIDTH = 278
RESOLVE_LIST_HEIGHT = 56
RESOLVE_DETAIL_TOP = 92
RESOLVE_DETAIL_HEIGHT = 50
RESOLVE_ACTION_TOP = 148
RESOLVE_BUTTON_TOP = 168
RESOLVE_HEIGHT = 186

RESOLUTION_ORDER = ("desktop", "device", "skip")
COMBINE_DISCARD_BUTTONS = (87, 124, 166)


DEVICE_MOBILE = "mobile device"
DEVICE_HPC = "H/PC"

WORDING = {
    DEVICE_MOBILE: {
        "column": N_("Mobile Device"),
        "intro": N_("The items below have been modified on both the mobile device and the desktop computer. To resolve the "
                    "conflict, choose which item to replace."),
        "desktop": N_("Replace the mobile device item with the desktop computer item."),
        "device": N_("Replace the desktop computer item with the mobile device item."),
        "combine": N_("Combine mobile device and desktop computer items, giving you the option to remove identical items. Note "
                      "that this may not detect all duplicates, so you may need to remove some duplicate items manually."),
        "discard": N_("Erase all synchronized database items on your mobile device, then copy items from your desktop "
                      "computer to your mobile device."),
    },
    DEVICE_HPC: {
        "column": N_("H/PC"),
        "intro": N_("The items below have been modified on both the H/PC and the desktop computer. To resolve the conflict, "
                    "choose which item to replace."),
        "desktop": N_("Replace the H/PC item with the desktop computer item."),
        "device": N_("Replace the desktop computer item with the H/PC item."),
        "combine": N_("Combine H/PC and desktop computer items, giving you the option to remove identical items. Note that this "
                      "may not detect all duplicates, so you may need to remove some duplicate items manually."),
        "discard": N_("Erase all synchronized database items on your H/PC, then copy items from your desktop computer to your "
                      "H/PC."),
    },
}


class ConflictWording:
    def __init__(self, device=DEVICE_MOBILE):
        self.texts = WORDING[device]

    def text(self, key):
        return _(self.texts[key])

    @property
    def device_column(self):
        return self.text("column")

    @property
    def intro(self):
        return self.text("intro")

    def action_text(self, resolution):
        return _("Skip; don't replace either item.") if resolution == "skip" else self.text(resolution)

    def action_label(self, resolution):
        return {"desktop": _("Replace  -->"), "device": _("<--  Replace"), "skip": _("Skip")}[resolution]


class ResolveConflictDialog(wx.Dialog):
    def __init__(self, parent, items, type_names, wording=None):
        super().__init__(parent, title=_("Resolve Conflict"))
        self.wording = wording or ConflictWording()
        self.items = [copy.copy(item) for item in items]
        self.type_names = type_names
        self.SetClientSize(dialog_size(self, RESOLVE_WIDTH, RESOLVE_HEIGHT))
        place(self, wx.StaticText, 7, 7, 264, 18, self.wording.intro)
        self.list = place(self, wx.ListCtrl, 7, 31, 264, RESOLVE_LIST_HEIGHT, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for column, (label, width) in enumerate(((_("Information Type"), 55), (_("Desktop Computer"), 76), (_("Action"), 52),
                                                  (self.wording.device_column, 76))):
            self.list.InsertColumn(column, label, width=dialog_size(self, width, 0).width)
        place(self, wx.StaticText, 7, RESOLVE_DETAIL_TOP, 130, 9, _("Desktop Computer"))
        place(self, wx.StaticText, 141, RESOLVE_DETAIL_TOP, 130, 9, self.wording.device_column)
        detail_style = wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP
        self.desktop_detail = place(self, wx.TextCtrl, 7, RESOLVE_DETAIL_TOP + 10, 130, RESOLVE_DETAIL_HEIGHT - 10, style=detail_style)
        self.device_detail = place(self, wx.TextCtrl, 141, RESOLVE_DETAIL_TOP + 10, 130, RESOLVE_DETAIL_HEIGHT - 10, style=detail_style)
        place(self, wx.StaticText, 7, RESOLVE_ACTION_TOP + 2, 24, 9, _("&Action:"))
        self.action = place(self, wx.Choice, 33, RESOLVE_ACTION_TOP, 238, 12,
                            choices=[self.wording.action_text(resolution) for resolution in RESOLUTION_ORDER])
        place(self, wx.StaticLine, 7, RESOLVE_BUTTON_TOP - 4, 264, 1)
        place(self, wx.Button, 161, RESOLVE_BUTTON_TOP, 50, 14, _("&Synchronize"), id=wx.ID_OK).SetDefault()
        place(self, wx.Button, 221, RESOLVE_BUTTON_TOP, 50, 14, _("Cancel"), id=wx.ID_CANCEL)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda event: self.show_item(event.GetIndex()))
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_cycle)
        self.list.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.on_menu)
        self.action.Bind(wx.EVT_CHOICE, self.on_action)
        self.fill()
        if self.items:
            self.list.Select(0)
            self.show_item(0)
        self.CentreOnParent()

    def fill(self):
        self.list.DeleteAllItems()
        for index, item in enumerate(self.items):
            self.list.InsertItem(index, self.type_names.get(item.object_type, item.object_type))
            self.list.SetItem(index, 1, item.desktop[0] if item.desktop else item.description)
            self.list.SetItem(index, 2, self.wording.action_label(item.resolution))
            self.list.SetItem(index, 3, item.device[0] if item.device else item.device_id)

    def selected(self):
        index = self.list.GetFirstSelected()
        return index if index >= 0 else None

    def show_item(self, index):
        item = self.items[index]
        self.desktop_detail.SetValue("\n".join(item.desktop))
        self.device_detail.SetValue("\n".join(item.device))
        self.action.SetSelection(RESOLUTION_ORDER.index(item.resolution))

    def set_resolution(self, index, resolution):
        self.items[index].resolution = resolution
        self.list.SetItem(index, 2, self.wording.action_label(resolution))
        if index == self.selected():
            self.action.SetSelection(RESOLUTION_ORDER.index(resolution))

    def on_action(self, event):
        index = self.selected()
        if index is not None:
            self.set_resolution(index, RESOLUTION_ORDER[self.action.GetSelection()])

    def on_cycle(self, event):
        index = event.GetIndex()
        current = RESOLUTION_ORDER.index(self.items[index].resolution)
        self.set_resolution(index, RESOLUTION_ORDER[(current + 1) % len(RESOLUTION_ORDER)])

    def on_menu(self, event):
        index = event.GetIndex()
        menu = wx.Menu()
        for resolution in RESOLUTION_ORDER:
            entry = menu.AppendRadioItem(wx.ID_ANY, self.wording.action_text(resolution))
            entry.Check(self.items[index].resolution == resolution)
            self.Bind(wx.EVT_MENU, lambda _, chosen=resolution: self.set_resolution(index, chosen), entry)
        self.PopupMenu(menu)
        menu.Destroy()


def resolve_items(parent, sync, wording=None, synchronize=True, default_resolution=None):
    items = sync.unresolved_items()
    if not items:
        wx.MessageBox(_("There are no unresolved items."), _("Resolve Items"), wx.OK | wx.ICON_INFORMATION, parent)
        return False
    if default_resolution in RESOLUTION_ORDER:
        for item in items:
            if item.resolution == "skip":
                item.resolution = default_resolution
    type_names = {object_type.key: _(object_type.display_name) for object_type, enabled in sync.object_types()}
    with ResolveConflictDialog(parent, items, type_names, wording) as dialog:
        if dialog.ShowModal() != wx.ID_OK:
            return False
        sync.apply_resolutions(dialog.items)
    if synchronize and any(item.resolution != "skip" for item in dialog.items):
        sync.start()
    return True


class CombineReplaceDialog(wx.Dialog):
    def __init__(self, parent, type_name, icon=None):
        super().__init__(parent, title=_("Combine or Replace"))
        self.SetClientSize(dialog_size(self, 305, 130))
        if icon is not None and icon.IsOk():
            wx.StaticBitmap(self, bitmap=icon, pos=self.ConvertDialogToPixels(wx.Point(7, 4)))
        place(self, wx.StaticText, 39, 6, 261, 23, _("The following information type on your mobile device has items that "
              "have not been synchronized with this computer before."))
        place(self, wx.StaticText, 39, 34, 58, 8, _("Information Type:"))
        place(self, wx.TextCtrl, 101, 34, 198, 9, type_name, style=wx.TE_READONLY | wx.BORDER_NONE).SetBackgroundColour(
            self.GetBackgroundColour())
        self.combine = place(self, wx.RadioButton, 39, 54, 262, 12, _("&Combine the items on my device with the items on "
                             "this computer."), style=wx.RB_GROUP)
        self.replace = place(self, wx.RadioButton, 39, 70, 262, 12, _("&Replace the items on my device with the items on "
                             "this computer."))
        self.skip = place(self, wx.RadioButton, 39, 86, 262, 12, _("Do &not synchronize this information type at this time."))
        self.combine.SetValue(True)
        place(self, wx.Button, 195, 113, 50, 14, _("OK"), id=wx.ID_OK).SetDefault()
        place(self, wx.Button, 251, 113, 50, 14, _("Cancel"), id=wx.ID_CANCEL)
        self.CentreOnScreen()

    def choice(self):
        if self.replace.GetValue():
            return FIRST_SYNC_REPLACE
        if self.skip.GetValue():
            return FIRST_SYNC_SKIP
        return FIRST_SYNC_COMBINE


def ask_combine_or_replace(parent, question, icon=None):
    with CombineReplaceDialog(parent, _(question.object_type.display_name), icon) as dialog:
        if dialog.ShowModal() != wx.ID_OK:
            return FIRST_SYNC_SKIP
        return dialog.choice()


class CombineDiscardDialog(wx.Dialog):
    def __init__(self, parent, title, device, intro, icon=None, button_tops=COMBINE_DISCARD_BUTTONS):
        wording = ConflictWording(device)
        super().__init__(parent, title=title)
        self.SetClientSize(dialog_size(self, 274, 194))
        if icon is not None and icon.IsOk():
            wx.StaticBitmap(self, bitmap=icon, pos=self.ConvertDialogToPixels(wx.Point(7, 7)))
        place(self, wx.StaticText, 57, 7, 210, 69, intro)
        place(self, wx.StaticLine, 7, 78, 258, 1)
        combine_top, discard_top, help_top = button_tops
        combine = place(self, wx.Button, 7, combine_top, 50, 14, _("&Combine"), id=wx.ID_YES)
        combine.SetDefault()
        place(self, wx.Button, 7, discard_top, 50, 14, _("&Discard"), id=wx.ID_NO)
        place(self, wx.Button, 7, help_top, 50, 14, _("&Help")).Enable(False)
        place(self, wx.StaticText, 67, 87, 200, 36, wording.text("combine"))
        place(self, wx.StaticText, 67, 124, 200, 33, wording.text("discard"))
        place(self, wx.StaticText, 67, 166, 200, 21, _("Explains these options in more detail."))
        for identifier in (wx.ID_YES, wx.ID_NO):
            self.Bind(wx.EVT_BUTTON, lambda event: self.EndModal(event.GetId()), id=identifier)
        self.CentreOnScreen()


def ask_combine_or_discard(parent, title, device, intro, icon=None, button_tops=COMBINE_DISCARD_BUTTONS):
    with CombineDiscardDialog(parent, title, device, intro, icon, button_tops) as dialog:
        result = dialog.ShowModal()
    if result == wx.ID_YES:
        return FIRST_SYNC_COMBINE
    if result == wx.ID_NO:
        return FIRST_SYNC_REPLACE
    return FIRST_SYNC_SKIP
