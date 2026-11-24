import math
import threading
from pathlib import Path

import wx

from ...i18n import _
from ...sync.plugin_install import KIND_FILE, PluginError, install_plugin, load_manifest, remove_plugin
from ...paths import plugins_directory
from ...sync.plugins import ORIGIN_FILE, ORIGIN_LABELS, ORIGIN_LIBRARY, discover_plugins, load_providers, normalized_name
from ...sync.settings_schema import (
    PARTNERSHIP_OPTION_KEYS, SettingError, load_global_settings, partnership_values, provider_schema, save_global_settings,
    schema_defaults,
)
from .layout import dialog_size, place

SETTINGS_WIDTH = 240
SETTINGS_LABEL_WIDTH = 80
SETTINGS_CONTROL_LEFT = 92
SETTINGS_CONTROL_WIDTH = 140
SETTINGS_BROWSE_WIDTH = 38
SETTINGS_LIST_HEIGHT = 30
HELP_CHARACTERS_PER_LINE = 52
HELP_LINE_HEIGHT = 8

MANAGER_WIDTH = 300
MANAGER_HEIGHT = 186
MANAGER_LIST_HEIGHT = 120


def help_height(text):
    return HELP_LINE_HEIGHT * max(1, math.ceil(len(text) / HELP_CHARACTERS_PER_LINE))


def run_with_progress(parent, title, message, work):
    outcome = {}

    def worker():
        try:
            outcome["value"] = work()
        except Exception as error:
            outcome["error"] = error
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    progress = wx.ProgressDialog(title, message, parent=parent, style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE)
    try:
        while thread.is_alive():
            progress.Pulse()
            thread.join(0.1)
    finally:
        progress.Destroy()
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")


class SettingControl:
    def __init__(self, dialog, setting, value, top):
        self.setting = setting
        self.browse = None
        if setting.type == "bool":
            self.control = place(dialog, wx.CheckBox, 8, top, SETTINGS_WIDTH - 16, 10, _(setting.label))
            self.control.SetValue(bool(value))
            self.height = 12
            return
        place(dialog, wx.StaticText, 8, top + 2, SETTINGS_LABEL_WIDTH, 9, _(setting.label) + ":")
        if setting.type == "int":
            minimum = setting.minimum if setting.minimum is not None else -(2 ** 31)
            maximum = setting.maximum if setting.maximum is not None else 2 ** 31 - 1
            self.control = place(dialog, wx.SpinCtrl, SETTINGS_CONTROL_LEFT, top, 50, 12, min=minimum, max=maximum,
                                 initial=int(value or 0))
            self.height = 14
        elif setting.type == "choice":
            self.control = place(dialog, wx.Choice, SETTINGS_CONTROL_LEFT, top, SETTINGS_CONTROL_WIDTH, 12,
                                 choices=[_(label) for label in setting.choice_labels()])
            values = setting.choice_values()
            self.control.SetSelection(values.index(value) if value in values else 0)
            self.height = 14
        elif setting.type == "list":
            self.control = place(dialog, wx.TextCtrl, SETTINGS_CONTROL_LEFT, top, SETTINGS_CONTROL_WIDTH, SETTINGS_LIST_HEIGHT,
                                 "\n".join(str(item) for item in value or []), style=wx.TE_MULTILINE)
            self.height = SETTINGS_LIST_HEIGHT + 2
        elif setting.type == "path":
            width = SETTINGS_CONTROL_WIDTH - SETTINGS_BROWSE_WIDTH - 4
            self.control = place(dialog, wx.TextCtrl, SETTINGS_CONTROL_LEFT, top, width, 12, str(value or ""))
            self.browse = place(dialog, wx.Button, SETTINGS_CONTROL_LEFT + width + 4, top, SETTINGS_BROWSE_WIDTH, 12, _("Browse..."))
            self.browse.Bind(wx.EVT_BUTTON, self.on_browse)
            self.height = 14
        else:
            self.control = place(dialog, wx.TextCtrl, SETTINGS_CONTROL_LEFT, top, SETTINGS_CONTROL_WIDTH, 12, str(value or ""))
            self.height = 14

    def on_browse(self, event):
        current = self.control.GetValue().strip()
        with wx.DirDialog(self.control.GetTopLevelParent(), _(self.setting.label), str(Path(current).expanduser()) if current else "",
                          style=wx.DD_DEFAULT_STYLE) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.control.SetValue(dialog.GetPath())

    def value(self):
        if self.setting.type == "bool":
            return self.control.GetValue()
        if self.setting.type == "int":
            return self.setting.check_range(self.control.GetValue())
        if self.setting.type == "choice":
            return self.setting.choice_values()[self.control.GetSelection()]
        if self.setting.type == "list":
            return [line.strip() for line in self.control.GetValue().splitlines() if line.strip()]
        return self.control.GetValue().strip()


class ProviderSettingsDialog(wx.Dialog):
    def __init__(self, parent, provider_class, partnership=None):
        display_name = provider_class.display_name or provider_class.name
        super().__init__(parent, title=_("{provider} Settings").format(provider=display_name))
        self.provider_class = provider_class
        self.partnership = partnership
        self.options = partnership.load_options() if partnership else None
        self.schema = [setting for setting in provider_schema(provider_class) if partnership or not setting.per_device]
        self.global_values = load_global_settings(provider_class.name)
        self.inherited = {**schema_defaults(self.schema), **self.global_values}
        current = {**self.inherited, **(partnership_values(self.options) if self.options else {})}
        if partnership:
            intro = _("Settings used when {device} synchronizes with {provider}.").format(device=partnership.name, provider=display_name)
        else:
            intro = _("Settings used by {provider} for every device, unless a device has its own.").format(provider=display_name)
        place(self, wx.StaticText, 8, 8, SETTINGS_WIDTH - 16, 18, intro)
        top = 30
        self.controls = []
        if not self.schema:
            place(self, wx.StaticText, 8, top, SETTINGS_WIDTH - 16, 9, _("This provider has no settings."))
            top += 14
        for setting in self.schema:
            control = SettingControl(self, setting, current.get(setting.key), top)
            self.controls.append(control)
            top += control.height
            if setting.help:
                text = _(setting.help)
                place(self, wx.StaticText, SETTINGS_CONTROL_LEFT if setting.type != "bool" else 20, top,
                      SETTINGS_CONTROL_WIDTH if setting.type != "bool" else SETTINGS_WIDTH - 28, help_height(text), text)
                top += help_height(text) + 4
        place(self, wx.StaticLine, 8, top + 2, SETTINGS_WIDTH - 16, 1)
        place(self, wx.Button, SETTINGS_WIDTH - 112, top + 8, 50, 14, _("OK"), id=wx.ID_OK).SetDefault()
        place(self, wx.Button, SETTINGS_WIDTH - 58, top + 8, 50, 14, _("Cancel"), id=wx.ID_CANCEL)
        self.SetClientSize(dialog_size(self, SETTINGS_WIDTH, top + 28))
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.CentreOnParent()

    def values(self):
        return {control.setting.key: control.value() for control in self.controls}

    def save(self, values):
        if self.partnership is None:
            stored = {key: value for key, value in self.global_values.items() if key not in values}
            defaults = schema_defaults(self.schema)
            stored.update({key: value for key, value in values.items() if value != defaults.get(key)})
            save_global_settings(self.provider_class.name, stored)
            return
        options = self.partnership.load_options()
        for key, value in values.items():
            if key in PARTNERSHIP_OPTION_KEYS:
                setattr(options, key, value)
            elif value == self.inherited.get(key):
                options.provider_settings.pop(key, None)
            else:
                options.provider_settings[key] = value
        self.partnership.save_options(options)

    def on_ok(self, event):
        try:
            values = self.values()
        except SettingError as error:
            wx.MessageBox(str(error), self.GetTitle(), wx.OK | wx.ICON_WARNING, self)
            return
        self.save(values)
        self.EndModal(wx.ID_OK)


def show_provider_settings(parent, provider_class, partnership=None):
    with ProviderSettingsDialog(parent, provider_class, partnership) as dialog:
        return dialog.ShowModal() == wx.ID_OK


class InstallPluginDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Install Sync Provider"))
        place(self, wx.StaticText, 8, 8, 224, 26,
              _("Type the name of a package, a git+https:// address or the location of a project folder, or choose a .py or "
                ".whl file."))
        place(self, wx.StaticText, 8, 40, 30, 9, _("&Install:"))
        self.spec = place(self, wx.TextCtrl, 40, 38, 150, 12)
        browse = place(self, wx.Button, 194, 37, 38, 14, _("&Browse..."))
        browse.Bind(wx.EVT_BUTTON, self.on_browse)
        place(self, wx.Button, 128, 60, 50, 14, _("OK"), id=wx.ID_OK).SetDefault()
        place(self, wx.Button, 182, 60, 50, 14, _("Cancel"), id=wx.ID_CANCEL)
        self.SetClientSize(dialog_size(self, 240, 82))
        self.spec.SetFocus()
        self.CentreOnParent()

    def on_browse(self, event):
        with wx.FileDialog(self, _("Choose a sync plugin"), wildcard=_("Sync plugins (*.py;*.whl)|*.py;*.whl|All files (*.*)|*.*"),
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.spec.SetValue(dialog.GetPath())


class ProviderRow:
    def __init__(self, provider, source, managed_name):
        self.provider = provider
        self.source = source
        self.managed_name = managed_name


def managed_name_for(source, manifest):
    if source.origin == ORIGIN_LIBRARY:
        wanted = normalized_name(source.name)
        for entry in manifest.values():
            if entry.kind != KIND_FILE and normalized_name(entry.name) == wanted:
                return entry.name
        return source.name
    if source.origin == ORIGIN_FILE and Path(source.location).parent.resolve() == plugins_directory().resolve():
        for entry in manifest.values():
            if entry.kind == KIND_FILE and entry.file == Path(source.location).name:
                return entry.name
        return Path(source.location).stem
    return None


class SyncProviderDialog(wx.Dialog):
    def __init__(self, parent, partnership=None):
        super().__init__(parent, title=_("Sync Provider"))
        self.partnership = partnership
        self.chosen = partnership.load_options().provider if partnership else None
        if partnership:
            intro = _("Choose how {device} is synchronized with this computer.").format(device=partnership.name)
        else:
            intro = _("Sync providers installed on this computer.")
        place(self, wx.StaticText, 8, 8, MANAGER_WIDTH - 16, 9, intro)
        self.list = place(self, wx.ListCtrl, 8, 22, MANAGER_WIDTH - 70, MANAGER_LIST_HEIGHT, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list.InsertColumn(0, _("Provider"), width=self.ConvertDialogToPixels(wx.Size(70, 0)).width)
        self.list.InsertColumn(1, _("Information types"), width=self.ConvertDialogToPixels(wx.Size(80, 0)).width)
        self.list.InsertColumn(2, _("Source"), width=self.ConvertDialogToPixels(wx.Size(76, 0)).width)
        button_left = MANAGER_WIDTH - 58
        self.install_button = place(self, wx.Button, button_left, 22, 50, 14, _("&Install..."))
        self.remove_button = place(self, wx.Button, button_left, 40, 50, 14, _("&Remove"))
        self.settings_button = place(self, wx.Button, button_left, 58, 50, 14, _("&Settings..."))
        self.errors = place(self, wx.StaticText, 8, MANAGER_LIST_HEIGHT + 26, MANAGER_WIDTH - 16, 18, "")
        place(self, wx.StaticLine, 8, MANAGER_HEIGHT - 26, MANAGER_WIDTH - 16, 1)
        if partnership:
            place(self, wx.Button, MANAGER_WIDTH - 112, MANAGER_HEIGHT - 20, 50, 14, _("OK"), id=wx.ID_OK).SetDefault()
            place(self, wx.Button, MANAGER_WIDTH - 58, MANAGER_HEIGHT - 20, 50, 14, _("Cancel"), id=wx.ID_CANCEL)
            self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        else:
            place(self, wx.Button, MANAGER_WIDTH - 58, MANAGER_HEIGHT - 20, 50, 14, _("Close"), id=wx.ID_CANCEL).SetDefault()
        self.SetClientSize(dialog_size(self, MANAGER_WIDTH, MANAGER_HEIGHT))
        self.install_button.Bind(wx.EVT_BUTTON, self.on_install)
        self.remove_button.Bind(wx.EVT_BUTTON, self.on_remove)
        self.settings_button.Bind(wx.EVT_BUTTON, self.on_settings)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_selection)
        self.list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_selection)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_settings)
        self.refresh()
        self.CentreOnParent()

    def refresh(self, select=None):
        sources = discover_plugins()
        manifest = load_manifest()
        rows = {}
        for source in sources:
            for provider in source.providers:
                if getattr(provider, "name", ""):
                    rows[provider.name] = ProviderRow(provider, source, managed_name_for(source, manifest))
        self.rows = sorted(rows.values(), key=lambda row: (row.provider.display_name or row.provider.name).lower())
        self.list.DeleteAllItems()
        for index, row in enumerate(self.rows):
            provider = row.provider
            source_text = _(ORIGIN_LABELS[row.source.origin])
            if row.source.version:
                source_text = f"{source_text} {row.source.version}"
            self.list.InsertItem(index, provider.display_name or provider.name)
            self.list.SetItem(index, 1, ", ".join(object_type.display_name for object_type in provider.object_types))
            self.list.SetItem(index, 2, source_text)
        failures = [f"{source.name}: {error}" for source in sources for error in source.errors]
        self.errors.SetLabel(_("Could not load: {failures}").format(failures="; ".join(failures)) if failures else "")
        wanted = select or self.chosen
        for index, row in enumerate(self.rows):
            if row.provider.name == wanted:
                self.list.Select(index)
                self.list.Focus(index)
        self.on_selection(None)

    def selected_row(self):
        index = self.list.GetFirstSelected()
        return self.rows[index] if index >= 0 else None

    def on_selection(self, event):
        row = self.selected_row()
        self.remove_button.Enable(bool(row and row.managed_name))
        self.settings_button.Enable(row is not None)
        ok = self.FindWindow(wx.ID_OK)
        if ok:
            ok.Enable(row is not None)

    def on_install(self, event):
        with InstallPluginDialog(self) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            spec = dialog.spec.GetValue().strip()
        if not spec:
            return
        try:
            entries = run_with_progress(self, _("Install Sync Provider"), _("Installing {spec}...").format(spec=spec),
                                        lambda: install_plugin(spec))
        except (PluginError, OSError) as error:
            wx.MessageBox(str(error), _("Install Sync Provider"), wx.OK | wx.ICON_ERROR, self)
            return
        installed = [name for entry in entries for name in entry.providers]
        problems = [error for entry in entries for error in entry.errors]
        if problems:
            wx.MessageBox("\n".join(problems), _("Install Sync Provider"), wx.OK | wx.ICON_WARNING, self)
        self.refresh(installed[0] if installed else None)

    def on_remove(self, event):
        row = self.selected_row()
        if not row or not row.managed_name:
            return
        question = _("Remove {plugin}? Partnerships that synchronize with its providers will not synchronize until you choose "
                     "another provider.").format(plugin=row.managed_name)
        if wx.MessageBox(question, _("Remove Sync Provider"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self) != wx.YES:
            return
        try:
            remove_plugin(row.managed_name)
        except (PluginError, OSError) as error:
            wx.MessageBox(str(error), _("Remove Sync Provider"), wx.OK | wx.ICON_ERROR, self)
            return
        self.refresh()

    def on_settings(self, event):
        row = self.selected_row()
        if row:
            show_provider_settings(self, row.provider, self.partnership)

    def on_ok(self, event):
        row = self.selected_row()
        if row is None:
            return
        options = self.partnership.load_options()
        options.provider = row.provider.name
        self.partnership.save_options(options)
        self.chosen = row.provider.name
        self.EndModal(wx.ID_OK)


def choose_sync_provider(parent, partnership=None):
    with SyncProviderDialog(parent, partnership) as dialog:
        if dialog.ShowModal() != wx.ID_OK:
            return None
        return dialog.chosen


def show_partnership_settings(parent, partnership):
    provider_class = load_providers().get(partnership.load_options().provider)
    if provider_class is None:
        return choose_sync_provider(parent, partnership) is not None
    return show_provider_settings(parent, provider_class, partnership)
