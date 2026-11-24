import wx

from ....i18n import N_, _, format_original, menu_label, plain_newlines
from ...branding import rebrand, title
from ...common.device_browser import (
    COMMAND_COPY_FROM_COMPUTER, COMMAND_COPY_TO_COMPUTER, COMMAND_DELETE, COMMAND_INVERT_SELECTION, COMMAND_NEW_FOLDER, COMMAND_OPEN, COPY, CUT,
    COMMAND_PROPERTIES, COMMAND_REFRESH, COMMAND_RENAME, COMMAND_SELECT_ALL, COMMAND_UP, SORT_DATE, SORT_NAME, SORT_SIZE, SORT_TYPE,
    VIEW_DETAILS, VIEW_LARGE, VIEW_LIST, VIEW_SMALL, VIEW_STYLES, DeviceBrowser, root_name,
)
from ...common.file_icons import KIND_FOLDER, FileIcons
from ...common.icon_grid import ItemListView
from ...service import STATE_CONNECTED, STATE_CONNECTING, STATE_DISABLED
from .device_properties import is_palm_size, memory_text

TITLE = title("ceservices22")
FOLDER_NAME = N_("Mobile Devices")
PALM_SIZE_ROOT = N_("My Palm-size PC")
FRONTEND_KEY = "ceservices22"

ID_COMMUNICATIONS = 2
ID_CREATE_SHORTCUT = 4
ID_EXPLORE = 10
ID_SORT_FILES_NAME = 20
ID_SORT_FILES_SIZE = 21
ID_SORT_FILES_TYPE = 22
ID_SORT_FILES_DATE = 23
ID_UNDO = 26
ID_SORT_DEVICES_NAME = 28
ID_SORT_DEVICES_DESCRIPTION = 29
ID_SORT_DEVICES_SYNCHRONIZATION = 30
ID_SORT_DEVICES_CONNECTION = 31
ID_SORT_DEVICES_MEMORY = 32
ID_ACTIVESYNC_STATUS = 35
ID_APPLICATION_MANAGER = 36
ID_HELP_TOPICS = 48
ID_ABOUT = 49
ID_BACKUP_RESTORE = 52
ID_BACK_UP_NOW = 53
ID_ACTIVESYNC_OPTIONS = 54
ID_SYNCHRONIZE_NOW = 55
ID_FILE_CONVERSION = 56
ID_GUIDED_TOUR = 57
ID_TROUBLESHOOTER = 58
ID_ENABLE_SERIAL = 59
ID_ENABLE_NETWORK = 60
ID_SHOW_ERRORS = 61
ID_SHOW_PROGRESS = 62
ID_CUT = 1001
ID_COPY = 1002
ID_PASTE = 1003
ID_PASTE_SHORTCUT = 1008
ID_BACK = 1101
ID_FORWARD = 1102
ID_TOOLBAR = 1103
ID_STATUS_BAR = 1104
ID_VIEWS = 1105
ID_LINE_UP_ICONS = 1106
ID_FOLDER_OPTIONS = 1107
ID_VIEW_LARGE = 1111
ID_VIEW_SMALL = 1112
ID_VIEW_LIST = 1113
ID_VIEW_DETAILS = 1114

WEB_ITEMS = [
    (37, N_("&Free Stuff")), (38, N_("&Product News")), (ID_GUIDED_TOUR, N_("Guided Tou&r")), (39, N_("&Developer Forum")),
    (40, N_("Frequently Asked &Questions")), (41, N_("Online &Support")), None, (42, N_("Microsoft Windows &CE Home Page")),
    (43, N_("Send Feedbac&k...")), (44, N_("&Best of the Web")), (45, N_("Search the &Web...")), (46, N_("Web &Tutorial")), None,
    (47, N_("Microsoft &Home Page")),
]

FILE_SORT_ITEMS = [(ID_SORT_FILES_NAME, N_("by &Name")), (ID_SORT_FILES_TYPE, N_("by &Type")),
                   (ID_SORT_FILES_SIZE, N_("by Si&ze")), (ID_SORT_FILES_DATE, N_("by &Date"))]
DEVICE_SORT_ITEMS = [(ID_SORT_DEVICES_NAME, N_("by &Name")), (ID_SORT_DEVICES_DESCRIPTION, N_("by &Description")),
                     (ID_SORT_DEVICES_SYNCHRONIZATION, N_("by &Synchronization")),
                     (ID_SORT_DEVICES_CONNECTION, N_("by &Connection")), (ID_SORT_DEVICES_MEMORY, N_("by &Total Memory"))]

VIEW_IDS = {VIEW_LARGE: ID_VIEW_LARGE, VIEW_SMALL: ID_VIEW_SMALL, VIEW_LIST: ID_VIEW_LIST, VIEW_DETAILS: ID_VIEW_DETAILS}
VIEW_CYCLE = [VIEW_LARGE, VIEW_SMALL, VIEW_LIST, VIEW_DETAILS]
FILE_SORTS = {ID_SORT_FILES_NAME: SORT_NAME, ID_SORT_FILES_SIZE: SORT_SIZE, ID_SORT_FILES_TYPE: SORT_TYPE, ID_SORT_FILES_DATE: SORT_DATE}
DEVICE_SORTS = [ID_SORT_DEVICES_NAME, ID_SORT_DEVICES_DESCRIPTION, ID_SORT_DEVICES_SYNCHRONIZATION, ID_SORT_DEVICES_CONNECTION,
                ID_SORT_DEVICES_MEMORY]
DEVICE_COLUMNS = [(N_("Name"), 130), (N_("Description"), 150), (N_("Synchronization"), 110), (N_("Connection"), 100), (N_("Total Memory"), 100)]

HELP_TEXT = {
    COMMAND_NEW_FOLDER: N_("Create a new folder"), ID_COMMUNICATIONS: N_("Show communications dialog"),
    ID_ENABLE_SERIAL: N_("Enables/disables Serial Port connection."), ID_ENABLE_NETWORK: N_("Enables/disables Networking connection."),
    ID_SYNCHRONIZE_NOW: N_("Synchronizes all the registered databases."), ID_ACTIVESYNC_STATUS: N_("Opens ActiveSync Status."),
    ID_ACTIVESYNC_OPTIONS: N_("Opens ActiveSync Options."), ID_BACK_UP_NOW: N_("Backs up all mobile device files, data, and settings."),
    ID_BACKUP_RESTORE: N_("Opens backup and restore properties."), ID_FILE_CONVERSION: N_("Show File Conversions dialog"),
    ID_APPLICATION_MANAGER: N_("Opens Application Manager."), ID_HELP_TOPICS: N_("Opens Help for Microsoft Windows CE Services."),
    ID_TROUBLESHOOTER: N_("Opens Help on Communications Troubleshooter."),
    ID_ABOUT: N_("Displays program information, version information and copyright for Windows CE Services."),
    COMMAND_OPEN: N_("Open selected folder"), ID_CREATE_SHORTCUT: N_("Create a shortcut to selected item(s)"),
    COMMAND_DELETE: N_("Delete selected item(s)"), COMMAND_RENAME: N_("Rename selected item"),
    COMMAND_PROPERTIES: N_("Display Properties for selected item(s)"), ID_CUT: N_("Cut selected item(s)"), ID_COPY: N_("Copy selected item(s)"),
    ID_PASTE: N_("Paste the Clipboard contents here"), ID_PASTE_SHORTCUT: N_("Create a shortcut to the copied item(s)"),
    ID_SORT_FILES_NAME: N_("Sort items by Name"), ID_SORT_FILES_SIZE: N_("Sort items by Size"), ID_SORT_FILES_TYPE: N_("Sort items by Type"),
    ID_SORT_FILES_DATE: N_("Sort items by Modified Time"), ID_SORT_DEVICES_NAME: N_("Sort items by Device name."),
    ID_SORT_DEVICES_DESCRIPTION: N_("Sort items by Device description."),
    ID_SORT_DEVICES_SYNCHRONIZATION: N_("Sort items by Synchronization status."),
    ID_SORT_DEVICES_CONNECTION: N_("Sort items by Connection status."), ID_SORT_DEVICES_MEMORY: N_("Sort items by total memory on the device."),
    ID_SHOW_ERRORS: N_("Shows/hides the ActiveSync error messages."), ID_SHOW_PROGRESS: N_("Shows/hides the ActiveSync progress messages."),
}

UNAVAILABLE = {
    ID_FILE_CONVERSION, ID_HELP_TOPICS, ID_TROUBLESHOOTER, ID_ENABLE_NETWORK, ID_UNDO, ID_LINE_UP_ICONS, ID_FOLDER_OPTIONS,
    ID_EXPLORE,
} | {identifier for identifier, label in filter(None, WEB_ITEMS)}

CONNECTION_STATUS = {
    STATE_DISABLED: N_("Connection disabled"),
    STATE_CONNECTING: N_("Initializing..."),
    STATE_CONNECTED: N_("Connected"),
}
WAITING_STATUS = N_("Waiting for a mobile device to connect...")


def device_root_name(announcement):
    return _(PALM_SIZE_ROOT) if is_palm_size(announcement) else root_name(announcement)


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


def disable_unavailable(menu):
    for item in menu.GetMenuItems():
        if item.GetSubMenu():
            disable_unavailable(item.GetSubMenu())
        elif item.GetId() in UNAVAILABLE:
            item.Enable(False)


class MobileDevicesWindow(wx.Frame):
    def __init__(self, frontend):
        super().__init__(None, title=_(FOLDER_NAME), size=wx.Size(640, 420))
        self.frontend = frontend
        self.application = frontend.application
        self.settings = frontend.settings
        self.artwork = frontend.artwork
        self.location = None
        self.history = [None]
        self.history_index = 0
        self.device_view = VIEW_LARGE
        self.file_view = VIEW_DETAILS
        self.device_sort = 0
        self.rows = []
        self.browser = None
        self.SetIcons(self.artwork.application_icons())

        self.toolbar = self._build_toolbar()
        self.CreateStatusBar(2)
        self.SetStatusWidths([-1, 220])
        self.body = wx.Panel(self)
        self.address = self._build_address_bar(self.body)
        self.device_list = ItemListView(self.body, style=VIEW_STYLES[self.device_view] | wx.LC_SINGLE_SEL | wx.LC_AUTOARRANGE)
        self.large_images = wx.ImageList(32, 32)
        self.small_images = wx.ImageList(16, 16)
        for palm_size, connected in ((False, True), (False, False), (True, True), (True, False)):
            self.large_images.Add(self.artwork.device_bitmap(palm_size, connected, 32))
            self.small_images.Add(self.artwork.device_bitmap(palm_size, connected, 16))
        self.device_list.SetImageList(self.large_images, wx.IMAGE_LIST_NORMAL)
        self.device_list.SetImageList(self.small_images, wx.IMAGE_LIST_SMALL)
        if self.device_view == VIEW_DETAILS:
            self._add_device_columns()
        self.content = wx.BoxSizer(wx.VERTICAL)
        self.content.Add(self.address, 0, wx.EXPAND | wx.BOTTOM, 2)
        self.content.Add(self.device_list, 1, wx.EXPAND)
        self.body.SetSizer(self.content)

        self.device_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda event: self.open_device())
        self.device_list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda event: self._update_device_status())
        self.device_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, lambda event: self._update_device_status())
        self.device_list.Bind(wx.EVT_CONTEXT_MENU, self._on_device_context_menu)
        self.device_list.Bind(wx.EVT_LIST_COL_CLICK, lambda event: self.sort_devices(event.GetColumn()))
        self.Bind(wx.EVT_MENU, self.on_command)
        self.Bind(wx.EVT_TOOL, self.on_command)
        self.Bind(wx.EVT_MENU_OPEN, lambda event: self._update_commands())
        self.Bind(wx.EVT_MENU_HIGHLIGHT_ALL, self._on_menu_highlight)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.SetAcceleratorTable(wx.AcceleratorTable([
            (wx.ACCEL_NORMAL, wx.WXK_F9, ID_SYNCHRONIZE_NOW),
            (wx.ACCEL_CTRL, ord("Z"), ID_UNDO),
            (wx.ACCEL_CTRL, ord("A"), COMMAND_SELECT_ALL),
            (wx.ACCEL_NORMAL, wx.WXK_F5, COMMAND_REFRESH),
            (wx.ACCEL_NORMAL, wx.WXK_DELETE, COMMAND_DELETE),
            (wx.ACCEL_NORMAL, wx.WXK_F2, COMMAND_RENAME),
            (wx.ACCEL_NORMAL, wx.WXK_BACK, COMMAND_UP),
            (wx.ACCEL_ALT, wx.WXK_RETURN, COMMAND_PROPERTIES),
            (wx.ACCEL_ALT, wx.WXK_LEFT, ID_BACK),
            (wx.ACCEL_ALT, wx.WXK_RIGHT, ID_FORWARD),
        ]))
        self._build_menu_bar()
        self.update_state(frontend.service.state, frontend.service.announcement)
        self.Centre()

    def _build_toolbar(self):
        toolbar = self.CreateToolBar(wx.TB_HORIZONTAL | wx.TB_FLAT | wx.TB_TEXT)
        size = wx.Size(24, 24)

        def art(name):
            return wx.ArtProvider.GetBitmap(name, wx.ART_TOOLBAR, size)
        toolbar.AddTool(ID_BACK, _("Back"), art(wx.ART_GO_BACK), _("Back"))
        toolbar.AddTool(ID_FORWARD, _("Forward"), art(wx.ART_GO_FORWARD), _("Forward"))
        toolbar.AddTool(COMMAND_UP, _("Up"), art(wx.ART_GO_DIR_UP), _("Up One Level"))
        toolbar.AddSeparator()
        toolbar.AddTool(ID_CUT, _("Cut"), art(wx.ART_CUT), _("Cut"))
        toolbar.AddTool(ID_COPY, _("Copy"), art(wx.ART_COPY), _("Copy"))
        toolbar.AddTool(ID_PASTE, _("Paste"), art(wx.ART_PASTE), _("Paste"))
        toolbar.AddSeparator()
        toolbar.AddTool(ID_UNDO, _("Undo"), art(wx.ART_UNDO), _("Undo"))
        toolbar.AddSeparator()
        toolbar.AddTool(COMMAND_DELETE, _("Delete"), art(wx.ART_DELETE), _("Delete"))
        toolbar.AddTool(COMMAND_PROPERTIES, _("Properties"), art(wx.ART_INFORMATION), _("Properties"))
        toolbar.AddSeparator()
        toolbar.AddTool(ID_VIEWS, _("Views"), art(wx.ART_LIST_VIEW), _("Views"))
        toolbar.Realize()
        return toolbar

    def _build_address_bar(self, parent):
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(wx.StaticText(panel, label=_("Address")), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 6)
        self.address_icon = wx.StaticBitmap(panel, bitmap=self.artwork.mobile_devices_bitmap(16))
        sizer.Add(self.address_icon, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.address_box = wx.ComboBox(panel, style=wx.CB_READONLY)
        sizer.Add(self.address_box, 1, wx.ALIGN_CENTER_VERTICAL | wx.TOP | wx.BOTTOM | wx.RIGHT, 2)
        panel.SetSizer(sizer)
        self.address_box.Bind(wx.EVT_COMBOBOX, self._on_address_selected)
        self.address_locations = []
        return panel

    def _build_menu_bar(self):
        in_device = self.location is not None
        menu_bar = wx.MenuBar()

        file_menu = wx.Menu()
        append_items(file_menu, [(COMMAND_OPEN, _("&Open")), (ID_EXPLORE, _("&Explore")), None,
                                 (ID_COMMUNICATIONS, _("Comm&unications..."))])
        file_menu.AppendCheckItem(ID_ENABLE_SERIAL, _("En&able Serial Connection"), help_text(ID_ENABLE_SERIAL))
        file_menu.AppendCheckItem(ID_ENABLE_NETWORK, _("Ena&ble Network Connection"), help_text(ID_ENABLE_NETWORK))
        file_menu.AppendSeparator()
        if in_device:
            append_items(file_menu, [(COMMAND_NEW_FOLDER, _("&New Folder")), None])
        append_items(file_menu, [(ID_CREATE_SHORTCUT, _("Create &Shortcut")), (COMMAND_DELETE, _("&Delete"))])
        if in_device:
            append_items(file_menu, [(COMMAND_RENAME, _("Rena&me"))])
        append_items(file_menu, [(COMMAND_PROPERTIES, _("P&roperties")), None])
        if in_device:
            file_menu.Append(COMMAND_COPY_TO_COMPUTER, _("Copy &to This Computer..."), _("Copy selected item(s) to this computer"))
            file_menu.Append(COMMAND_COPY_FROM_COMPUTER, _("Copy &Files Here..."), _("Copy files from this computer"))
            file_menu.AppendSeparator()
        file_menu.Append(wx.ID_CLOSE, _("&Close"), _("Closes the window."))
        menu_bar.Append(file_menu, _("&File"))

        edit_menu = wx.Menu()
        append_items(edit_menu, [(ID_UNDO, _("&Undo") + "\tCtrl+Z"), None, (ID_CUT, _("Cu&t") + "\tCtrl+X"),
                                 (ID_COPY, _("&Copy") + "\tCtrl+C"), (ID_PASTE, _("&Paste") + "\tCtrl+V"),
                                 (ID_PASTE_SHORTCUT, _("Paste &Shortcut")), None,
                                 (COMMAND_SELECT_ALL, menu_label(N_("Select &All\tCtrl+A"))),
                                 (COMMAND_INVERT_SELECTION, _("&Invert Selection"))])
        menu_bar.Append(edit_menu, _("&Edit"))

        view_menu = wx.Menu()
        view_menu.AppendCheckItem(ID_TOOLBAR, _("&Toolbar"), _("Shows or hides the toolbar."))
        view_menu.AppendCheckItem(ID_STATUS_BAR, _("Status &Bar"), _("Shows or hides the status bar."))
        view_menu.AppendSeparator()
        view_menu.AppendRadioItem(ID_VIEW_LARGE, _("Lar&ge Icons"), _("Displays items by using large icons."))
        view_menu.AppendRadioItem(ID_VIEW_SMALL, _("S&mall Icons"), _("Displays items by using small icons."))
        view_menu.AppendRadioItem(ID_VIEW_LIST, _("&List"), _("Displays items in a list."))
        view_menu.AppendRadioItem(ID_VIEW_DETAILS, _("&Details"), _("Displays information about each item in the window."))
        view_menu.AppendSeparator()
        arrange_menu = wx.Menu()
        if in_device:
            append_items(arrange_menu, translated_items(FILE_SORT_ITEMS))
        else:
            append_items(arrange_menu, translated_items(DEVICE_SORT_ITEMS))
        view_menu.AppendSubMenu(arrange_menu, _("Arrange &Icons"))
        append_items(view_menu, [(ID_LINE_UP_ICONS, _("Line &Up Icons")), None, (COMMAND_REFRESH, _("&Refresh") + "\tF5"),
                                 (ID_FOLDER_OPTIONS, _("&Options..."))])
        menu_bar.Append(view_menu, _("&View"))

        go_menu = wx.Menu()
        go_menu.Append(ID_BACK, _("&Back") + "\tAlt+Left")
        go_menu.Append(ID_FORWARD, _("&Forward") + "\tAlt+Right")
        go_menu.Append(COMMAND_UP, _("&Up One Level"))
        menu_bar.Append(go_menu, _("&Go"))

        tools_menu = wx.Menu()
        append_items(tools_menu, [(ID_SYNCHRONIZE_NOW, _("Synchronize &Now") + "\tF9"),
                                  (ID_ACTIVESYNC_STATUS, _("ActiveSync &Status...")),
                                  (ID_ACTIVESYNC_OPTIONS, _("ActiveSync &Options...")), None,
                                  (ID_BACK_UP_NOW, _("&Back Up Now...")), (ID_BACKUP_RESTORE, _("Backup/&Restore...")), None,
                                  (ID_FILE_CONVERSION, _("File &Conversion...")), None,
                                  (ID_APPLICATION_MANAGER, _("&Application Manager..."))])
        menu_bar.Append(tools_menu, _("&Tools"))

        help_menu = wx.Menu()
        append_items(help_menu, [(ID_HELP_TOPICS, rebrand(_("Windows CE Services Help &Topics"), FRONTEND_KEY)),
                                 (ID_TROUBLESHOOTER, _("&Communications Troubleshooter"))])
        web_menu = wx.Menu()
        append_items(web_menu, translated_items(WEB_ITEMS))
        help_menu.AppendSubMenu(web_menu, _("Microsoft on the &Web"), _("Opens links to related sites on the Internet."))
        help_menu.AppendSeparator()
        help_menu.Append(wx.ID_ABOUT, rebrand(_("About Windows CE &Services"), FRONTEND_KEY), help_text(ID_ABOUT))
        menu_bar.Append(help_menu, _("&Help"))

        for index in range(menu_bar.GetMenuCount()):
            disable_unavailable(menu_bar.GetMenu(index))
        old_menu_bar = self.GetMenuBar()
        self.SetMenuBar(menu_bar)
        if old_menu_bar:
            old_menu_bar.Destroy()
        self._update_commands()

    def _add_device_columns(self):
        for index, (label, width) in enumerate(DEVICE_COLUMNS):
            self.device_list.InsertColumn(index, _(label), width=width)

    def _on_menu_highlight(self, event):
        menu_bar = self.GetMenuBar()
        item = menu_bar.FindItemById(event.GetMenuId()) if menu_bar and event.GetMenuId() >= 0 else None
        self.SetStatusText(item.GetHelp() if item else "", 0)

    @property
    def current_view(self):
        return self.file_view if self.location is not None else self.device_view

    def _selected_rows(self):
        index = self.device_list.GetFirstSelected()
        return [self.rows[index]] if 0 <= index < len(self.rows) else []

    def _update_commands(self):
        menu_bar = self.GetMenuBar()
        if not menu_bar:
            return
        in_device = self.location is not None
        connected = self.frontend.service.state == STATE_CONNECTED
        can_cut = can_paste = can_paste_shortcut = False
        if in_device and self.browser:
            entries = self.browser.selected_entries()
            can_delete = bool(entries)
            can_properties = len(entries) == 1
            can_open = len(entries) == 1 and entries[0].is_directory
            can_cut = bool(entries) and not self.browser.in_rom(entries) and connected
            can_paste = connected and self.browser.can_paste()
            can_paste_shortcut = connected and self.browser.clipboard is not None
        else:
            rows = self._selected_rows()
            can_delete = bool(rows) and not rows[0]["connected"]
            can_properties = bool(rows) and rows[0]["connected"]
            can_open = can_properties
        states = {
            COMMAND_OPEN: can_open, COMMAND_DELETE: can_delete, COMMAND_PROPERTIES: can_properties,
            COMMAND_RENAME: in_device and can_properties, COMMAND_UP: in_device, ID_BACK: self.history_index > 0,
            ID_FORWARD: self.history_index < len(self.history) - 1, ID_ACTIVESYNC_STATUS: True,
            COMMAND_COPY_TO_COMPUTER: in_device and can_delete, COMMAND_NEW_FOLDER: in_device and connected,
            COMMAND_COPY_FROM_COMPUTER: in_device and connected, ID_SYNCHRONIZE_NOW: self.frontend.can_synchronize(),
            ID_ACTIVESYNC_OPTIONS: self.frontend.connected() and self.application.partnership is not None,
            ID_BACK_UP_NOW: self.frontend.can_back_up(), ID_BACKUP_RESTORE: self.frontend.can_back_up(),
            ID_CUT: can_cut, ID_COPY: can_cut, ID_CREATE_SHORTCUT: can_cut, ID_PASTE: can_paste, ID_PASTE_SHORTCUT: can_paste_shortcut,
        }
        for identifier, enabled in states.items():
            if menu_bar.FindItemById(identifier):
                menu_bar.Enable(identifier, enabled)
            if self.toolbar.FindById(identifier):
                self.toolbar.EnableTool(identifier, enabled)
        self.toolbar.EnableTool(ID_UNDO, False)
        menu_bar.Check(ID_ENABLE_SERIAL, self.settings.serial_enabled)
        menu_bar.Check(ID_ENABLE_NETWORK, self.settings.network_enabled)
        menu_bar.Check(ID_TOOLBAR, self.toolbar.IsShown())
        menu_bar.Check(ID_STATUS_BAR, self.GetStatusBar().IsShown())
        menu_bar.Check(VIEW_IDS[self.current_view], True)

    def update_state(self, state, announcement):
        self.state = state
        self.announcement = announcement
        if state != STATE_CONNECTED and self.location is not None:
            self.show_location(None)
            self.history = [None]
            self.history_index = 0
        self._fill_devices()
        self._update_commands()

    def details_changed(self):
        self._fill_devices()

    def _device_row(self):
        announcement = self.announcement
        details = self.application.device_details
        partnership = self.application.partnership
        return {
            "name": partnership.name if partnership else _("Guest"),
            "connected": True,
            "partnership": partnership,
            "description": details.get("description", ""),
            "synchronization": self.frontend.device_sync_status(),
            "connection": _("Connected"),
            "memory": memory_text(details) if details.get("memory") or details.get("store") else "",
            "image": 2 if is_palm_size(announcement) else 0,
        }

    def _profile_rows(self):
        connected = self.application.partnership if self.state == STATE_CONNECTED else None
        rows = []
        for partnership in self.application.partnerships():
            if connected is not None and partnership.directory == connected.directory:
                continue
            rows.append({"name": partnership.name, "connected": False, "partnership": partnership, "description": "",
                         "synchronization": "", "connection": _("Disconnected"), "memory": "", "image": 0})
        return rows

    def connected_row(self):
        return next((row for row in self.rows if row["connected"]), None)

    def delete_profiles(self):
        rows = self._selected_rows()
        if not rows:
            return
        if any(row["connected"] for row in rows):
            message = _("Cannot delete the partnership profile of a connected device.\r\nPlease disconnect the device and try again.")
            wx.MessageBox(plain_newlines(message), _("Error Deleting Partnership Profile"), wx.OK | wx.ICON_ERROR, self)
            return
        question = _("Your partnership profile(s) may contain settings, backup, and other device-specific "
                     "information.\r\n\r\nAre you sure you want to delete these profile(s)?")
        answer = wx.MessageBox(plain_newlines(question), _("Confirm Partnership Profile(s) Delete"),
                               wx.YES_NO | wx.ICON_QUESTION, self)
        if answer != wx.YES:
            return
        for row in rows:
            self.application.delete_partnership(row["partnership"], lambda result, error: self._fill_devices())

    def _fill_devices(self):
        selected = {row["name"] for row in self._selected_rows()}
        self.rows = ([self._device_row()] if self.state == STATE_CONNECTED else []) + self._profile_rows()
        keys = ["name", "description", "synchronization", "connection", "memory"]
        self.rows.sort(key=lambda row: row[keys[self.device_sort]].lower())
        self.device_list.DeleteAllItems()
        for index, row in enumerate(self.rows):
            self.device_list.InsertItem(index, row["name"], row["image"])
            if self.device_view == VIEW_DETAILS:
                for column, key in enumerate(keys[1:], start=1):
                    self.device_list.SetItem(index, column, row[key])
            if row["name"] in selected:
                self.device_list.Select(index)
        if self.location is None:
            self._update_device_status()
            self._update_address()

    def _update_device_status(self):
        if self.location is not None:
            return
        selected = len(self._selected_rows())
        self.SetStatusText(format_original(_("%1!d! object(s) selected"), selected) if selected
                           else format_original(_("%1!d! object(s)"), len(self.rows)), 0)
        if self.state == STATE_CONNECTED:
            row = self.connected_row()
            text = format_original(_("%s Connected"), row["name"]) if row else _(CONNECTION_STATUS[STATE_CONNECTED])
        else:
            text = _(CONNECTION_STATUS.get(self.state, WAITING_STATUS))
        self.SetStatusText(text, 1)
        self._update_commands()

    def sort_devices(self, column):
        self.device_sort = column
        self._fill_devices()

    def set_view(self, view):
        if self.location is not None and self.browser:
            self.file_view = view
            self.browser.set_view(view)
        else:
            self.device_view = view
            style = self.device_list.GetWindowStyleFlag() & ~(wx.LC_ICON | wx.LC_SMALL_ICON | wx.LC_LIST | wx.LC_REPORT)
            self.device_list.SetWindowStyleFlag(style | VIEW_STYLES[view])
            if view == VIEW_DETAILS and self.device_list.GetColumnCount() == 0:
                self._add_device_columns()
            self._fill_devices()
        self._update_commands()

    def open_device(self):
        rows = self._selected_rows() or self.rows[:1]
        if not rows or self.state != STATE_CONNECTED or not rows[0]["connected"]:
            wx.MessageBox(_("Cannot explore or open an unconnected device."), _("Explore/Open Error:"), wx.OK | wx.ICON_ERROR, self)
            return
        if self.frontend.version_one_connected():
            message = _("This version of Windows CE Services is not compatible with the connected mobile device. Please close all "
                        "Windows CE Service windows and open the Explorer window that corresponds to the version of the mobile "
                        "device.")
            wx.MessageBox(rebrand(message, FRONTEND_KEY), _("Version Conflict Detected"), wx.OK | wx.ICON_WARNING, self)
            return
        self.navigate("\\")

    def navigate(self, location):
        self.history = self.history[:self.history_index + 1] + [location]
        self.history_index = len(self.history) - 1
        self.show_location(location)

    def _record_folder(self, folder):
        if self.history[self.history_index] != folder:
            self.history = self.history[:self.history_index + 1] + [folder]
            self.history_index = len(self.history) - 1
        self.location = folder
        self._update_address()
        self._update_commands()

    def show_location(self, location):
        if location is None:
            self.location = None
            if self.browser:
                self.content.Detach(self.browser)
                self.browser.Destroy()
                self.browser = None
            self.device_list.Show()
            self.SetTitle(_(FOLDER_NAME))
            self.SetStatusText("", 1)
            self._build_menu_bar()
            self._fill_devices()
            self.body.Layout()
            return
        if not self.browser:
            self.location = location
            self.browser = DeviceBrowser(self.body, self.application, device_root_name(self.announcement),
                                         on_status=self.SetStatusText, on_title=self.SetTitle, on_folder=self._record_folder,
                                         file_icons=FileIcons(self.artwork))
            self.browser.set_tree_visible(False)
            self.browser.set_view(self.file_view)
            self.browser.context_menu_factory = self._file_context_menu
            self.browser.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_file_selection)
            self.browser.list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self._on_file_selection)
            self.device_list.Hide()
            self.content.Add(self.browser, 1, wx.EXPAND)
            self.body.Layout()
            self._build_menu_bar()
        self.browser.navigate(location)

    def _on_file_selection(self, event):
        self._update_commands()
        event.Skip()

    def go_back(self):
        if self.history_index > 0:
            self.history_index -= 1
            self.show_location(self.history[self.history_index])
            self._update_commands()

    def go_forward(self):
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.show_location(self.history[self.history_index])
            self._update_commands()

    def go_up(self):
        if self.location is None:
            return
        if self.location in ("", "\\"):
            self.navigate(None)
        else:
            parent = self.location.rstrip("\\").rsplit("\\", 1)[0] or "\\"
            self.navigate(parent)

    def _update_address(self):
        self.address_box.Clear()
        self.address_locations = [None]
        self.address_box.Append(_(FOLDER_NAME))
        bitmap = self.artwork.mobile_devices_bitmap(16)
        if self.location is not None:
            root = device_root_name(self.announcement)
            self.address_locations.append("\\")
            self.address_box.Append(root)
            bitmap = self.artwork.device_bitmap(is_palm_size(self.announcement), True, 16)
            path = ""
            for part in [part for part in self.location.split("\\") if part]:
                path += "\\" + part
                self.address_locations.append(path)
                self.address_box.Append(root + path)
                bitmap = FileIcons(self.artwork).base_bitmap(KIND_FOLDER, 16)
        self.address_box.SetSelection(len(self.address_locations) - 1)
        self.address_icon.SetBitmap(bitmap)

    def _on_address_selected(self, event):
        location = self.address_locations[event.GetSelection()]
        if location != self.location:
            self.navigate(location)

    def _device_context_menu(self):
        menu = wx.Menu()
        append_items(menu, [(COMMAND_OPEN, _("&Open")), (ID_EXPLORE, _("&Explore")), None,
                            (ID_SYNCHRONIZE_NOW, _("Synchronize &Now")), (ID_ACTIVESYNC_STATUS, _("ActiveSync &Status...")),
                            (ID_ACTIVESYNC_OPTIONS, _("ActiveSync &Options..."))])
        menu.AppendCheckItem(ID_SHOW_ERRORS, _("S&how ActiveSync Errors"), help_text(ID_SHOW_ERRORS))
        menu.AppendCheckItem(ID_SHOW_PROGRESS, _("Sho&w ActiveSync Progress"), help_text(ID_SHOW_PROGRESS))
        append_items(menu, [None, (ID_CREATE_SHORTCUT, _("Create &Shortcut")), (COMMAND_DELETE, _("&Delete")), None,
                            (COMMAND_PROPERTIES, _("P&roperties"))])
        disable_unavailable(menu)
        rows = self._selected_rows()
        menu.Enable(COMMAND_DELETE, bool(rows) and not rows[0]["connected"])
        menu.Enable(ID_CREATE_SHORTCUT, False)
        menu.Enable(ID_SYNCHRONIZE_NOW, self.frontend.can_synchronize())
        menu.Enable(ID_ACTIVESYNC_OPTIONS, self.frontend.connected())
        menu.Check(ID_SHOW_ERRORS, self.frontend.sync_display.show_errors)
        menu.Check(ID_SHOW_PROGRESS, self.frontend.sync_display.show_progress)
        return menu

    def _background_context_menu(self, sorts):
        menu = wx.Menu()
        view_menu = wx.Menu()
        view_menu.AppendRadioItem(ID_VIEW_LARGE, _("Lar&ge Icons"))
        view_menu.AppendRadioItem(ID_VIEW_SMALL, _("S&mall Icons"))
        view_menu.AppendRadioItem(ID_VIEW_LIST, _("&List"))
        view_menu.AppendRadioItem(ID_VIEW_DETAILS, _("&Details"))
        view_menu.Check(VIEW_IDS[self.current_view], True)
        menu.AppendSubMenu(view_menu, _("&View"))
        menu.AppendSeparator()
        arrange_menu = wx.Menu()
        append_items(arrange_menu, translated_items(sorts))
        menu.AppendSubMenu(arrange_menu, _("Arrange &Icons"))
        append_items(menu, [(ID_LINE_UP_ICONS, _("Line &Up Icons")), None, (COMMAND_REFRESH, _("R&efresh"))])
        return menu

    def _file_context_menu(self, entries):
        if not entries:
            menu = self._background_context_menu(FILE_SORT_ITEMS)
            append_items(menu, [None, (ID_PASTE, _("&Paste")), (ID_PASTE_SHORTCUT, _("Paste &Shortcut")), None])
            menu.Append(COMMAND_COPY_FROM_COMPUTER, _("Copy &Files Here..."))
            new_menu = wx.Menu()
            append_items(new_menu, [(COMMAND_NEW_FOLDER, _("Ne&w Folder"))])
            menu.AppendSubMenu(new_menu, _("Ne&w"))
            disable_unavailable(menu)
            menu.Enable(ID_PASTE, self.browser.can_paste())
            menu.Enable(ID_PASTE_SHORTCUT, self.browser.clipboard is not None)
            return menu
        menu = wx.Menu()
        if len(entries) == 1 and entries[0].is_directory:
            append_items(menu, [(COMMAND_OPEN, _("&Open")), (ID_EXPLORE, _("&Explore")), None])
        append_items(menu, [(ID_CUT, _("Cu&t")), (ID_COPY, _("&Copy"))])
        menu.Append(COMMAND_COPY_TO_COMPUTER, _("Copy &to This Computer..."))
        append_items(menu, [None, (ID_CREATE_SHORTCUT, _("Create &Shortcut")), (COMMAND_DELETE, _("&Delete")),
                            (COMMAND_RENAME, _("Rena&me")), None, (COMMAND_PROPERTIES, _("P&roperties"))])
        disable_unavailable(menu)
        in_rom = self.browser.in_rom(entries)
        for identifier in (ID_CUT, ID_COPY, ID_CREATE_SHORTCUT, COMMAND_DELETE):
            menu.Enable(identifier, not in_rom)
        menu.Enable(COMMAND_RENAME, len(entries) == 1 and not in_rom)
        menu.Enable(COMMAND_PROPERTIES, len(entries) == 1)
        return menu

    def _on_device_context_menu(self, event):
        if self._selected_rows():
            menu = self._device_context_menu()
        else:
            menu = self._background_context_menu(DEVICE_SORT_ITEMS)
            disable_unavailable(menu)
        self.PopupMenu(menu)
        menu.Destroy()

    def show_device_properties(self):
        rows = self._selected_rows()
        if rows and self.state == STATE_CONNECTED and rows[0]["connected"]:
            self.frontend.show_device_properties(self, rows[0]["name"])

    def on_command(self, event):
        identifier = event.GetId()
        in_device = self.location is not None and self.browser is not None
        if identifier == wx.ID_CLOSE:
            self.Close()
        elif identifier == wx.ID_ABOUT:
            self.frontend.show_about(self)
        elif identifier == ID_COMMUNICATIONS:
            self.frontend.show_connection_settings(self)
        elif identifier == ID_ENABLE_SERIAL:
            self.frontend.toggle_serial_connection()
        elif identifier == ID_ACTIVESYNC_STATUS:
            self.frontend.show_sync_status()
        elif identifier == ID_SYNCHRONIZE_NOW:
            self.frontend.synchronize_now()
        elif identifier == ID_ACTIVESYNC_OPTIONS:
            self.frontend.show_activesync_options(self)
        elif identifier == ID_BACKUP_RESTORE:
            self.frontend.show_backup_restore(self)
        elif identifier == ID_BACK_UP_NOW:
            self.frontend.back_up_now(self)
        elif identifier == ID_SHOW_ERRORS:
            self.frontend.toggle_show_errors()
        elif identifier == ID_SHOW_PROGRESS:
            self.frontend.toggle_show_progress()
        elif identifier == ID_APPLICATION_MANAGER:
            from ...common.app_manager import show_app_manager
            show_app_manager(self, self.frontend, title=_("Application Manager"))
        elif identifier == ID_BACK:
            self.go_back()
        elif identifier == ID_FORWARD:
            self.go_forward()
        elif identifier == COMMAND_UP:
            self.go_up()
        elif identifier == ID_TOOLBAR:
            self.toolbar.Show(not self.toolbar.IsShown())
            self.SendSizeEvent()
        elif identifier == ID_STATUS_BAR:
            self.GetStatusBar().Show(not self.GetStatusBar().IsShown())
            self.SendSizeEvent()
        elif identifier in (ID_VIEW_LARGE, ID_VIEW_SMALL, ID_VIEW_LIST, ID_VIEW_DETAILS):
            self.set_view({value: key for key, value in VIEW_IDS.items()}[identifier])
        elif identifier == ID_VIEWS:
            self.set_view(VIEW_CYCLE[(VIEW_CYCLE.index(self.current_view) + 1) % len(VIEW_CYCLE)])
        elif identifier in DEVICE_SORTS:
            self.sort_devices(DEVICE_SORTS.index(identifier))
        elif identifier in FILE_SORTS and in_device:
            self.browser.sort_by(FILE_SORTS[identifier])
        elif identifier in (ID_CUT, ID_COPY) and in_device:
            self.browser.set_clipboard(CUT if identifier == ID_CUT else COPY)
        elif identifier == ID_PASTE and in_device:
            self.browser.paste()
        elif identifier == ID_PASTE_SHORTCUT and in_device:
            self.browser.paste_shortcut()
        elif identifier == ID_CREATE_SHORTCUT and in_device:
            self.browser.create_shortcut_selected()
        elif in_device:
            self.browser.on_command(event)
        elif identifier == COMMAND_OPEN:
            self.open_device()
        elif identifier == COMMAND_PROPERTIES:
            self.show_device_properties()
        elif identifier == COMMAND_DELETE:
            self.delete_profiles()
        elif identifier == COMMAND_REFRESH:
            self._fill_devices()
        elif identifier == COMMAND_SELECT_ALL:
            for index in range(self.device_list.GetItemCount()):
                self.device_list.Select(index)
        elif identifier == COMMAND_INVERT_SELECTION:
            for index in range(self.device_list.GetItemCount()):
                self.device_list.Select(index, not self.device_list.IsSelected(index))
        else:
            event.Skip()

    def on_close(self, event):
        self.frontend.main_window = None
        self.Destroy()
