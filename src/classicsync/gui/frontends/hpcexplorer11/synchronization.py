import wx

from ....i18n import N_, _, format_original
from ...branding import PRODUCT_NAME
from ...common.animation import AnimationPlayer, load_clip
from ...common.layout import dialog_rect, place
from ...common.plugin_settings import change_partnership_provider, show_type_settings
from ...common.sync_runner import SYNC_MODE_CONNECT, SYNC_MODE_MANUAL
from .sheet import PropertySheet

REPLICATION = "replui.dll"
PROGRESS_ANIMATION = 155

PIM_TYPES = ("calendar", "contacts", "tasks")
DATABASE_NAMES = {"calendar": N_("Appointments")}
DATABASE_DETAILS = {"calendar": N_("All appointments are synchronized."), "contacts": N_("All contacts are synchronized."),
                    "tasks": N_("All tasks are synchronized.")}

POLICY_SKIP = "skip"
POLICY_REPLACE_DEVICE = "desktop"
POLICY_REPLACE_DESKTOP = "device"
CONFLICT_ACTIONS = [(POLICY_SKIP, N_("Skip")), (POLICY_REPLACE_DEVICE, N_("Replace H/PC item")),
                    (POLICY_REPLACE_DESKTOP, N_("Replace desktop computer item"))]

STATUS_UP_TO_DATE = N_("Up-to-date")
STATUS_SYNCHRONIZING = N_("Synchronizing...")
STATUS_DISABLED = N_("Disabled")
STATUS_NOT_CONNECTED = N_("Not connected")
STATUS_ERROR = N_("Error")
STATUS_NOT_SYNCHRONIZED = N_("Not synchronized")
STATUS_NOT_AVAILABLE = N_("Not available")

STATUS_BAR_TEXT = {
    STATUS_UP_TO_DATE: N_("Synchronization: Up-to-date."),
    STATUS_SYNCHRONIZING: N_("Synchronizing..."),
    STATUS_DISABLED: N_("Synchronization: Disabled."),
    STATUS_NOT_CONNECTED: N_("Synchronization: Not connected."),
    STATUS_ERROR: N_("Synchronization: Error"),
    STATUS_NOT_SYNCHRONIZED: N_("Synchronization: Not synchronized."),
    STATUS_NOT_AVAILABLE: N_("Synchronization: Not available."),
}

CANCEL_WARNING = N_("Canceling synchronization may result in duplicate items on your H/PC the next time you synchronize. "
                    "Are you sure you want to cancel?")


def database_name(object_type):
    return _(DATABASE_NAMES[object_type.key]) if object_type.key in DATABASE_NAMES else _(object_type.display_name)


def out_of_date(count):
    return count if count else STATUS_UP_TO_DATE


def status_label(status):
    if isinstance(status, int):
        return _("1 item out-of-date") if status == 1 else format_original(_("%d items out-of-date"), status)
    return _(status) if status else ""


def type_problems(report, key):
    failures = sum(1 for action in report.actions if action.object_type == key and action.error)
    unresolved = sum(1 for action in report.unresolved if action.object_type == key)
    return failures + unresolved


def stored_problems(sync):
    partnership = sync.partnership()
    if not partnership:
        return None
    state = partnership.load_state()
    if not state.get("last_sync"):
        return None
    return {key: len(stored.get("unresolved", [])) for key, stored in state.get("types", {}).items()}


def database_status(sync, object_type, enabled, failed, progress=None):
    if not enabled:
        return STATUS_DISABLED
    if sync.running:
        return STATUS_SYNCHRONIZING if progress and progress.object_type == object_type.key else ""
    if failed:
        return STATUS_ERROR
    report = sync.last_report
    if report:
        if object_type.key in report.skipped_types:
            return STATUS_NOT_AVAILABLE
        return out_of_date(type_problems(report, object_type.key))
    stored = stored_problems(sync)
    if stored is None or object_type.key not in stored:
        return STATUS_NOT_SYNCHRONIZED
    return out_of_date(stored[object_type.key])


def overall_status(sync, connected, failed):
    if not connected:
        return STATUS_NOT_CONNECTED
    if sync.running:
        return STATUS_SYNCHRONIZING
    if not sync.partnership():
        return STATUS_DISABLED
    enabled = [object_type for object_type, enabled in sync.object_types() if enabled]
    if not enabled:
        return STATUS_DISABLED
    if failed:
        return STATUS_ERROR
    report = sync.last_report
    if report:
        return out_of_date(sum(type_problems(report, object_type.key) for object_type in enabled) + len(report.errors))
    stored = stored_problems(sync)
    if stored is None:
        return STATUS_NOT_SYNCHRONIZED
    return out_of_date(sum(stored.get(object_type.key, 0) for object_type in enabled))


def status_bar_text(status):
    if isinstance(status, int):
        if status == 1:
            return _("Synchronization: 1 item out-of-date.")
        return format_original(_("Synchronization: %d items out-of-date."), status)
    return _(STATUS_BAR_TEXT[status])


class GeneralPage:
    def __init__(self, sheet, page):
        self.sheet = sheet
        frontend = sheet.frontend
        self.clock = place(page, wx.CheckBox, 7, 11, 232, 15,
                           _("Synchronize H/PC &time with desktop computer time upon connecting."))
        self.enable = place(page, wx.CheckBox, 7, 31, 202, 10, _("&Enable Appointment, Contact, and Task synchronization."))
        self.automatic = place(page, wx.CheckBox, 18, 46, 177, 10, _("A&utomatically synchronize upon connecting."))
        place(page, wx.StaticBox, 18, 63, 225, 29, _("Status"))
        self.status = place(page, wx.StaticText, 24, 75, 135, 8, "", style=wx.ST_NO_AUTORESIZE)
        self.synchronize = place(page, wx.Button, 165, 72, 63, 14, _("&Synchronize Now"))
        place(page, wx.StaticBox, 18, 102, 225, 94, _("Conflict Resolution"))
        place(page, wx.StaticText, 24, 117, 215, 10, _("If an item has changed on both my H/PC and my desktop computer:"))
        labels = [_(label) for policy, label in CONFLICT_ACTIONS]
        self.prompt = place(page, wx.RadioButton, 24, 132, 186, 10, _("&Prompt me, and set the following as the default action:"),
                            style=wx.RB_GROUP)
        self.prompt_action = place(page, wx.Choice, 35, 144, 197, 50, choices=labels)
        self.always = place(page, wx.RadioButton, 24, 163, 190, 10, _("&Don't prompt me, and always:"))
        self.always_action = place(page, wx.Choice, 35, 175, 197, 50, choices=labels)

        self.clock.SetValue(frontend.settings.sync_clock_on_connect)
        self.automatic.SetValue(frontend.settings.sync_mode == SYNC_MODE_CONNECT)
        policy = frontend.sync.conflict_policy() or "skip"
        policies = [value for value, label in CONFLICT_ACTIONS]
        selection = policies.index(policy) if policy in policies else 1
        prompt = frontend.sync.conflict_prompt()
        self.prompt_action.SetSelection(policies.index(prompt) if prompt in policies else selection)
        self.always_action.SetSelection(selection)
        (self.prompt if prompt else self.always).SetValue(True)

        self.enable.Bind(wx.EVT_CHECKBOX, self.on_enable)
        self.synchronize.Bind(wx.EVT_BUTTON, lambda event: frontend.synchronize_now())
        for control in (self.clock, self.automatic):
            control.Bind(wx.EVT_CHECKBOX, sheet.changed)
        for control in (self.always_action, self.prompt_action):
            control.Bind(wx.EVT_CHOICE, sheet.changed)
        for control in (self.always, self.prompt):
            control.Bind(wx.EVT_RADIOBUTTON, sheet.changed)

    def on_enable(self, event):
        for key in PIM_TYPES:
            if key in self.sheet.enabled:
                self.sheet.enabled[key] = self.enable.GetValue()
        self.sheet.changed()
        self.sheet.refresh()

    def refresh(self):
        enabled = self.sheet.enabled
        self.enable.SetValue(any(enabled.get(key) for key in PIM_TYPES))
        self.automatic.Enable(any(enabled.values()))
        frontend = self.sheet.frontend
        self.status.SetLabel(status_label(overall_status(frontend.sync, frontend.connected(), frontend.sync_failed)))
        self.synchronize.Enable(frontend.can_synchronize())

    def apply(self):
        settings = self.sheet.frontend.settings
        settings.sync_clock_on_connect = self.clock.GetValue()
        settings.sync_mode = SYNC_MODE_CONNECT if self.automatic.GetValue() else SYNC_MODE_MANUAL
        sync = self.sheet.frontend.sync
        sync.set_conflict_policy(CONFLICT_ACTIONS[self.always_action.GetSelection()][0])
        sync.set_conflict_prompt(CONFLICT_ACTIONS[self.prompt_action.GetSelection()][0] if self.prompt.GetValue() else "")


class DatabasesPage:
    def __init__(self, sheet, page):
        self.sheet = sheet
        self.page = page
        place(page, wx.StaticText, 7, 7, 216, 35,
              _("The following databases can be synchronized with Microsoft Schedule+ or Microsoft Outlook on your desktop "
                "computer. To change the options for a database, select the database in the list below and click Options."))
        self.list = place(page, wx.ListCtrl, 7, 49, 159, 64, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list.InsertColumn(0, _("Name"), width=page.ConvertDialogToPixels(wx.Size(68, 0)).width)
        self.list.InsertColumn(1, _("Status"), width=page.ConvertDialogToPixels(wx.Size(84, 0)).width)
        self.options = place(page, wx.Button, 173, 48, 50, 14, _("&Options..."))
        self.provider = place(page, wx.Button, 173, 66, 50, 14, _("&Provider..."))
        self.note = place(page, wx.StaticText, 7, 120, 216, 26,
                          _("* Files (\\My Documents) is a {product} addition. H/PC Explorer 1.1 synchronized only "
                            "Appointments, Contacts, and Tasks.").format(product=PRODUCT_NAME))
        self.note.Show(any(object_type.key not in PIM_TYPES for object_type in sheet.object_types))
        self.options.Bind(wx.EVT_BUTTON, self.on_options)
        self.provider.Bind(wx.EVT_BUTTON, self.on_provider)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_options)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda event: self.options.Enable(True))
        self.list.Bind(wx.EVT_LIST_ITEM_DESELECTED, lambda event: self.options.Enable(False))
        self.options.Enable(False)

    def refresh(self):
        frontend = self.sheet.frontend
        selected = self.list.GetFirstSelected()
        self.list.DeleteAllItems()
        for index, object_type in enumerate(self.sheet.object_types):
            enabled = self.sheet.enabled[object_type.key]
            name = database_name(object_type) if object_type.key in PIM_TYPES else f"{database_name(object_type)} *"
            self.list.InsertItem(index, name)
            self.list.SetItem(index, 1, status_label(database_status(frontend.sync, object_type, enabled, frontend.sync_failed,
                                                                      frontend.sync.last_progress)))
        if 0 <= selected < self.list.GetItemCount():
            self.list.Select(selected)

    def on_options(self, event):
        index = self.list.GetFirstSelected()
        if index < 0:
            return
        object_type = self.sheet.object_types[index]
        with DatabaseOptionsDialog(self.page, object_type, self.sheet.enabled[object_type.key], self.sheet.frontend.sync) as dialog:
            if dialog.ShowModal() == wx.ID_OK and dialog.enabled() != self.sheet.enabled[object_type.key]:
                self.sheet.enabled[object_type.key] = dialog.enabled()
                self.sheet.changed()
                self.sheet.refresh()

    def on_provider(self, event):
        if change_partnership_provider(self.page.GetTopLevelParent(), self.sheet.frontend.sync):
            self.sheet.reload_object_types()
            self.sheet.refresh()

    def apply(self):
        pass


class DatabaseOptionsDialog(wx.Dialog):
    def __init__(self, parent, object_type, enabled, sync):
        super().__init__(parent, title=_("{database} Options").format(database=database_name(object_type)))
        self.SetClientSize(parent.ConvertDialogToPixels(wx.Size(200, 64)))
        self.synchronize = place(self, wx.CheckBox, 7, 9, 186, 10, _("&Synchronize {database}").format(database=database_name(object_type)))
        self.synchronize.SetValue(enabled)
        if object_type.key in DATABASE_DETAILS:
            detail = _(DATABASE_DETAILS[object_type.key])
        else:
            detail = _("Files in \\My Documents and one level of subfolders. A {product} addition.").format(product=PRODUCT_NAME)
        place(self, wx.StaticText, 18, 23, 175, 18, detail)
        settings = place(self, wx.Button, 7, 44, 50, 14, _("&Settings..."))
        settings.Bind(wx.EVT_BUTTON, lambda event: show_type_settings(self, sync, object_type.key))
        place(self, wx.Button, 89, 44, 50, 14, _("OK"), id=wx.ID_OK).SetDefault()
        place(self, wx.Button, 143, 44, 50, 14, _("Cancel"), id=wx.ID_CANCEL)
        self.CentreOnParent()

    def enabled(self):
        return self.synchronize.GetValue()


class SynchronizationManagerSheet(PropertySheet):
    def __init__(self, parent, frontend):
        super().__init__(parent, _("Synchronization Manager"))
        self.frontend = frontend
        self.enabled = {}
        self.reload_object_types()
        self.general = GeneralPage(self, self.add_page(_("General"), 250, 203))
        self.databases = DatabasesPage(self, self.add_page(_("Databases"), 250, 203))
        self.finish()
        self.refresh()
        frontend.sync.add_listener(self.on_sync_event)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.on_destroy)

    def reload_object_types(self):
        object_types = self.frontend.sync.object_types()
        self.object_types = [object_type for object_type, enabled in object_types]
        self.enabled = {object_type.key: self.enabled.get(object_type.key, enabled) for object_type, enabled in object_types}

    def refresh(self):
        self.general.refresh()
        self.databases.refresh()

    def on_sync_event(self, kind, payload):
        self.refresh()

    def on_destroy(self, event):
        if event.GetEventObject() is self:
            self.frontend.sync.remove_listener(self.on_sync_event)
        event.Skip()

    def apply(self):
        self.general.apply()
        self.databases.apply()
        self.frontend.sync.set_enabled_types([object_type.key for object_type in self.object_types if self.enabled[object_type.key]])
        self.frontend.settings.save()
        self.frontend.sync_settings_changed()
        self.refresh()


class SynchronizationProgressDialog(wx.Dialog):
    def __init__(self, parent, frontend):
        super().__init__(parent, title=_("Synchronization in Progress"), style=wx.CAPTION | wx.SYSTEM_MENU | wx.CLOSE_BOX)
        self.frontend = frontend
        self.confirming = False
        self.finished = False
        self.SetClientSize(self.ConvertDialogToPixels(wx.Size(233, 127)))
        position, size = dialog_rect(self, 10, 4, 218, 50)
        self.animation = AnimationPlayer(self, load_clip(frontend.artwork, REPLICATION, PROGRESS_ANIMATION), position, size)
        place(self, wx.StaticText, 10, 60, 218, 8, _("Now synchronizing H/PC data with desktop computer data."))
        self.gauge = place(self, wx.Gauge, 10, 74, 218, 12, 1000, style=wx.GA_SMOOTH)
        place(self, wx.StaticLine, 7, 98, 221, 1)
        self.message = place(self, wx.StaticText, 8, 105, 169, 17, _("Initializing synchronization..."), style=wx.ST_NO_AUTORESIZE)
        self.cancel = place(self, wx.Button, 182, 106, 45, 15, _("Cancel"), id=wx.ID_CANCEL)
        self.cancel.SetDefault()
        self.cancel.Bind(wx.EVT_BUTTON, self.on_cancel)
        self.Bind(wx.EVT_CLOSE, self.on_cancel)
        self.type_keys = [object_type.key for object_type, enabled in frontend.sync.object_types() if enabled]
        self.names = {object_type.key: database_name(object_type) for object_type, enabled in frontend.sync.object_types()}
        if parent:
            self.CentreOnParent()
        else:
            self.CentreOnScreen()

    def start(self):
        self.Show()
        self.animation.play()

    def update(self, progress):
        if not self.cancel.IsEnabled():
            return
        name = self.names.get(progress.object_type, progress.object_type)
        position = self.type_keys.index(progress.object_type) if progress.object_type in self.type_keys else None
        if progress.phase == "scan" and progress.object_type:
            self.message.SetLabel(format_original(_("Preparing to synchronize %s ..."), name))
        elif progress.phase == "apply" and progress.total:
            self.message.SetLabel(format_original(_("Synchronizing:  %d/%d %s."), progress.done, progress.total, name))
        elif progress.phase == "start":
            self.message.SetLabel(_("Initializing synchronization..."))
        if position is not None and self.type_keys:
            fraction = progress.done / progress.total if progress.total else 0
            self.gauge.SetValue(int(1000 * (position + fraction) / len(self.type_keys)))

    def on_cancel(self, event):
        if self.confirming or not self.cancel.IsEnabled():
            return
        self.confirming = True
        answer = wx.MessageBox(_(CANCEL_WARNING), _("Synchronization Manager"), wx.YES_NO | wx.ICON_QUESTION, self)
        self.confirming = False
        if self.finished:
            self.close()
            return
        if answer == wx.YES:
            self.message.SetLabel(_("Canceling synchronization. Please wait..."))
            self.cancel.Enable(False)
            self.frontend.sync.stop()

    def finish(self):
        self.finished = True
        if not self.confirming:
            self.close()

    def close(self):
        self.animation.stop()
        self.Destroy()
