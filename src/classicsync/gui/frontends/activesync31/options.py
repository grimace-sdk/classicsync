import wx

from ....i18n import _
from ...branding import rebrand
from ...common.layout import dialog_size, place
from ...common.plugin_settings import change_partnership_provider, show_type_settings
from ...common.sync_runner import SYNC_MODE_CONNECT, SYNC_MODE_MANUAL
from .artwork import MANAGER

PAGE_WIDTH = 247
PAGE_HEIGHT = 225

POLICY_SKIP = "skip"
POLICY_DESKTOP_WINS = "desktop"
POLICY_DEVICE_WINS = "device"


def page_icon(page, artwork, number, x, y):
    bitmap = artwork.icon_as_bitmap(MANAGER, number, 32, lambda: wx.ArtProvider.GetBitmap(wx.ART_INFORMATION, wx.ART_MESSAGE_BOX, wx.Size(32, 32)))
    wx.StaticBitmap(page, bitmap=bitmap, pos=page.ConvertDialogToPixels(wx.Point(x, y)))


class SyncOptionsPage(wx.Panel):
    def __init__(self, parent, frontend):
        super().__init__(parent)
        self.frontend = frontend
        self.SetMinSize(dialog_size(self, PAGE_WIDTH, PAGE_HEIGHT))
        page_icon(self, frontend.artwork, 159, 10, 12)
        place(self, wx.StaticText, 42, 12, 198, 24, _("To synchronize a particular type of information, select its check box. To stop "
              "synchronization of that information, clear its check box."))
        self.types = place(self, wx.ListCtrl, 6, 44, 234, 100, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.types.EnableCheckBoxes(True)
        self.types.InsertColumn(0, _("Information Type"), width=dialog_size(self, 110, 0).width)
        self.types.InsertColumn(1, _("Status"), width=dialog_size(self, 110, 0).width)
        place(self, wx.StaticText, 7, 153, 172, 28, _("To find out more about and to customize what gets synchronized, click on that "
              "information type in the list and then click Settings."))
        self.settings_button = place(self, wx.Button, 189, 153, 50, 14, _("&Settings..."))
        self.provider_button = place(self, wx.Button, 189, 170, 50, 14, _("&Provider..."))
        self.clock = place(self, wx.CheckBox, 9, 186, 232, 10, _("Synchronize mobile device &clock upon connecting."))
        self.clock.SetValue(frontend.settings.sync_clock_on_connect)
        self.fill_types(frontend.sync.object_types())
        self.settings_button.Bind(wx.EVT_BUTTON, self.on_settings)
        self.provider_button.Bind(wx.EVT_BUTTON, self.on_provider)
        self.types.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_selection)
        self.types.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_selection)

    def fill_types(self, object_types, checked=None):
        self.object_types = object_types
        self.types.DeleteAllItems()
        for index, (object_type, enabled) in enumerate(object_types):
            enabled = checked.get(object_type.key, enabled) if checked else enabled
            self.types.InsertItem(index, _(object_type.display_name))
            self.types.SetItem(index, 1, "" if enabled else _("Synchronization Disabled"))
            self.types.CheckItem(index, enabled)
        self.on_selection(None)

    def checked_states(self):
        return {object_type.key: self.types.IsItemChecked(index) for index, (object_type, enabled) in enumerate(self.object_types)}

    def selected_type(self):
        index = self.types.GetFirstSelected()
        return self.object_types[index][0] if 0 <= index < len(self.object_types) else None

    def on_selection(self, event):
        self.settings_button.Enable(self.selected_type() is not None)

    def on_settings(self, event):
        object_type = self.selected_type()
        if object_type is not None:
            show_type_settings(self.GetTopLevelParent(), self.frontend.sync, object_type.key)

    def on_provider(self, event):
        checked = self.checked_states()
        if change_partnership_provider(self.GetTopLevelParent(), self.frontend.sync):
            self.fill_types(self.frontend.sync.object_types(), checked)

    def apply(self):
        enabled = [object_type.key for index, (object_type, _) in enumerate(self.object_types) if self.types.IsItemChecked(index)]
        self.frontend.sync.set_enabled_types(enabled)
        self.frontend.settings.sync_clock_on_connect = self.clock.GetValue()


class SyncModePage(wx.Panel):
    def __init__(self, parent, frontend):
        super().__init__(parent)
        self.frontend = frontend
        self.SetMinSize(dialog_size(self, PAGE_WIDTH, PAGE_HEIGHT))
        page_icon(self, frontend.artwork, 158, 10, 12)
        place(self, wx.StaticText, 42, 12, 196, 18, rebrand(_("Select when you want ActiveSync to synchronize information between the "
              "mobile device and desktop computer."), "activesync31"))
        place(self, wx.StaticText, 10, 42, 49, 11, _("Synchronize:"))
        self.continuous = place(self, wx.RadioButton, 10, 59, 212, 11, _("&Continuously while the device is connected"), style=wx.RB_GROUP)
        self.continuous.Enable(False)
        place(self, wx.StaticText, 21, 70, 216, 20, _("Synchronize automatically whenever the information changes on either the mobile "
              "device or desktop computer."))
        self.on_connect = place(self, wx.RadioButton, 10, 93, 216, 11, _("Only &upon connection"))
        place(self, wx.StaticText, 21, 105, 216, 20, _("Synchronize automatically each time that the mobile device is connected to the "
              "desktop computer."))
        self.manually = place(self, wx.RadioButton, 10, 128, 147, 11, _("Ma&nually"))
        place(self, wx.StaticText, 21, 140, 214, 16, _("Only synchronize information in response to clicking the Sync button on the "
              "toolbar, or clicking Synchronize on the File menu."))
        (self.on_connect if frontend.settings.sync_mode == SYNC_MODE_CONNECT else self.manually).SetValue(True)

    def apply(self):
        self.frontend.settings.sync_mode = SYNC_MODE_CONNECT if self.on_connect.GetValue() else SYNC_MODE_MANUAL


class RulesPage(wx.Panel):
    def __init__(self, parent, frontend):
        super().__init__(parent)
        self.frontend = frontend
        self.SetMinSize(dialog_size(self, PAGE_WIDTH, PAGE_HEIGHT))
        place(self, wx.StaticBox, 5, 11, 235, 101, _("Conflict Resolution"))
        page_icon(self, frontend.artwork, 160, 12, 24)
        place(self, wx.StaticText, 45, 25, 182, 19, _("If there is a conflict (an item has been changed on both the mobile device and "
              "desktop computer):"))
        self.leave = place(self, wx.RadioButton, 14, 52, 195, 17, _("&Leave the item unresolved. (Click \"Resolve items...\" to "
                           "choose which item to keep.)"), style=wx.RB_GROUP)
        self.replace_device = place(self, wx.RadioButton, 14, 72, 195, 17, _("Always replace the item on my &device"))
        self.replace_computer = place(self, wx.RadioButton, 14, 90, 195, 11, _("Always replace the item on this &computer"))
        policy = POLICY_SKIP if frontend.sync.conflict_prompt() else (frontend.sync.conflict_policy() or POLICY_SKIP)
        {POLICY_SKIP: self.leave, POLICY_DEVICE_WINS: self.replace_computer}.get(policy, self.replace_device).SetValue(True)
        place(self, wx.StaticBox, 5, 118, 235, 58, _("File Conversion"))
        page_icon(self, frontend.artwork, 6102, 12, 131)
        place(self, wx.StaticText, 45, 131, 187, 24, _("Set how files will be converted when they are copied, moved, or synchronized "
              "between this computer and your mobile device."))
        place(self, wx.Button, 152, 157, 82, 14, _("Conversion &Settings...")).Enable(False)
        self.open_on_connect = place(self, wx.CheckBox, 7, 183, 233, 12,
                                     rebrand(_("&Open ActiveSync when my mobile device connects."), "activesync31"))
        self.open_on_connect.SetValue(frontend.settings.open_on_connect)

    def apply(self):
        if self.leave.GetValue():
            policy = POLICY_SKIP
        elif self.replace_computer.GetValue():
            policy = POLICY_DEVICE_WINS
        else:
            policy = POLICY_DESKTOP_WINS
        self.frontend.sync.set_conflict_prompt("")
        self.frontend.sync.set_conflict_policy(policy)
        self.frontend.settings.open_on_connect = self.open_on_connect.GetValue()


class OptionsSheet(wx.Dialog):
    def __init__(self, parent, frontend):
        super().__init__(parent, title=_("Options"))
        self.frontend = frontend
        notebook = wx.Notebook(self)
        self.pages = [SyncOptionsPage(notebook, frontend), SyncModePage(notebook, frontend), RulesPage(notebook, frontend)]
        for page, label in zip(self.pages, (_("Sync Options"), _("Sync Mode"), _("Rules"))):
            notebook.AddPage(page, label)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(notebook, 1, wx.EXPAND | wx.ALL, 6)
        sizer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALIGN_RIGHT | wx.ALL, 6)
        self.SetSizerAndFit(sizer)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.CentreOnParent()

    def on_ok(self, event):
        for page in self.pages:
            page.apply()
        self.frontend.settings.save()
        self.EndModal(wx.ID_OK)


def show_options(parent, frontend):
    if not frontend.sync.partnership():
        wx.MessageBox(_("Connect your mobile device to change its synchronization options."), _("Options"), wx.OK | wx.ICON_INFORMATION, parent)
        return
    with OptionsSheet(parent, frontend) as dialog:
        dialog.ShowModal()
