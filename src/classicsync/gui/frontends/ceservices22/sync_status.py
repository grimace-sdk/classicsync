import wx

from ....i18n import N_, _, format_original, menu_label
from ...branding import rebrand
from ...common.layout import dialog_size
from ...service import STATE_CONNECTED, STATE_CONNECTING
from .activesync import (
    ProgressTracker, partnership_status, provider_display_name, service_status, service_status_text, status_window_text,
)
from .artwork import SYNC_ICON, VIEWER

ID_PROPERTIES = 200
ID_COMMUNICATIONS = 201
ID_CLOSE = 202
ID_SELECT_ALL = 203
ID_INVERT_SELECTION = 204
ID_TOOLBAR = 205
ID_STATUS_BAR = 206
ID_SORT_NAME = 211
ID_SORT_TYPE = 212
ID_SORT_SIZE = 213
ID_SORT_DATE = 214
ID_REFRESH = 215
ID_OPTIONS = 216
ID_ACTIVESYNC_OPTIONS = 217
ID_SYNCHRONIZE_NOW = 218
ID_HELP_TOPICS = 219
ID_ABOUT = 220
ID_SHOW_ERRORS = 244
ID_SHOW_PROGRESS = 255
ID_SYNCHRONIZE_SELECTED = 232

WEB_ITEMS = [
    (221, N_("&Free Stuff")), (222, N_("&Product News")), (223, N_("&Developer Forum")), (224, N_("Frequently Asked &Questions")),
    (225, N_("Online &Support")), None, (226, N_("Microsoft Windows &CE Home Page")), (227, N_("Send Feedbac&k...")),
    (228, N_("&Best of the Web")), (229, N_("Search the &Web...")), (230, N_("Web &Tutorial")), None,
    (231, N_("Microsoft &Home Page")),
]

AVAILABLE = {ID_COMMUNICATIONS, ID_CLOSE, ID_TOOLBAR, ID_STATUS_BAR, ID_REFRESH, ID_ABOUT, ID_SELECT_ALL, ID_INVERT_SELECTION,
             ID_SORT_NAME, ID_SORT_TYPE, ID_SYNCHRONIZE_NOW, ID_ACTIVESYNC_OPTIONS, ID_SHOW_ERRORS, ID_SHOW_PROGRESS}

HELP_TEXT = {
    ID_PROPERTIES: N_("Displays properties of the selected items."), ID_COMMUNICATIONS: N_("Opens communications properties."),
    ID_CLOSE: N_("Closes the window."), ID_SELECT_ALL: N_("Selects all items in the window."),
    ID_INVERT_SELECTION: N_("Reverses which items are selected and which are not."), ID_TOOLBAR: N_("Shows or hides the toolbar."),
    ID_STATUS_BAR: N_("Shows or hides the status bar."), ID_SORT_NAME: N_("Sorts items alphabetically by name."),
    ID_SORT_TYPE: N_("Sorts items by type."), ID_SORT_SIZE: N_("Sorts items by size, from smallest to largest."),
    ID_SORT_DATE: N_("Sorts items by date, from oldest to most recent."), ID_REFRESH: N_("Refreshes item information."),
    ID_OPTIONS: N_("Changes the display options for the window."), ID_ACTIVESYNC_OPTIONS: N_("Opens ActiveSync Options."),
    ID_SYNCHRONIZE_NOW: N_("Synchronizes all the registered databases."), ID_HELP_TOPICS: N_("Opens Help for Windows CE Services."),
    ID_ABOUT: N_("Displays program information, version number, and copyright."),
    ID_SHOW_ERRORS: N_("Shows/hides the ActiveSync error messages."),
    ID_SHOW_PROGRESS: N_("Shows/hides the ActiveSync progress messages."),
    ID_SYNCHRONIZE_SELECTED: N_("Synchronizes the selected items."),
}

STATUS_TEXT = {STATE_CONNECTING: N_("Establishing connection to a mobile device...")}
WAITING_TEXT = N_("Waiting for a mobile device to connect...")
FRONTEND_KEY = "ceservices22"


def help_text(identifier):
    return rebrand(_(HELP_TEXT[identifier]), FRONTEND_KEY) if identifier in HELP_TEXT else ""


def translated_items(items):
    return [None if item is None else (item[0], _(item[1])) for item in items]


def append_items(menu, items):
    for item in items:
        if item is None:
            menu.AppendSeparator()
        else:
            identifier, label = item
            menu.Append(identifier, label, help_text(identifier))


class SyncStatusWindow(wx.Frame):
    def __init__(self, frontend):
        super().__init__(None, size=wx.Size(520, 300))
        self.frontend = frontend
        self.SetIcons(frontend.artwork.application_icons())
        menu_bar = wx.MenuBar()
        file_menu = wx.Menu()
        append_items(file_menu, [(ID_PROPERTIES, menu_label(N_("P&roperties\tAlt+Enter"))), None,
                                 (ID_COMMUNICATIONS, _("Comm&unications...")), None, (ID_CLOSE, _("&Close"))])
        menu_bar.Append(file_menu, _("&File"))
        edit_menu = wx.Menu()
        append_items(edit_menu, [(ID_SELECT_ALL, menu_label(N_("Select &All\tCtrl+A"))),
                                 (ID_INVERT_SELECTION, _("&Invert Selection"))])
        menu_bar.Append(edit_menu, _("&Edit"))
        view_menu = wx.Menu()
        view_menu.AppendCheckItem(ID_TOOLBAR, _("&Toolbar"))
        view_menu.AppendCheckItem(ID_STATUS_BAR, _("Status &Bar"))
        view_menu.AppendSeparator()
        arrange_menu = wx.Menu()
        append_items(arrange_menu, [(ID_SORT_NAME, _("by &Name")), (ID_SORT_TYPE, _("by &Type")), (ID_SORT_SIZE, _("by Si&ze")),
                                    (ID_SORT_DATE, _("by &Date"))])
        view_menu.AppendSubMenu(arrange_menu, _("Arrange &Icons"))
        append_items(view_menu, [None, (ID_REFRESH, _("&Refresh") + "\tF5"), (ID_OPTIONS, _("&Options..."))])
        menu_bar.Append(view_menu, _("&View"))
        tools_menu = wx.Menu()
        append_items(tools_menu, [(ID_SYNCHRONIZE_NOW, _("Synchronize &Now") + "\tF9"),
                                  (ID_ACTIVESYNC_OPTIONS, _("ActiveSync &Options..."))])
        tools_menu.AppendCheckItem(ID_SHOW_ERRORS, _("Show ActiveSync &Errors"), help_text(ID_SHOW_ERRORS))
        tools_menu.AppendCheckItem(ID_SHOW_PROGRESS, _("Show ActiveSync &Progress"), help_text(ID_SHOW_PROGRESS))
        menu_bar.Append(tools_menu, _("&Tools"))
        help_menu = wx.Menu()
        append_items(help_menu, [(ID_HELP_TOPICS, _("ActiveSync Help &Topics") + "\tF1"), None])
        web_menu = wx.Menu()
        append_items(web_menu, translated_items(WEB_ITEMS))
        help_menu.AppendSubMenu(web_menu, _("Microsoft on the &Web"))
        append_items(help_menu, [None, (ID_ABOUT, rebrand(_("&About Windows CE Services"), FRONTEND_KEY))])
        menu_bar.Append(help_menu, _("&Help"))
        self.SetMenuBar(menu_bar)
        for index in range(menu_bar.GetMenuCount()):
            for item in menu_bar.GetMenu(index).GetMenuItems():
                if not item.IsSeparator() and not item.GetSubMenu() and item.GetId() not in AVAILABLE:
                    item.Enable(False)
        for item in web_menu.GetMenuItems():
            if not item.IsSeparator():
                item.Enable(False)
        arrange_menu.Enable(ID_SORT_SIZE, False)
        arrange_menu.Enable(ID_SORT_DATE, False)

        self.toolbar = self.CreateToolBar(wx.TB_HORIZONTAL | wx.TB_FLAT)
        size = wx.Size(16, 16)
        self.toolbar.AddTool(ID_SYNCHRONIZE_NOW, _("Synchronize Now"), wx.ArtProvider.GetBitmap(wx.ART_REDO, wx.ART_TOOLBAR, size),
                             _("Synchronize Now"))
        self.toolbar.AddTool(ID_PROPERTIES, _("Properties"), wx.ArtProvider.GetBitmap(wx.ART_INFORMATION, wx.ART_TOOLBAR, size),
                             _("Properties"))
        self.toolbar.Realize()
        self.toolbar.EnableTool(ID_PROPERTIES, False)
        menu_bar.Check(ID_TOOLBAR, True)
        menu_bar.Check(ID_STATUS_BAR, True)

        panel = wx.Panel(self)
        header = wx.BoxSizer(wx.HORIZONTAL)
        icon = frontend.artwork.icon_as_bitmap(VIEWER, SYNC_ICON, 32,
                                               lambda: wx.ArtProvider.GetBitmap(wx.ART_REDO, wx.ART_OTHER, wx.Size(32, 32)))
        header.Add(wx.StaticBitmap(panel, bitmap=icon), 0, wx.ALL, 6)
        text = wx.BoxSizer(wx.VERTICAL)
        self.status = wx.StaticText(panel, label="")
        text.Add(self.status, 0, wx.EXPAND)
        self.progress_text = wx.StaticText(panel, label="", style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
        text.Add(self.progress_text, 0, wx.EXPAND | wx.TOP, 2)
        self.gauge = wx.Gauge(panel, range=1000, size=dialog_size(panel, 150, 8), style=wx.GA_SMOOTH)
        text.Add(self.gauge, 0, wx.TOP, 3)
        header.Add(text, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.list = wx.ListCtrl(panel, style=wx.LC_REPORT)
        for index, (label, width) in enumerate([(_("Name"), 180), (_("Sync Copy In"), 140), (_("Status"), 160)]):
            self.list.InsertColumn(index, label, width=width)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(header, 0, wx.EXPAND)
        sizer.Add(self.list, 1, wx.EXPAND)
        panel.SetSizer(sizer)
        self.panel = panel
        self.CreateStatusBar()
        self.sort_column = 0
        self.rows = []
        self.tracker = None
        self.Bind(wx.EVT_MENU, self.on_command)
        self.Bind(wx.EVT_MENU_OPEN, lambda event: self.update_commands())
        self.Bind(wx.EVT_MENU_HIGHLIGHT_ALL, self.on_menu_highlight)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda event: self.update_item_count())
        self.list.Bind(wx.EVT_LIST_ITEM_DESELECTED, lambda event: self.update_item_count())
        self.list.Bind(wx.EVT_LIST_COL_CLICK, lambda event: self.sort_by(event.GetColumn()))
        self.list.Bind(wx.EVT_CONTEXT_MENU, self.on_context_menu)
        self.SetAcceleratorTable(wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord("A"), ID_SELECT_ALL),
            (wx.ACCEL_NORMAL, wx.WXK_F5, ID_REFRESH),
            (wx.ACCEL_NORMAL, wx.WXK_F9, ID_SYNCHRONIZE_NOW),
        ]))
        self.update_state(frontend.service.state)
        self.Centre()

    def update_state(self, state):
        self.refresh()

    def refresh(self, progress=None):
        frontend = self.frontend
        sync = frontend.sync
        state = frontend.service.state
        connected = frontend.connected()
        name = frontend.connected_name() if state == STATE_CONNECTED else ""
        self.SetTitle(format_original(_("%s ActiveSync Status"), name) if name else _("ActiveSync Status"))
        if connected:
            self.status.SetLabel(status_window_text(partnership_status(sync, frontend.sync_failed)))
        else:
            self.status.SetLabel(_(STATUS_TEXT.get(state, WAITING_TEXT)))
        if sync.running:
            if not self.tracker:
                self.tracker = ProgressTracker(sync)
            if progress:
                text = self.tracker.text(progress)
                if text:
                    self.progress_text.SetLabel(text)
                fraction = self.tracker.fraction(progress)
                if fraction is not None:
                    self.gauge.SetValue(int(1000 * fraction))
        else:
            self.tracker = None
            self.progress_text.SetLabel("")
            self.gauge.SetValue(0)
        self.progress_text.Show(sync.running)
        self.gauge.Show(sync.running)
        self.panel.Layout()
        self._fill(progress if sync.running else None)
        self.update_commands()

    def _fill(self, progress):
        frontend = self.frontend
        sync = frontend.sync
        selected = {self.rows[index]["name"] for index in self._selected_indexes()}
        self.rows = []
        if frontend.connected() and sync.partnership():
            copy_in = provider_display_name(sync)
            current = progress or sync.last_progress
            for object_type, enabled in sync.object_types():
                status = service_status(sync, object_type, enabled, frontend.sync_failed, current)
                self.rows.append({"name": _(object_type.display_name), "copy_in": copy_in, "status": service_status_text(status)})
        key = ["name", "copy_in", "status"][self.sort_column]
        self.rows.sort(key=lambda row: row[key].lower())
        if self.list.GetItemCount() != len(self.rows):
            self.list.DeleteAllItems()
            for index in range(len(self.rows)):
                self.list.InsertItem(index, "")
        for index, row in enumerate(self.rows):
            self.list.SetItem(index, 0, row["name"])
            self.list.SetItem(index, 1, row["copy_in"])
            self.list.SetItem(index, 2, row["status"])
            self.list.Select(index, row["name"] in selected)
        self.update_item_count()

    def _selected_indexes(self):
        return [index for index in range(self.list.GetItemCount()) if self.list.IsSelected(index)]

    def update_item_count(self):
        selected = len(self._selected_indexes())
        self.SetStatusText(format_original(_("%d database(s) selected"), selected) if selected
                           else format_original(_("%d database(s)"), len(self.rows)))

    def update_commands(self):
        frontend = self.frontend
        menu_bar = self.GetMenuBar()
        menu_bar.Enable(ID_SYNCHRONIZE_NOW, frontend.can_synchronize())
        menu_bar.Enable(ID_ACTIVESYNC_OPTIONS, frontend.connected())
        menu_bar.Check(ID_SHOW_ERRORS, frontend.sync_display.show_errors)
        menu_bar.Check(ID_SHOW_PROGRESS, frontend.sync_display.show_progress)
        self.toolbar.EnableTool(ID_SYNCHRONIZE_NOW, frontend.can_synchronize())

    def sort_by(self, column):
        self.sort_column = column
        self._fill(None)

    def on_menu_highlight(self, event):
        self.SetStatusText(help_text(event.GetMenuId()) if event.GetMenuId() >= 0 else "")

    def on_context_menu(self, event):
        menu = wx.Menu()
        if self._selected_indexes():
            append_items(menu, [(ID_SYNCHRONIZE_SELECTED, _("&Synchronize")), (ID_ACTIVESYNC_OPTIONS, _("ActiveSync &Options..."))])
            menu.Enable(ID_SYNCHRONIZE_SELECTED, False)
        else:
            append_items(menu, [(ID_SYNCHRONIZE_NOW, _("&Synchronize Now")), (ID_ACTIVESYNC_OPTIONS, _("ActiveSync &Options..."))])
            menu.Enable(ID_SYNCHRONIZE_NOW, self.frontend.can_synchronize())
        menu.AppendCheckItem(ID_SHOW_ERRORS, _("Show ActiveSync &Errors")).Check(self.frontend.sync_display.show_errors)
        menu.AppendCheckItem(ID_SHOW_PROGRESS, _("Show ActiveSync &Progress")).Check(self.frontend.sync_display.show_progress)
        menu.AppendSeparator()
        if not self._selected_indexes():
            append_items(menu, [(ID_SORT_NAME, _("Arrange by &Name")), (ID_SORT_TYPE, _("Arrange by &Type")), None])
        append_items(menu, [(ID_PROPERTIES, _("P&roperties"))])
        menu.Enable(ID_ACTIVESYNC_OPTIONS, self.frontend.connected())
        menu.Enable(ID_PROPERTIES, False)
        self.PopupMenu(menu)
        menu.Destroy()

    def on_command(self, event):
        identifier = event.GetId()
        if identifier == ID_CLOSE:
            self.Close()
        elif identifier == ID_COMMUNICATIONS:
            self.frontend.show_connection_settings(self)
        elif identifier == ID_ABOUT:
            self.frontend.show_about(self)
        elif identifier == ID_REFRESH:
            self.refresh()
        elif identifier == ID_SYNCHRONIZE_NOW:
            self.frontend.synchronize_now()
        elif identifier == ID_ACTIVESYNC_OPTIONS:
            self.frontend.show_activesync_options(self)
        elif identifier == ID_SHOW_ERRORS:
            self.frontend.toggle_show_errors()
            self.update_commands()
        elif identifier == ID_SHOW_PROGRESS:
            self.frontend.toggle_show_progress()
            self.update_commands()
        elif identifier == ID_SELECT_ALL:
            for index in range(self.list.GetItemCount()):
                self.list.Select(index)
        elif identifier == ID_INVERT_SELECTION:
            for index in range(self.list.GetItemCount()):
                self.list.Select(index, not self.list.IsSelected(index))
        elif identifier in (ID_SORT_NAME, ID_SORT_TYPE):
            self.sort_by(0 if identifier == ID_SORT_NAME else 1)
        elif identifier == ID_TOOLBAR:
            self.toolbar.Show(not self.toolbar.IsShown())
            self.SendSizeEvent()
        elif identifier == ID_STATUS_BAR:
            self.GetStatusBar().Show(not self.GetStatusBar().IsShown())
            self.SendSizeEvent()
        else:
            event.Skip()

    def on_close(self, event):
        self.frontend.sync_status_window = None
        self.Destroy()
