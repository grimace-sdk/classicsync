import wx

from ....i18n import N_, _, format_original, menu_label
from ...branding import rebrand, title
from ...common.device_browser import parent_folder, root_name
from ...common.layout import dialog_size
from ...service import STATE_CONNECTED, STATE_CONNECTING, STATE_WAITING
from ...common.device_browser import COPY, CUT
from .browser import HpcDeviceBrowser, display_name
from .commands import (
    ARRANGE_COMMANDS, ID_ABOUT, ID_ADDRESS, ID_ARRANGE_BY_DATE, ID_ARRANGE_BY_NAME, ID_ARRANGE_BY_SIZE,
    ID_ARRANGE_BY_TYPE, ID_BACK_UP_NOW, ID_BACKUP_RESTORE, ID_BEST_OF_THE_WEB, ID_CANCEL_MODE, ID_CLOSE, ID_COMMUNICATIONS,
    ID_CONTEXT_MENU, ID_COPY, ID_CREATE_SHORTCUT, ID_CUT, ID_DELETE, ID_DETAILS, ID_DEVELOPER_FORUM, ID_FAQ,
    ID_FILE_CONVERSION, ID_FOLDERS, ID_FREE_STUFF, ID_HELP_TOPICS, ID_INVERT_SELECTION, ID_LARGE_ICONS, ID_LIST,
    ID_MICROSOFT_HOME, ID_NEW_FOLDER, ID_NEXT_PANE, ID_ONLINE_SUPPORT, ID_OPEN, ID_OPTIONS, ID_PASTE, ID_PASTE_SHORTCUT,
    ID_PREVIOUS_PANE, ID_PRINT, ID_PRODUCT_NEWS, ID_PROPERTIES, ID_REFRESH, ID_RENAME, ID_SEARCH_THE_WEB, ID_SELECT_ALL,
    ID_SEND_FEEDBACK, ID_SMALL_ICONS, ID_STATUS_BAR, ID_SYNCHRONIZATION_MANAGER, ID_SYNCHRONIZE_NOW, ID_TOOLBAR, ID_UNDO,
    ID_UP, ID_WEB_TUTORIAL, ID_WINDOWS_CE_HOME, UNAVAILABLE, VIEW_COMMANDS, help_text, tooltip,
)
from .options import OptionsSheet

FRONTEND_KEY = "hpcexplorer11"
TITLE = title(FRONTEND_KEY)

ALL_FOLDERS = N_(" All Folders")
CONTENTS_OF = N_(" Contents of '%s'")

CONNECTION_STATUS = {
    STATE_WAITING: N_("Waiting to connect to H/PC..."),
    STATE_CONNECTING: N_("Establishing connection to H/PC..."),
}

IMAGE_DEVICE = 3


def menu(items):
    built = wx.Menu()
    for item in items:
        if item is None:
            built.AppendSeparator()
        elif isinstance(item[1], wx.Menu):
            built.AppendSubMenu(item[1], item[0])
        else:
            identifier, label, kind = item if len(item) == 3 else (item[0], item[1], wx.ITEM_NORMAL)
            built.Append(identifier, label, help_text(identifier), kind)
    return built


class DescriptionBars(wx.Panel):
    def __init__(self, parent, window):
        super().__init__(parent)
        self.window = window
        self.contents = ""
        self.SetMinSize(wx.Size(-1, self.GetCharHeight() + 6))
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_SIZE, self.on_size)

    def set_contents(self, folder_name):
        self.contents = format_original(_(CONTENTS_OF), folder_name)
        self.Refresh()

    def on_size(self, event):
        self.Refresh()
        event.Skip()

    def on_paint(self, event):
        dc = wx.PaintDC(self)
        dc.SetFont(self.GetFont())
        dc.SetTextForeground(wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNTEXT))
        width, height = self.GetClientSize()
        view = self.window.view
        boxes = []
        if view and view.IsSplit():
            sash = view.GetSashPosition()
            right = sash + view.GetSashSize()
            boxes.append((0, sash, _(ALL_FOLDERS)))
            boxes.append((right, width - right, self.contents))
        else:
            boxes.append((0, width, self.contents))
        renderer = wx.RendererNative.Get()
        text_top = (height - dc.GetCharHeight()) // 2
        for left, box_width, text in boxes:
            rectangle = wx.Rect(left, 0, box_width, height)
            renderer.DrawHeaderButton(self, dc, rectangle)
            dc.SetClippingRegion(wx.Rect(left + 2, 0, max(0, box_width - 4), height))
            dc.DrawText(text, left + 2, text_top)
            dc.DestroyClippingRegion()


class WaitingView(wx.SplitterWindow):
    def __init__(self, parent, window, root_label):
        super().__init__(parent, style=wx.SP_LIVE_UPDATE)
        settings = window.view_settings
        self.small_images = window.artwork.image_list(16)
        self.tree = wx.TreeCtrl(self, style=wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT | wx.TR_SINGLE)
        self.tree.SetImageList(self.small_images)
        self.tree.AddRoot(root_label, IMAGE_DEVICE)
        self.list = wx.ListCtrl(self, style=wx.LC_REPORT if settings.view == "details" else wx.LC_ICON)
        if settings.view == "details":
            for index, (label, width, align) in enumerate([(_("Name"), 220, wx.LIST_FORMAT_LEFT), (_("Size"), 80, wx.LIST_FORMAT_RIGHT),
                                                           (_("Type"), 160, wx.LIST_FORMAT_LEFT), (_("Modified"), 130, wx.LIST_FORMAT_LEFT)]):
                self.list.InsertColumn(index, label, align, width)
        self.tree_width = settings.sash_position
        self.SplitVertically(self.tree, self.list, self.tree_width)
        self.SetMinimumPaneSize(80)
        self.set_tree_visible(settings.show_folders)

    def set_tree_visible(self, visible):
        if visible and not self.IsSplit():
            self.tree.Show()
            self.SplitVertically(self.tree, self.list, self.tree_width)
        elif not visible and self.IsSplit():
            self.tree_width = self.GetSashPosition()
            self.Unsplit(self.tree)

    def set_view(self, view):
        style = self.list.GetWindowStyleFlag() & ~(wx.LC_ICON | wx.LC_REPORT)
        self.list.SetWindowStyleFlag(style | (wx.LC_REPORT if view == "details" else wx.LC_ICON))


class ExplorerWindow(wx.Frame):
    def __init__(self, frontend):
        super().__init__(None, title=TITLE, size=wx.Size(640, 460))
        self.frontend = frontend
        self.application = frontend.application
        self.artwork = frontend.artwork
        self.view_settings = frontend.view_settings
        self.root_label = root_name(None)
        self.folder = "\\"
        self.clipboard = None
        self.system_clipboard_has_files = False
        self.status_text = ""
        self.view = None
        self.browser = None
        self.toolbar = None
        self.address = None
        self.SetIcons(self.artwork.application_icons())
        self._build_menu()
        self.status_bar = self.CreateStatusBar(2)
        self.status_bar.SetStatusWidths([-1, dialog_size(self, 120, 0).width])
        self.status_bar.Show(self.view_settings.show_status_bar)
        self.body = wx.Panel(self)
        self.body_sizer = wx.BoxSizer(wx.VERTICAL)
        self._build_toolbar()
        self.description = DescriptionBars(self.body, self)
        self.description.Show(self.view_settings.description_bars)
        self.body_sizer.Add(self.description, 0, wx.EXPAND)
        self.body.SetSizer(self.body_sizer)
        self.SetAcceleratorTable(wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord("A"), ID_SELECT_ALL),
            (wx.ACCEL_CTRL, ord("C"), ID_COPY),
            (wx.ACCEL_CTRL, ord("V"), ID_PASTE),
            (wx.ACCEL_CTRL, ord("X"), ID_CUT),
            (wx.ACCEL_CTRL, ord("Z"), ID_UNDO),
            (wx.ACCEL_NORMAL, wx.WXK_F1, ID_HELP_TOPICS),
            (wx.ACCEL_SHIFT, wx.WXK_F10, ID_CONTEXT_MENU),
            (wx.ACCEL_NORMAL, wx.WXK_F2, ID_RENAME),
            (wx.ACCEL_NORMAL, wx.WXK_F4, ID_ADDRESS),
            (wx.ACCEL_NORMAL, wx.WXK_F5, ID_REFRESH),
            (wx.ACCEL_NORMAL, wx.WXK_F6, ID_NEXT_PANE),
            (wx.ACCEL_NORMAL, wx.WXK_F9, ID_SYNCHRONIZE_NOW),
            (wx.ACCEL_ALT, wx.WXK_RETURN, ID_PROPERTIES),
            (wx.ACCEL_CTRL | wx.ACCEL_ALT, wx.WXK_RETURN, ID_PROPERTIES),
        ]))
        self.Bind(wx.EVT_MENU, self.on_command)
        self.Bind(wx.EVT_UPDATE_UI, self.on_update_ui)
        self.Bind(wx.EVT_MENU_HIGHLIGHT_ALL, self.on_menu_highlight)
        self.Bind(wx.EVT_MENU_CLOSE, lambda event: self.status_bar.SetStatusText(self.status_text, 0))
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        self.Bind(wx.EVT_ACTIVATE, self.on_activate)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self._replace_view(WaitingView(self.body, self, self.root_label))
        self._restore_placement()
        service = self.application.service
        self.update_state(service.state, service.announcement, service.error)

    def _build_menu(self):
        file_menu = menu([(ID_OPEN, _("&Open")), (ID_PRINT, _("&Print")), (ID_NEW_FOLDER, _("&New Folder")), None,
                          (ID_CREATE_SHORTCUT, _("Create &Shortcut")), (ID_DELETE, _("&Delete")), (ID_RENAME, _("Rena&me")),
                          (ID_PROPERTIES, _("P&roperties") + "\tAlt+Enter"), None, (ID_COMMUNICATIONS, _("Comm&unications...")), None,
                          (ID_CLOSE, _("&Close"))])
        edit_menu = menu([(ID_UNDO, menu_label(N_("&Undo\tCtrl+Z"))), None, (ID_CUT, menu_label(N_("Cu&t\tCtrl+X"))),
                          (ID_COPY, menu_label(N_("&Copy\tCtrl+C"))), (ID_PASTE, menu_label(N_("&Paste\tCtrl+V"))),
                          (ID_PASTE_SHORTCUT, _("Paste &Shortcut")), None, (ID_SELECT_ALL, _("Select &All") + "\tCtrl+A"),
                          (ID_INVERT_SELECTION, _("&Invert Selection"))])
        arrange_menu = menu([(ID_ARRANGE_BY_NAME, _("by &Name")), (ID_ARRANGE_BY_TYPE, _("by &Type")),
                             (ID_ARRANGE_BY_SIZE, _("by Si&ze")), (ID_ARRANGE_BY_DATE, _("by &Date"))])
        view_menu = menu([(ID_FOLDERS, _("&Folders"), wx.ITEM_CHECK), (ID_TOOLBAR, _("&Toolbar"), wx.ITEM_CHECK),
                          (ID_STATUS_BAR, _("Status &Bar"), wx.ITEM_CHECK), None,
                          (ID_LARGE_ICONS, _("Lar&ge Icons"), wx.ITEM_RADIO), (ID_SMALL_ICONS, _("S&mall Icons"), wx.ITEM_RADIO),
                          (ID_LIST, _("&List"), wx.ITEM_RADIO), (ID_DETAILS, _("&Details"), wx.ITEM_RADIO), None,
                          (_("Arrange &Icons"), arrange_menu), None, (ID_REFRESH, _("&Refresh")), (ID_OPTIONS, _("&Options..."))])
        tools_menu = menu([(ID_SYNCHRONIZATION_MANAGER, _("&Synchronization Manager...")), (ID_SYNCHRONIZE_NOW, menu_label(N_("Synchronize &Now\tF9"))),
                           None, (ID_BACKUP_RESTORE, _("Backup/&Restore...")), (ID_BACK_UP_NOW, _("&Back Up Now")), None,
                           (ID_FILE_CONVERSION, _("File &Conversion..."))])
        web_menu = menu([(ID_FREE_STUFF, _("&Free Stuff")), (ID_PRODUCT_NEWS, _("&Product News")),
                         (ID_DEVELOPER_FORUM, _("&Developer Forum")), (ID_FAQ, _("Frequently Asked &Questions")),
                         (ID_ONLINE_SUPPORT, _("Online &Support")), None, (ID_WINDOWS_CE_HOME, _("Microsoft Windows &CE Home Page")),
                         (ID_SEND_FEEDBACK, _("Send Feedbac&k...")), (ID_BEST_OF_THE_WEB, _("&Best of the Web")),
                         (ID_SEARCH_THE_WEB, _("Search the &Web...")), (ID_WEB_TUTORIAL, _("Web &Tutorial")), None,
                         (ID_MICROSOFT_HOME, _("Microsoft &Home Page"))])
        help_menu = menu([(ID_HELP_TOPICS, rebrand(_("H/PC Explorer Help &Topics"), FRONTEND_KEY)), None,
                          (_("Microsoft on the &Web"), web_menu), None,
                          (ID_ABOUT, rebrand(_("&About H/PC Explorer..."), FRONTEND_KEY))])
        menu_bar = wx.MenuBar()
        for built, label in ((file_menu, _("&File")), (edit_menu, _("&Edit")), (view_menu, _("&View")), (tools_menu, _("&Tools")),
                             (help_menu, _("&Help"))):
            menu_bar.Append(built, label)
        self.SetMenuBar(menu_bar)
        for identifier in UNAVAILABLE:
            if menu_bar.FindItemById(identifier):
                menu_bar.Enable(identifier, False)

    def _build_toolbar(self):
        toolbar = wx.ToolBar(self.body, style=wx.TB_HORIZONTAL | wx.TB_FLAT | wx.TB_NODIVIDER)
        toolbar.SetToolBitmapSize(wx.Size(16, 16))
        self.address = wx.ComboBox(toolbar, ID_ADDRESS, size=wx.Size(dialog_size(self, 110, 0).width, -1), style=wx.CB_READONLY)
        self.address.SetToolTip(tooltip(ID_ADDRESS))
        self.address.Bind(wx.EVT_COMBOBOX, self.on_address)
        toolbar.AddControl(self.address)
        toolbar.AddSeparator()
        synchronize, back_up, folders = self.artwork.custom_toolbar_bitmaps()
        art = self.artwork.art
        buttons = [
            (ID_UP, art(wx.ART_GO_DIR_UP, 16), wx.ITEM_NORMAL),
            (ID_NEW_FOLDER, art(wx.ART_NEW_DIR, 16), wx.ITEM_NORMAL),
            None,
            (ID_CUT, art(wx.ART_CUT, 16), wx.ITEM_NORMAL),
            (ID_COPY, art(wx.ART_COPY, 16), wx.ITEM_NORMAL),
            (ID_PASTE, art(wx.ART_PASTE, 16), wx.ITEM_NORMAL),
            None,
            (ID_UNDO, art(wx.ART_UNDO, 16), wx.ITEM_NORMAL),
            None,
            (ID_DELETE, art(wx.ART_DELETE, 16), wx.ITEM_NORMAL),
            (ID_PROPERTIES, art(wx.ART_INFORMATION, 16), wx.ITEM_NORMAL),
            None,
            (ID_FOLDERS, folders, wx.ITEM_CHECK),
            (ID_LARGE_ICONS, self.artwork.view_bitmap("large"), wx.ITEM_RADIO),
            (ID_SMALL_ICONS, self.artwork.view_bitmap("small"), wx.ITEM_RADIO),
            (ID_LIST, self.artwork.view_bitmap("list"), wx.ITEM_RADIO),
            (ID_DETAILS, self.artwork.view_bitmap("details"), wx.ITEM_RADIO),
            None,
            (ID_SYNCHRONIZE_NOW, synchronize, wx.ITEM_NORMAL),
            (ID_BACK_UP_NOW, back_up, wx.ITEM_NORMAL),
        ]
        for button in buttons:
            if button is None:
                toolbar.AddSeparator()
                continue
            identifier, bitmap, kind = button
            toolbar.AddTool(identifier, "", bitmap, tooltip(identifier), kind)
            toolbar.SetToolLongHelp(identifier, help_text(identifier))
        toolbar.Realize()
        self.toolbar = toolbar
        self.body_sizer.Add(toolbar, 0, wx.EXPAND)
        self.body_sizer.Add(wx.StaticLine(self.body), 0, wx.EXPAND)
        toolbar.Show(self.view_settings.show_toolbar)

    def _replace_view(self, view):
        if self.view:
            self.body_sizer.Detach(self.view)
            self.view.Destroy()
        self.view = view
        self.browser = view if isinstance(view, HpcDeviceBrowser) else None
        self.body_sizer.Add(view, 1, wx.EXPAND)
        view.Bind(wx.EVT_SPLITTER_SASH_POS_CHANGING, self.on_sash_moved)
        view.Bind(wx.EVT_SPLITTER_SASH_POS_CHANGED, self.on_sash_moved)
        self.body.Layout()
        self.description.Refresh()

    def _restore_placement(self):
        rect = self.view_settings.window_rect
        if len(rect) == 4:
            self.SetRect(wx.Rect(*rect))
        else:
            self.Centre()

    def update_state(self, state, announcement, error):
        connected = state == STATE_CONNECTED
        if connected and not self.browser:
            self.root_label = root_name(announcement)
            browser = HpcDeviceBrowser(self.body, self, self.root_label)
            self._replace_view(browser)
            browser.navigate("\\")
        elif not connected and self.browser:
            self.clipboard = None
            self._replace_view(WaitingView(self.body, self, self.root_label))
        if not connected:
            self.folder = "\\"
            self.set_status(_(CONNECTION_STATUS[state]) if state in CONNECTION_STATUS else error or _("Communications disabled"), 0)
            self.folder_changed("\\")
        self.update_sync_status()
        self.update_title()

    def update_sync_status(self):
        self.status_bar.SetStatusText(self.frontend.sync_status_bar_text(), 1)

    def set_status(self, text, field=0):
        if field == 0:
            self.status_text = text
        self.status_bar.SetStatusText(text, field)

    def folder_changed(self, folder):
        self.folder = folder
        self.description.set_contents(display_name(self.root_label, folder))
        self._fill_address()
        self.update_title()

    def _fill_address(self):
        parts = [part for part in self.folder.split("\\") if part]
        labels = [self.root_label] + ["    " * (depth + 1) + part for depth, part in enumerate(parts)]
        self.address.Set(labels)
        self.address.SetSelection(len(labels) - 1)

    def update_title(self):
        if not self.browser:
            self.SetTitle(TITLE)
            return
        if self.view_settings.full_path_in_title and self.folder != "\\":
            path = self.root_label + self.folder.rstrip("\\")
        else:
            path = display_name(self.root_label, self.folder)
        self.SetTitle(_("Exploring - ") + path if self.view_settings.show_folders else path)

    @property
    def clipboard(self):
        return getattr(self.application, "device_clipboard", None)

    @clipboard.setter
    def clipboard(self, value):
        self.application.device_clipboard = value

    def can_paste(self):
        return self.browser is not None and (self.clipboard is not None or self.system_clipboard_has_files)

    def on_address(self, event):
        if not self.browser:
            return
        parts = [part for part in self.folder.split("\\") if part]
        depth = self.address.GetSelection()
        target = "\\" + "\\".join(parts[:depth]) if depth else "\\"
        if target != self.folder:
            self.browser.navigate(target)

    def on_sash_moved(self, event):
        self.description.Refresh()
        event.Skip()

    def on_activate(self, event):
        if event.GetActive():
            self.system_clipboard_has_files = self._system_clipboard_files() is not None
        event.Skip()

    def _system_clipboard_files(self):
        if not wx.TheClipboard.Open():
            return None
        try:
            if not wx.TheClipboard.IsSupported(wx.DataFormat(wx.DF_FILENAME)):
                return None
            data = wx.FileDataObject()
            if not wx.TheClipboard.GetData(data):
                return None
            return data.GetFilenames() or None
        finally:
            wx.TheClipboard.Close()

    def on_menu_highlight(self, event):
        identifier = event.GetMenuId()
        if identifier >= 0:
            self.status_bar.SetStatusText(help_text(identifier), 0)

    def on_char_hook(self, event):
        focus = wx.Window.FindFocus()
        other_modifiers = event.GetModifiers() & ~wx.MOD_SHIFT
        if isinstance(focus, (wx.TextCtrl, wx.ComboBox)) or other_modifiers:
            event.Skip()
            return
        key = event.GetKeyCode()
        commands = {
            (wx.WXK_BACK, False): ID_UP,
            (wx.WXK_BACK, True): ID_DELETE,
            (wx.WXK_DELETE, False): ID_DELETE,
            (wx.WXK_TAB, False): ID_NEXT_PANE,
            (wx.WXK_TAB, True): ID_PREVIOUS_PANE,
            (wx.WXK_ESCAPE, False): ID_CANCEL_MODE,
        }
        identifier = commands.get((key, event.ShiftDown()))
        if identifier is None:
            event.Skip()
            return
        self.ProcessEvent(wx.CommandEvent(wx.wxEVT_MENU, identifier))

    def switch_pane(self, forward):
        panes = [self.address] if self.toolbar.IsShown() else []
        if self.view.IsSplit():
            panes.append(self.view.tree)
        panes.append(self.view.list)
        focus = wx.Window.FindFocus()
        index = panes.index(focus) if focus in panes else -1
        panes[(index + (1 if forward else -1)) % len(panes)].SetFocus()

    def on_command(self, event):
        identifier = event.GetId()
        if identifier in UNAVAILABLE:
            return
        if identifier == ID_CLOSE:
            self.Close()
        elif identifier == ID_ABOUT:
            self.frontend.show_about(self)
        elif identifier == ID_COMMUNICATIONS:
            self.frontend.show_connection_settings(self)
        elif identifier == ID_SYNCHRONIZE_NOW:
            self.frontend.synchronize_now()
        elif identifier == ID_SYNCHRONIZATION_MANAGER:
            self.frontend.show_synchronization_manager(self)
        elif identifier == ID_BACKUP_RESTORE:
            self.frontend.show_backup_restore(self)
        elif identifier == ID_BACK_UP_NOW:
            self.frontend.back_up_now(self)
        elif identifier == ID_FILE_CONVERSION:
            self.frontend.show_file_conversion(self)
        elif identifier == ID_OPTIONS:
            with OptionsSheet(self, self.view_settings, self.apply_view_settings) as sheet:
                sheet.ShowModal()
        elif identifier == ID_TOOLBAR:
            self.toggle_setting("show_toolbar", self.toolbar)
        elif identifier == ID_STATUS_BAR:
            self.toggle_setting("show_status_bar", self.status_bar)
        elif identifier == ID_FOLDERS:
            self.view_settings.show_folders = not self.view_settings.show_folders
            self.view_settings.save()
            self.view.set_tree_visible(self.view_settings.show_folders)
            self.description.Refresh()
            self.update_title()
        elif identifier in VIEW_COMMANDS:
            self.view_settings.view = VIEW_COMMANDS[identifier]
            self.view_settings.save()
            self.view.set_view(self.view_settings.view)
        elif identifier == ID_ADDRESS:
            if self.toolbar.IsShown():
                self.address.SetFocus()
                self.address.Popup()
        elif identifier in (ID_NEXT_PANE, ID_PREVIOUS_PANE):
            self.switch_pane(identifier == ID_NEXT_PANE)
        elif identifier == ID_CANCEL_MODE:
            if self.clipboard and self.clipboard[0] == CUT:
                self.clipboard = None
        elif self.browser:
            self.browser_command(identifier, event)
        else:
            event.Skip()

    def browser_command(self, identifier, event):
        browser = self.browser
        if identifier in ARRANGE_COMMANDS:
            browser.arrange(identifier)
        elif identifier == ID_UP:
            if self.folder != "\\":
                browser.navigate(parent_folder(self.folder))
        elif identifier == ID_REFRESH:
            browser.refresh()
        elif identifier == ID_OPEN:
            browser.open_selected()
        elif identifier == ID_NEW_FOLDER:
            browser.new_folder()
        elif identifier == ID_DELETE:
            if not browser.selection_in_rom():
                browser.delete_selected()
        elif identifier == ID_RENAME:
            if not browser.selection_in_rom():
                browser.rename_selected()
        elif identifier == ID_PROPERTIES:
            browser.show_properties()
        elif identifier == ID_SELECT_ALL:
            browser.select_all()
        elif identifier == ID_INVERT_SELECTION:
            browser.invert_selection()
        elif identifier in (ID_CUT, ID_COPY):
            self.set_clipboard(CUT if identifier == ID_CUT else COPY)
        elif identifier == ID_PASTE:
            self.paste()
        elif identifier == ID_PASTE_SHORTCUT:
            browser.paste_shortcut()
        elif identifier == ID_PRINT:
            browser.print_selected()
        elif identifier == ID_CREATE_SHORTCUT:
            browser.create_shortcut_selected()
        elif identifier == ID_CONTEXT_MENU:
            browser._on_context_menu(None)
        else:
            event.Skip()

    def set_clipboard(self, mode):
        entries = self.browser.selected_entries()
        if not entries or (mode == CUT and self.browser.selection_in_rom()):
            return
        self.clipboard = (mode, self.folder, entries) if entries else None

    def paste(self):
        if self.clipboard:
            if self.browser.paste_from_device(self.clipboard):
                self.clipboard = None
            return
        files = self._system_clipboard_files()
        if files:
            self.browser.upload(files)

    def toggle_setting(self, name, control):
        visible = not getattr(self.view_settings, name)
        setattr(self.view_settings, name, visible)
        self.view_settings.save()
        control.Show(visible)
        self.body.Layout()
        self.SendSizeEvent()

    def apply_view_settings(self):
        self.description.Show(self.view_settings.description_bars)
        self.body.Layout()
        self.update_title()
        if self.browser:
            self.browser.refresh()

    def on_update_ui(self, event):
        identifier = event.GetId()
        if identifier in UNAVAILABLE:
            event.Enable(False)
        elif identifier in VIEW_COMMANDS:
            event.Check(self.view_settings.view == VIEW_COMMANDS[identifier])
        elif identifier == ID_FOLDERS:
            event.Check(self.view_settings.show_folders)
        elif identifier == ID_TOOLBAR:
            event.Check(self.view_settings.show_toolbar)
        elif identifier == ID_STATUS_BAR:
            event.Check(self.view_settings.show_status_bar)
        elif identifier in ARRANGE_COMMANDS or identifier in (ID_REFRESH, ID_NEW_FOLDER, ID_SELECT_ALL, ID_INVERT_SELECTION):
            event.Enable(self.browser is not None)
        elif identifier == ID_SYNCHRONIZE_NOW:
            event.Enable(self.frontend.can_synchronize())
        elif identifier == ID_SYNCHRONIZATION_MANAGER:
            event.Enable(self.frontend.connected())
        elif identifier in (ID_BACKUP_RESTORE, ID_BACK_UP_NOW):
            event.Enable(self.frontend.can_back_up())
        elif identifier == ID_UP:
            event.Enable(self.browser is not None and self.folder != "\\")
        elif identifier == ID_PASTE:
            event.Enable(self.can_paste())
        elif identifier == ID_PASTE_SHORTCUT:
            event.Enable(self.browser is not None and self.clipboard is not None)
        elif identifier == ID_PRINT:
            event.Enable(self.browser is not None and any(not entry.is_directory for entry in self.browser.selected_entries()))
        elif identifier in (ID_OPEN, ID_CUT, ID_COPY, ID_CREATE_SHORTCUT, ID_DELETE, ID_RENAME, ID_PROPERTIES):
            event.Enable(self.selection_allows(identifier))

    def selection_allows(self, identifier):
        if not self.browser:
            return False
        entries = self.browser.selected_entries()
        if not entries:
            return False
        if identifier in (ID_OPEN, ID_PROPERTIES):
            return len(entries) == 1
        if identifier == ID_COPY:
            return True
        in_rom = self.browser.selection_in_rom()
        if identifier == ID_RENAME:
            return len(entries) == 1 and not in_rom
        return not in_rom

    def on_close(self, event):
        rect = self.GetRect()
        self.view_settings.window_rect = [rect.x, rect.y, rect.width, rect.height]
        if self.view.IsSplit():
            self.view_settings.sash_position = self.view.GetSashPosition()
        self.view_settings.save()
        if event.CanVeto() and self.frontend.tray:
            self.Hide()
            event.Veto()
            return
        self.Destroy()
        self.frontend.explorer_window = None
