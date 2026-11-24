import json
from dataclasses import asdict, dataclass

import wx

from ....i18n import N_, _, format_original
from ....sync import load_providers
from ...common.animation import AnimationPlayer
from ...common.layout import dialog_rect, dialog_size, place
from ...common.plugin_settings import change_partnership_provider, show_type_settings
from ...common.sync_runner import SYNC_MODE_CONNECT, SYNC_MODE_MANUAL
from ...settings import data_directory
from .artwork import SYNC_MANAGER
from .sheet import lay_out_property_sheet

PROGRESS_ANIMATION = 155

CODE_DISABLED = "disabled"
CODE_RUNNING = "running"
CODE_IDLE = ""
CODE_ERROR = "error"
CODE_NOT_INSTALLED = "not installed"
CODE_OUT_OF_DATE = "out of date"
CODE_UP_TO_DATE = "up to date"
CODE_UNKNOWN = "unknown"

POLICY_SKIP = "skip"
POLICY_REPLACE_DEVICE = "desktop"
POLICY_REPLACE_DESKTOP = "device"
CONFLICT_ACTIONS = [(POLICY_SKIP, N_("Skip")), (POLICY_REPLACE_DEVICE, N_("Replace mobile device item")),
                    (POLICY_REPLACE_DESKTOP, N_("Replace desktop computer item"))]

CANCEL_WARNING = N_("Canceling synchronization may result in duplicate items on your mobile device the next time you synchronize. "
                    "Are you sure you want to cancel?")

SERVICE_STATUS_TEXT = {CODE_DISABLED: N_("Synchronization Disabled"), CODE_RUNNING: N_("Synchronizing..."),
                       CODE_ERROR: N_("Synchronization Error"), CODE_NOT_INSTALLED: N_("Not Installed"),
                       CODE_UP_TO_DATE: N_("Up-to-date")}
DEVICE_STATUS_TEXT = {CODE_DISABLED: N_("Disabled"), CODE_RUNNING: N_("Synchronizing..."), CODE_ERROR: N_("Error"),
                      CODE_UP_TO_DATE: N_("Up-to-date")}
STATUS_WINDOW_TEXT = {CODE_DISABLED: N_("Connected, synchronization disabled"), CODE_RUNNING: N_("Synchronizing..."),
                      CODE_ERROR: N_("Synchronization Error"), CODE_UP_TO_DATE: N_("Up-to-date.")}


@dataclass
class SyncDisplaySettings:
    show_progress: bool = True
    show_errors: bool = True

    @classmethod
    def path(cls):
        return data_directory() / "ceservices22.json"

    @classmethod
    def load(cls):
        try:
            stored = json.loads(cls.path().read_text())
        except (OSError, ValueError):
            return cls()
        known = {name: value for name, value in stored.items() if name in cls.__dataclass_fields__}
        return cls(**known)

    def save(self):
        path = self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))


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


def service_status(sync, object_type, enabled, failed, progress=None):
    if not enabled:
        return CODE_DISABLED, 0
    if sync.running:
        return (CODE_RUNNING if progress and progress.object_type == object_type.key else CODE_IDLE), 0
    if failed:
        return CODE_ERROR, 0
    report = sync.last_report
    if report:
        if object_type.key in report.skipped_types:
            return CODE_NOT_INSTALLED, 0
        problems = type_problems(report, object_type.key)
        return (CODE_OUT_OF_DATE, problems) if problems else (CODE_UP_TO_DATE, 0)
    stored = stored_problems(sync)
    if stored is None or object_type.key not in stored:
        return CODE_UNKNOWN, 0
    return (CODE_OUT_OF_DATE, stored[object_type.key]) if stored[object_type.key] else (CODE_UP_TO_DATE, 0)


def partnership_status(sync, failed):
    if sync.running:
        return CODE_RUNNING, 0
    if not sync.partnership():
        return CODE_UNKNOWN, 0
    enabled = [object_type for object_type, enabled in sync.object_types() if enabled]
    if not enabled:
        return CODE_DISABLED, 0
    if failed:
        return CODE_ERROR, 0
    report = sync.last_report
    if report:
        problems = sum(type_problems(report, object_type.key) for object_type in enabled) + len(report.errors)
        return (CODE_OUT_OF_DATE, problems) if problems else (CODE_UP_TO_DATE, 0)
    stored = stored_problems(sync)
    if stored is None:
        return CODE_UNKNOWN, 0
    problems = sum(stored.get(object_type.key, 0) for object_type in enabled)
    return (CODE_OUT_OF_DATE, problems) if problems else (CODE_UP_TO_DATE, 0)


def service_status_text(status):
    code, count = status
    if code == CODE_OUT_OF_DATE:
        return _("1 item out-of-date") if count == 1 else format_original(_("%d items out-of-date"), count)
    return _(SERVICE_STATUS_TEXT[code]) if code in SERVICE_STATUS_TEXT else ""


def device_status_text(status):
    code, count = status
    if code == CODE_OUT_OF_DATE:
        return format_original(_("%d items need updating"), count)
    return _(DEVICE_STATUS_TEXT.get(code, N_("Guest")))


def status_window_text(status):
    code, count = status
    if code == CODE_OUT_OF_DATE:
        return _("1 item out-of-date.") if count == 1 else format_original(_("%d items out-of-date."), count)
    return _(STATUS_WINDOW_TEXT.get(code, N_("Synchronization Status Unknown")))


def progress_text(progress, display_name):
    if progress.phase == "apply" and progress.total:
        percent = 100 * progress.done // progress.total
        return format_original(_("Updating %1!d! %2 (%3!d!%% done)"), progress.total, display_name, percent)
    if progress.phase == "scan" and progress.object_type:
        return format_original(_("Preparing to synchronize %s ..."), display_name)
    if progress.phase == "start":
        return _("Initializing ActiveSync...")
    return None


def provider_display_name(sync):
    partnership = sync.partnership()
    name = partnership.load_options().provider if partnership else "folder"
    provider = load_providers().get(name)
    return getattr(provider, "display_name", None) or name


class ProgressTracker:
    def __init__(self, sync):
        self.type_keys = [object_type.key for object_type, enabled in sync.object_types() if enabled]
        self.names = {object_type.key: _(object_type.display_name) for object_type, enabled in sync.object_types()}

    def fraction(self, progress):
        if progress.object_type not in self.type_keys:
            return None
        position = self.type_keys.index(progress.object_type)
        done = progress.done / progress.total if progress.total else 0
        return (position + done) / len(self.type_keys)

    def text(self, progress):
        return progress_text(progress, self.names.get(progress.object_type, progress.object_type))


class AdvancedOptionsDialog(wx.Dialog):
    def __init__(self, parent, name, policy, display_settings, prompt=""):
        super().__init__(parent, title=format_original(_("%s Advanced ActiveSync Options"), name) if name
                         else _("Advanced ActiveSync Options"))
        self.SetClientSize(dialog_size(self, 239, 220))
        place(self, wx.StaticBox, 7, 7, 225, 81, _("Conflict resolution rules"))
        place(self, wx.StaticText, 14, 20, 215, 10, _("If an item changes on both computers:"))
        labels = [_(label) for policy, label in CONFLICT_ACTIONS]
        self.prompt = place(self, wx.RadioButton, 14, 34, 154, 10, _("&Prompt me with the following default action:"),
                            style=wx.RB_GROUP)
        self.prompt_action = place(self, wx.Choice, 14, 44, 197, 50, choices=labels)
        self.always = place(self, wx.RadioButton, 14, 61, 190, 10, _("&Don't prompt me, and always:"))
        self.always_action = place(self, wx.Choice, 14, 71, 197, 50, choices=labels)
        policies = [value for value, _ in CONFLICT_ACTIONS]
        selection = policies.index(policy) if policy in policies else 1
        self.prompt_action.SetSelection(policies.index(prompt) if prompt in policies else selection)
        self.always_action.SetSelection(selection)
        (self.prompt if prompt else self.always).SetValue(True)
        place(self, wx.StaticBox, 7, 91, 225, 39, _("Messages"))
        self.hide_progress = place(self, wx.CheckBox, 14, 104, 212, 8, _("D&on't show ActiveSync progress during synchronization."))
        self.hide_errors = place(self, wx.CheckBox, 14, 116, 212, 8, _("Do&n't show ActiveSync errors during synchronization."))
        self.hide_progress.SetValue(not display_settings.show_progress)
        self.hide_errors.SetValue(not display_settings.show_errors)
        place(self, wx.StaticBox, 7, 134, 225, 58, _("Duplicate resolution"))
        place(self, wx.StaticText, 13, 148, 211, 20, _("Click Remove Duplicates to remove any duplicate items found by "
              "synchronization service providers on the desktop computer."))
        place(self, wx.Button, 77, 172, 72, 14, _("&Remove Duplicates")).Enable(False)
        place(self, wx.Button, 126, 199, 50, 14, _("OK"), id=wx.ID_OK).SetDefault()
        place(self, wx.Button, 182, 199, 50, 14, _("Cancel"), id=wx.ID_CANCEL)
        self.CentreOnParent()

    def policy(self):
        return CONFLICT_ACTIONS[self.always_action.GetSelection()][0]

    def prompt_default(self):
        return CONFLICT_ACTIONS[self.prompt_action.GetSelection()][0] if self.prompt.GetValue() else ""

    def show_progress(self):
        return not self.hide_progress.GetValue()

    def show_errors(self):
        return not self.hide_errors.GetValue()


class GeneralPage(wx.Panel):
    def __init__(self, parent, sheet):
        super().__init__(parent)
        self.sheet = sheet
        frontend = sheet.frontend
        self.SetMinSize(dialog_size(self, 250, 222))
        self.clock = place(self, wx.CheckBox, 7, 3, 232, 10, _("Synchronize mobile device &clock upon connecting"))
        place(self, wx.StaticBox, 7, 16, 232, 52, _("Synchronization"))
        self.enable = place(self, wx.CheckBox, 19, 28, 93, 10, _("&Enable synchronization"))
        self.on_connect = place(self, wx.CheckBox, 34, 41, 177, 10, _("A&utomatically synchronize upon connecting"))
        self.continuous = place(self, wx.CheckBox, 34, 54, 177, 10, _("Auto&matically synchronize if data is out of date"))
        self.continuous.Enable(False)
        place(self, wx.StaticBox, 7, 71, 232, 146, _("Synchronization &services"))
        self.services = place(self, wx.ListCtrl, 13, 82, 218, 84, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.services.EnableCheckBoxes(True)
        self.services.InsertColumn(0, _("Name"), width=dialog_size(self, 110, 0).width)
        self.services.InsertColumn(1, _("Status"), width=dialog_size(self, 100, 0).width)
        place(self, wx.StaticText, 13, 169, 215, 33,
              _("Click the check box next to a service type and click OK to enable or disable that service.  A check indicates "
                "that the service type is enabled.  Select an enabled service and click Options to change settings for that "
                "service type."))
        self.options = place(self, wx.Button, 120, 199, 50, 14, _("&Options..."))
        self.advanced = place(self, wx.Button, 180, 199, 50, 14, _("Ad&vanced..."))
        self.provider = place(self, wx.Button, 180, 26, 50, 14, _("&Provider..."))

        enabled = {object_type.key: state for object_type, state in frontend.sync.object_types()}
        self.clock.SetValue(frontend.settings.sync_clock_on_connect)
        self.on_connect.SetValue(frontend.settings.sync_mode == SYNC_MODE_CONNECT)
        self.enable.SetValue(any(enabled.values()))
        self.fill_services(frontend.sync.object_types())
        self.enable.Bind(wx.EVT_CHECKBOX, self.on_enable)
        self.services.Bind(wx.EVT_LIST_ITEM_CHECKED, self.on_service_checked)
        self.services.Bind(wx.EVT_LIST_ITEM_UNCHECKED, self.on_service_checked)
        self.services.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda event: self.update_options_button())
        self.services.Bind(wx.EVT_LIST_ITEM_DESELECTED, lambda event: self.update_options_button())
        self.options.Bind(wx.EVT_BUTTON, self.on_options)
        self.advanced.Bind(wx.EVT_BUTTON, lambda event: sheet.show_advanced())
        self.provider.Bind(wx.EVT_BUTTON, self.on_provider)

    def fill_services(self, object_types, checked=None):
        self.object_types = [object_type for object_type, state in object_types]
        self.services.DeleteAllItems()
        for index, (object_type, state) in enumerate(object_types):
            self.services.InsertItem(index, _(object_type.display_name))
            self.services.CheckItem(index, checked.get(object_type.key, state) if checked else state)
        self.refresh()

    def selected_index(self):
        index = self.services.GetFirstSelected()
        return index if 0 <= index < len(self.object_types) else None

    def update_options_button(self):
        index = self.selected_index()
        self.options.Enable(self.enable.GetValue() and index is not None and self.services.IsItemChecked(index))

    def on_options(self, event):
        index = self.selected_index()
        if index is not None:
            show_type_settings(self.GetTopLevelParent(), self.sheet.frontend.sync, self.object_types[index].key)

    def on_provider(self, event):
        checked = {object_type.key: self.services.IsItemChecked(index) for index, object_type in enumerate(self.object_types)}
        if change_partnership_provider(self.GetTopLevelParent(), self.sheet.frontend.sync):
            self.fill_services(self.sheet.frontend.sync.object_types(), checked)

    def checked_keys(self):
        return [object_type.key for index, object_type in enumerate(self.object_types) if self.services.IsItemChecked(index)]

    def on_enable(self, event):
        if self.enable.GetValue() and not self.checked_keys():
            for index in range(len(self.object_types)):
                self.services.CheckItem(index, True)
        self.refresh()

    def on_service_checked(self, event):
        self.refresh()
        event.Skip()

    def refresh(self):
        frontend = self.sheet.frontend
        enabled = self.enable.GetValue()
        self.on_connect.Enable(enabled)
        self.services.Enable(enabled)
        checked = set(self.checked_keys())
        for index, object_type in enumerate(self.object_types):
            status = service_status(frontend.sync, object_type, enabled and object_type.key in checked, frontend.sync_failed,
                                    frontend.sync.last_progress)
            self.services.SetItem(index, 1, service_status_text(status))
        self.update_options_button()

    def apply(self):
        settings = self.sheet.frontend.settings
        settings.sync_clock_on_connect = self.clock.GetValue()
        settings.sync_mode = SYNC_MODE_CONNECT if self.on_connect.GetValue() else SYNC_MODE_MANUAL
        self.sheet.frontend.sync.set_enabled_types(self.checked_keys() if self.enable.GetValue() else [])


class ActiveSyncOptionsSheet(wx.Dialog):
    def __init__(self, parent, frontend):
        name = frontend.application.device_name(frontend.service.announcement)
        super().__init__(parent, title=format_original(_("%s ActiveSync Options"), name) if name else _("ActiveSync Options"))
        self.frontend = frontend
        self.device_name = name
        self.policy = frontend.sync.conflict_policy() or "skip"
        self.prompt = frontend.sync.conflict_prompt()
        self.display_settings = frontend.sync_display
        self.show_progress = self.display_settings.show_progress
        self.show_errors = self.display_settings.show_errors
        self.SetIcons(frontend.artwork.application_icons())
        self.notebook = wx.Notebook(self)
        self.general = GeneralPage(self.notebook, self)
        self.notebook.AddPage(self.general, _("General"))
        lay_out_property_sheet(self, self.notebook)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.Bind(wx.EVT_BUTTON, lambda event: self.apply(), id=wx.ID_APPLY)
        frontend.sync.add_listener(self.on_sync_event)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.on_destroy)
        self.CentreOnParent()

    def on_sync_event(self, kind, payload):
        self.general.refresh()

    def on_destroy(self, event):
        if event.GetEventObject() is self:
            self.frontend.sync.remove_listener(self.on_sync_event)
        event.Skip()

    def show_advanced(self):
        settings = SyncDisplaySettings(self.show_progress, self.show_errors)
        with AdvancedOptionsDialog(self, self.device_name, self.policy, settings, self.prompt) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.policy = dialog.policy()
                self.prompt = dialog.prompt_default()
                self.show_progress = dialog.show_progress()
                self.show_errors = dialog.show_errors()

    def apply(self):
        self.general.apply()
        self.frontend.sync.set_conflict_policy(self.policy)
        self.frontend.sync.set_conflict_prompt(self.prompt)
        self.frontend.settings.save()
        self.display_settings.show_progress = self.show_progress
        self.display_settings.show_errors = self.show_errors
        self.display_settings.save()
        self.frontend.sync_settings_changed()

    def on_ok(self, event):
        self.apply()
        self.EndModal(wx.ID_OK)


class SynchronizationProgressDialog(wx.Dialog):
    def __init__(self, parent, frontend):
        super().__init__(parent, title=_("Synchronization in Progress"), style=wx.CAPTION | wx.SYSTEM_MENU | wx.CLOSE_BOX)
        self.frontend = frontend
        self.tracker = ProgressTracker(frontend.sync)
        self.confirming = False
        self.finished = False
        self.SetClientSize(dialog_size(self, 233, 127))
        position, size = dialog_rect(self, 10, 4, 218, 50)
        self.animation = AnimationPlayer(self, frontend.artwork.animation(SYNC_MANAGER, PROGRESS_ANIMATION), position, size)
        place(self, wx.StaticText, 10, 60, 218, 8, _("Now synchronizing mobile device data with desktop computer data."))
        self.gauge = place(self, wx.Gauge, 10, 74, 218, 12, 1000, style=wx.GA_SMOOTH)
        place(self, wx.StaticLine, 7, 98, 221, 1)
        self.message = place(self, wx.StaticText, 8, 105, 169, 17, _("Initializing ActiveSync..."), style=wx.ST_NO_AUTORESIZE)
        self.cancel = place(self, wx.Button, 182, 106, 45, 15, _("Cancel"), id=wx.ID_CANCEL)
        self.cancel.SetDefault()
        self.cancel.Bind(wx.EVT_BUTTON, self.on_cancel)
        self.Bind(wx.EVT_CLOSE, self.on_cancel)
        self.CentreOnScreen()

    def start(self):
        self.Show()
        self.animation.play()

    def update(self, progress):
        if not self.cancel.IsEnabled():
            return
        text = self.tracker.text(progress)
        if text:
            self.message.SetLabel(text)
        fraction = self.tracker.fraction(progress)
        if fraction is not None:
            self.gauge.SetValue(int(1000 * fraction))

    def on_cancel(self, event):
        if self.confirming or not self.cancel.IsEnabled():
            return
        self.confirming = True
        answer = wx.MessageBox(_(CANCEL_WARNING), _("ActiveSync"), wx.YES_NO | wx.ICON_QUESTION, self)
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
