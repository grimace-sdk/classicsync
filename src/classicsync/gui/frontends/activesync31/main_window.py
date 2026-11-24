import wx
import wx.adv

from ....i18n import N_, _, format_original
from ...branding import rebrand, title
from ...common.layout import bold, dialog_size, place
from ...service import STATE_CONNECTED, STATE_CONNECTING, STATE_DISABLED, STATE_WAITING

TITLE = title("activesync31")

ID_SYNCHRONIZE = 10003
ID_STOP = 10005
ID_EXPLORE = 10022
ID_DELETE_PARTNERSHIP = 9000
ID_MOBILE_DEVICE_PLACEHOLDER = 8000
ID_GET_CONNECTED = 10041
ID_CONNECTION_SETTINGS = 10040
ID_TOOLBAR_LARGE = 10036
ID_TOOLBAR_SMALL = 10037
ID_TOOLBAR_NONE = 10038
ID_DETAILS = 10024
ID_OPTIONS = 10034
ID_RESOLVE = 10025
ID_BACKUP_RESTORE = 10030
ID_ADD_REMOVE_PROGRAMS = 10031
ID_HELP = 10008
ID_REFRESH = 10039

FRONTEND_KEY = "activesync31"

STATUS_TEXT = {
    STATE_CONNECTED: N_("Connected"),
    STATE_CONNECTING: N_("Connecting..."),
    STATE_WAITING: N_("Not connected"),
    STATE_DISABLED: N_("Connection disabled"),
}

TOOLBAR_BUTTONS = [
    (ID_SYNCHRONIZE, N_("Sync"), N_("Synchronize your data now.\nStart Synchronization")),
    (ID_STOP, N_("Stop"), N_("Stop synchronization now.\nStop Synchronization")),
    (ID_DETAILS, N_("Details"), N_("Show or hide details\nOpen/Close Detail Pane")),
    (ID_EXPLORE, N_("Explore"), N_("Explore device.\nExplore Device")),
    (ID_OPTIONS, N_("Options"), N_("Show sync. settings.\nChange Options")),
]

UNAVAILABLE = {ID_HELP}
ID_PARTNERSHIP_FIRST = 8001
CONFIRM_DELETE_TITLE = N_("Confirm Partnership Deletion")
CONFIRM_DELETE_TEXT = N_("Deleting the selected partnership deletes all device-specific information from this computer. However, "
                         "any existing backup file for this partnership will not be deleted.\n\nAre you sure you want to "
                         "delete this partnership?")
SYNC_COMMANDS = (ID_SYNCHRONIZE, ID_STOP, ID_OPTIONS)


def command_prompt(identifier):
    for button_identifier, _label, prompt in TOOLBAR_BUTTONS:
        if button_identifier == identifier:
            return _(prompt).split("\n")[0]
    return ""


def items_not_synchronized(count):
    if count == 1:
        return _("1 item not synchronized")
    return format_original(_("%1!d! items not synchronized"), count)


def last_synchronized(moment):
    return format_original(_("Last Synchronized %1!s! %2!s!"), f"{moment:%d/%m/%Y}", f"{moment:%H:%M}")


class StatusPanel(wx.Panel):
    def __init__(self, parent, artwork):
        super().__init__(parent, style=wx.BORDER_SUNKEN)
        self.artwork = artwork
        self.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))
        self.name = bold(place(self, wx.StaticText, 3, 1, 190, 13, "", style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END), 1.2)
        place(self, wx.StaticLine, 3, 16, 219, 1)
        self.line_one = place(self, wx.StaticText, 3, 20, 187, 8, "", style=wx.ST_NO_AUTORESIZE)
        self.line_two = place(self, wx.StaticText, 3, 31, 187, 8, "", style=wx.ST_NO_AUTORESIZE)
        self.line_three = place(self, wx.StaticText, 3, 41, 187, 8, "", style=wx.ST_NO_AUTORESIZE)
        position, size = self.ConvertDialogToPixels(wx.Point(3, 40)), self.ConvertDialogToPixels(wx.Size(60, 10))
        self.resolve_link = wx.adv.HyperlinkCtrl(self, wx.ID_ANY, _("Resolve items..."), "", pos=position, size=size,
                                                 style=wx.adv.HL_ALIGN_LEFT | wx.BORDER_NONE)
        self.resolve_link.SetBackgroundColour(self.GetBackgroundColour())
        self.resolve_link.Hide()
        self.progress = place(self, wx.Gauge, 3, 54, 155, 8, 100, style=wx.GA_SMOOTH)
        self.progress.Hide()
        position = self.ConvertDialogToPixels(wx.Point(195, 7))
        self.state_bitmap = wx.StaticBitmap(self, bitmap=artwork.state_bitmap("waiting"), pos=position)
        self.SetMinSize(dialog_size(self, 233, 64))

    def show_progress(self, fraction):
        if fraction is None:
            self.progress.Hide()
            return
        self.progress.SetValue(max(0, min(100, int(fraction * 100))))
        self.progress.Show()

    def show(self, name, line_one, line_two="", line_three="", state="waiting", resolve_link=False):
        self.name.SetLabel(name)
        self.line_one.SetLabel(line_one)
        self.line_two.SetLabel(line_two)
        self.line_three.SetLabel("" if resolve_link else line_three)
        self.line_three.Show(not resolve_link)
        self.resolve_link.Show(resolve_link)
        self.state_bitmap.SetBitmap(self.artwork.state_bitmap(state))


class MainWindow(wx.Frame):
    def __init__(self, application):
        super().__init__(None, title=TITLE, style=wx.DEFAULT_FRAME_STYLE)
        self.application = application
        self.settings = application.settings
        self.selected_partnership = None
        self.artwork = application.artwork
        self.SetIcons(self.artwork.application_icons())
        self._build_menu()
        self.toolbar = None
        self._build_toolbar()
        self._build_body()
        self.CreateStatusBar()
        self.SetAcceleratorTable(wx.AcceleratorTable([
            (wx.ACCEL_NORMAL, wx.WXK_F5, ID_REFRESH),
            (wx.ACCEL_NORMAL, wx.WXK_F9, ID_SYNCHRONIZE),
        ]))
        self.Bind(wx.EVT_MENU, self.on_command)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_MENU_HIGHLIGHT_ALL, self.on_menu_highlight)
        self.Bind(wx.EVT_MENU_OPEN, self.on_menu_open)
        self.status_panel.resolve_link.Bind(wx.adv.EVT_HYPERLINK, lambda event: self.application.show_resolve_items(self))
        self._apply_details()
        self._restore_placement()
        self.update_state(application.service.state, application.service.announcement, application.service.error)

    def _build_menu(self):
        menu_bar = wx.MenuBar()
        file_menu = wx.Menu()
        file_menu.Append(ID_SYNCHRONIZE, _("&Synchronize") + "\tF9", command_prompt(ID_SYNCHRONIZE))
        file_menu.Append(ID_STOP, _("S&top"), command_prompt(ID_STOP))
        file_menu.AppendSeparator()
        self.mobile_device_menu = wx.Menu()
        self.mobile_device_menu.Append(ID_MOBILE_DEVICE_PLACEHOLDER, _("No partnerships")).Enable(False)
        file_menu.AppendSubMenu(self.mobile_device_menu, _("&Mobile Device"))
        file_menu.Append(ID_EXPLORE, _("&Explore"), command_prompt(ID_EXPLORE))
        file_menu.Append(ID_DELETE_PARTNERSHIP, _("&Delete Partnership"))
        file_menu.AppendSeparator()
        file_menu.Append(ID_GET_CONNECTED, _("&Get Connected..."))
        file_menu.Append(ID_CONNECTION_SETTINGS, _("&Connection Settings..."))
        file_menu.AppendSeparator()
        file_menu.Append(wx.ID_CLOSE, _("C&lose"))
        menu_bar.Append(file_menu, _("&File"))

        view_menu = wx.Menu()
        toolbar_menu = wx.Menu()
        toolbar_menu.AppendRadioItem(ID_TOOLBAR_LARGE, _("Lar&ge Icons"))
        toolbar_menu.AppendRadioItem(ID_TOOLBAR_SMALL, _("S&mall Icons"))
        toolbar_menu.AppendRadioItem(ID_TOOLBAR_NONE, _("&None"))
        toolbar_menu.Check({"large": ID_TOOLBAR_LARGE, "small": ID_TOOLBAR_SMALL}.get(self.settings.toolbar_style, ID_TOOLBAR_NONE), True)
        view_menu.AppendSubMenu(toolbar_menu, _("&Toolbar"))
        view_menu.AppendCheckItem(ID_DETAILS, _("&Details"), command_prompt(ID_DETAILS)).Check(self.settings.show_details)
        menu_bar.Append(view_menu, _("&View"))

        tools_menu = wx.Menu()
        tools_menu.Append(ID_OPTIONS, _("&Options..."), command_prompt(ID_OPTIONS))
        tools_menu.AppendSeparator()
        tools_menu.Append(ID_RESOLVE, _("&Resolve Items..."))
        tools_menu.AppendSeparator()
        tools_menu.Append(ID_BACKUP_RESTORE, _("&Backup/Restore..."))
        tools_menu.Append(ID_ADD_REMOVE_PROGRAMS, _("Add/Re&move Programs..."))
        menu_bar.Append(tools_menu, _("&Tools"))

        help_menu = wx.Menu()
        help_menu.Append(ID_HELP, rebrand(_("&Microsoft ActiveSync Help"), FRONTEND_KEY) + "\tF1")
        help_menu.AppendSeparator()
        help_menu.Append(wx.ID_ABOUT, rebrand(_("&About Microsoft ActiveSync"), FRONTEND_KEY))
        menu_bar.Append(help_menu, _("&Help"))
        self.SetMenuBar(menu_bar)
        for identifier in UNAVAILABLE:
            menu_bar.Enable(identifier, False)

    def _build_toolbar(self):
        if self.toolbar:
            self.toolbar.Destroy()
            self.toolbar = None
            self.SetToolBar(None)
        if self.settings.toolbar_style == "none":
            self.Layout()
            return
        large = self.settings.toolbar_style == "large"
        self.toolbar = self.CreateToolBar(wx.TB_HORIZONTAL | wx.TB_FLAT | wx.TB_TEXT | wx.TB_NODIVIDER)
        bitmaps = self.artwork.toolbar_bitmaps(large)
        for (identifier, label, prompt), bitmap in zip(TOOLBAR_BUTTONS, bitmaps):
            long_help, short_help = _(prompt).split("\n", 1)
            kind = wx.ITEM_CHECK if identifier == ID_DETAILS else wx.ITEM_NORMAL
            self.toolbar.AddTool(identifier, _(label), bitmap, short_help, kind)
            self.toolbar.SetToolLongHelp(identifier, long_help)
        self.toolbar.Realize()
        self.toolbar.ToggleTool(ID_DETAILS, self.settings.show_details)
        for identifier in UNAVAILABLE:
            self.toolbar.EnableTool(identifier, False)
        self.toolbar.EnableTool(ID_EXPLORE, self.application.service.state == STATE_CONNECTED)
        self.Layout()

    def _build_body(self):
        self.body = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.status_panel = StatusPanel(self.body, self.artwork)
        sizer.Add(self.status_panel, 0, wx.EXPAND | wx.ALL, 6)
        self.details = wx.ListCtrl(self.body, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.details.InsertColumn(0, _("Information Type"), width=self.ConvertDialogToPixels(wx.Size(110, 0)).width)
        self.details.InsertColumn(1, _("Status"), width=self.ConvertDialogToPixels(wx.Size(110, 0)).width)
        sizer.Add(self.details, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        self.body.SetSizer(sizer)

    def _apply_details(self):
        self.details.Show(self.settings.show_details)
        self.body.Layout()
        self.Fit()
        if self.settings.show_details:
            self.SetSize(self.GetSize().width, max(self.GetSize().height, self.ConvertDialogToPixels(wx.Size(0, 250)).height))
        self.SetMinSize(self.GetSize() if not self.settings.show_details else wx.Size(self.GetSize().width, 300))

    def _restore_placement(self):
        rect = self.settings.window_rect
        if len(rect) == 4:
            self.SetPosition(wx.Point(rect[0], rect[1]))
            if self.settings.show_details:
                self.SetSize(wx.Size(rect[2], rect[3]))
        else:
            self.Centre()

    def partnerships(self):
        return self.application.application.partnerships()

    def shown_partnership(self):
        connected = self.application.service.state == STATE_CONNECTED
        if connected:
            return self.application.application.partnership
        partnerships = self.partnerships()
        directories = [partnership.directory for partnership in partnerships]
        if self.selected_partnership and self.selected_partnership.directory in directories:
            return self.selected_partnership
        return partnerships[0] if partnerships else None

    def rebuild_mobile_device_menu(self):
        menu = self.mobile_device_menu
        for item in list(menu.GetMenuItems()):
            menu.Delete(item)
        partnerships = self.partnerships()
        shown = self.shown_partnership()
        if not partnerships:
            menu.Append(ID_MOBILE_DEVICE_PLACEHOLDER, _("No partnerships")).Enable(False)
            return
        connected = self.application.service.state == STATE_CONNECTED
        for index, partnership in enumerate(partnerships):
            item = menu.AppendRadioItem(ID_PARTNERSHIP_FIRST + index, partnership.name)
            item.Check(shown is not None and partnership.directory == shown.directory)
            item.Enable(not connected)

    def on_menu_open(self, event):
        if event.GetMenu() is self.mobile_device_menu or event.GetMenu() is self.GetMenuBar().GetMenu(0):
            self.rebuild_mobile_device_menu()
        event.Skip()

    def update_state(self, state, announcement, error):
        connected = state == STATE_CONNECTED
        self.rebuild_mobile_device_menu()
        if connected:
            self.update_connected(announcement)
            return
        self.status_panel.show_progress(None)
        shown = self.shown_partnership()
        name = shown.name if shown else _("No partnerships")
        if state == STATE_DISABLED:
            line_two = _("Connections are disabled. Use Connection Settings to choose a port.")
        else:
            line_two = _("Waiting for device on {port}").format(port=self.settings.serial_port) if self.settings.serial_port else ""
        if shown and shown.load_state().get("last_sync"):
            line_two = self.last_synchronized_text(shown)
        line_three = error if error and not connected else ""
        bitmap_state = {STATE_CONNECTED: "connected", STATE_CONNECTING: "connecting", STATE_DISABLED: "disabled"}.get(state, "waiting")
        self.status_panel.show(name, _(STATUS_TEXT[state]) if state in STATUS_TEXT else "", line_two, line_three, bitmap_state)
        self._enable_commands(False)
        self.details.DeleteAllItems()

    def last_synchronized_text(self, partnership):
        from datetime import datetime, timezone
        stamp = partnership.load_state().get("last_sync")
        if not stamp:
            return ""
        moment = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone()
        return last_synchronized(moment)

    def _enable_commands(self, connected):
        sync = self.application.sync
        running = sync.running
        partnered = connected and sync.partnership() is not None
        backing_up = self.application.application.backup.running
        states = {ID_EXPLORE: connected, ID_SYNCHRONIZE: partnered and not running and not backing_up, ID_STOP: running,
                  ID_OPTIONS: partnered, ID_BACKUP_RESTORE: connected and not running and not backing_up}
        for identifier, enabled in states.items():
            self.GetMenuBar().Enable(identifier, enabled)
            if self.toolbar and self.toolbar.FindById(identifier):
                self.toolbar.EnableTool(identifier, enabled)
        self.GetMenuBar().Enable(ID_RESOLVE, partnered and not running and bool(sync.unresolved_items()))
        self.GetMenuBar().Enable(ID_DELETE_PARTNERSHIP, not running and self.shown_partnership() is not None)

    def update_connected(self, announcement, progress=None):
        sync = self.application.sync
        partnership = sync.partnership()
        last_sync, last_result = sync.last_sync() if partnership else (None, "")
        name = partnership.name if partnership else _("Guest")
        unresolved = len(sync.unresolved_items()) if partnership and not sync.running else 0
        if sync.running:
            line_one = _("Synchronizing...")
            line_two = progress.message if progress and progress.message else ""
            if progress and progress.total == 1:
                line_two = format_original(_("%1!s!: %2!d! of 1 item completed"), progress.object_type, progress.done)
            elif progress and progress.total:
                line_two = format_original(_("%1!s!: %2!d! of %3!d! items completed"), progress.object_type, progress.done,
                                           progress.total)
            state = "connecting"
            self.status_panel.show_progress(progress.done / progress.total if progress and progress.total else 0)
        else:
            self.status_panel.show_progress(None)
            if unresolved:
                line_one = items_not_synchronized(unresolved)
                state = "error"
            elif last_sync:
                line_one = _("Synchronized")
                state = "connected"
            else:
                line_one = _("Connected")
                state = "connected"
            line_two = last_synchronized(last_sync) if last_sync else self.application.device_label(announcement)
        line_three = last_result if last_sync and not sync.running else ""
        self.status_panel.show(name, line_one, line_two, line_three, state, resolve_link=bool(unresolved))
        self._enable_commands(True)
        self._fill_details(progress)

    def show_sync_failure(self, error):
        self.status_panel.show_progress(None)
        self.status_panel.show(self.status_panel.name.GetLabel(), _("Error"), str(error), "", "error")
        self._enable_commands(self.application.service.state == STATE_CONNECTED)

    def _fill_details(self, progress=None):
        sync = self.application.sync
        report = sync.last_report
        self.details.DeleteAllItems()
        if not sync.partnership():
            return
        pending = sync.unresolved_items() if not sync.running else []
        for index, (object_type, enabled) in enumerate(sync.object_types()):
            if not enabled:
                status = _("Synchronization Disabled")
            elif sync.running and progress and progress.object_type == object_type.key:
                status = _("Synchronizing...")
            elif sync.running:
                status = ""
            elif report:
                failures = sum(1 for action in report.actions if action.object_type == object_type.key and action.error)
                unresolved = sum(1 for item in pending if item.object_type == object_type.key)
                if object_type.key in report.skipped_types:
                    status = format_original(_("%1!s! not available"), _(object_type.display_name))
                elif failures + unresolved:
                    status = items_not_synchronized(failures + unresolved)
                else:
                    status = _("Synchronized")
            else:
                status = ""
            self.details.InsertItem(index, _(object_type.display_name))
            self.details.SetItem(index, 1, status)

    def delete_partnership(self):
        partnership = self.shown_partnership()
        if partnership is None:
            return
        answer = wx.MessageBox(_(CONFIRM_DELETE_TEXT), _(CONFIRM_DELETE_TITLE), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self)
        if answer != wx.YES:
            return

        def deleted(result, error):
            if error:
                wx.MessageBox(str(error), _(CONFIRM_DELETE_TITLE), wx.OK | wx.ICON_ERROR, self)
            self.selected_partnership = None
            self.update_state(self.application.service.state, self.application.service.announcement, None)

        self.application.application.delete_partnership(partnership, deleted)

    def on_menu_highlight(self, event):
        item = self.GetMenuBar().FindItemById(event.GetMenuId()) if event.GetMenuId() >= 0 else None
        self.SetStatusText(item.GetHelp() if item else "")

    def on_command(self, event):
        identifier = event.GetId()
        if identifier == wx.ID_CLOSE:
            self.Close()
        elif identifier == wx.ID_ABOUT:
            self.application.show_about(self)
        elif identifier == ID_EXPLORE:
            self.application.show_explore()
        elif identifier == ID_CONNECTION_SETTINGS:
            self.application.show_connection_settings(self)
        elif identifier == ID_GET_CONNECTED:
            self.application.show_get_connected(self)
        elif identifier == ID_SYNCHRONIZE:
            self.application.sync.start()
        elif identifier == ID_RESOLVE:
            self.application.show_resolve_items(self)
        elif identifier == ID_DELETE_PARTNERSHIP:
            self.delete_partnership()
        elif ID_PARTNERSHIP_FIRST <= identifier < ID_PARTNERSHIP_FIRST + 100:
            partnerships = self.partnerships()
            index = identifier - ID_PARTNERSHIP_FIRST
            if index < len(partnerships):
                self.selected_partnership = partnerships[index]
                self.update_state(self.application.service.state, self.application.service.announcement, None)
        elif identifier == ID_STOP:
            self.application.sync.stop()
            self.status_panel.show(self.status_panel.name.GetLabel(), _("Stopping..."), "", "", "connecting")
        elif identifier == ID_OPTIONS:
            from .options import show_options
            show_options(self, self.application)
            self.update_state(self.application.service.state, self.application.service.announcement, None)
        elif identifier == ID_BACKUP_RESTORE:
            from .backup import show_backup_restore
            show_backup_restore(self, self.application)
        elif identifier == ID_ADD_REMOVE_PROGRAMS:
            from ...common.app_manager import show_app_manager
            show_app_manager(self, self.application)
        elif identifier in (ID_TOOLBAR_LARGE, ID_TOOLBAR_SMALL, ID_TOOLBAR_NONE):
            self.settings.toolbar_style = {ID_TOOLBAR_LARGE: "large", ID_TOOLBAR_SMALL: "small"}.get(identifier, "none")
            self.settings.save()
            self._build_toolbar()
        elif identifier == ID_DETAILS:
            self.settings.show_details = not self.settings.show_details
            self.settings.save()
            self.GetMenuBar().Check(ID_DETAILS, self.settings.show_details)
            if self.toolbar:
                self.toolbar.ToggleTool(ID_DETAILS, self.settings.show_details)
            self._apply_details()
        else:
            event.Skip()

    def on_close(self, event):
        rect = self.GetRect()
        self.settings.window_rect = [rect.x, rect.y, rect.width, rect.height]
        self.settings.save()
        if event.CanVeto() and self.application.tray:
            self.Hide()
            event.Veto()
            return
        self.Destroy()
        self.application.main_window = None
