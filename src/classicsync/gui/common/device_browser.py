import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

import wx

from ...convert import ConversionError, converter
from ...convert.rules import DESKTOP_TO_DEVICE, DEVICE_TO_DESKTOP, desktop_conversion, device_conversion
from ...i18n import N_, _, format_original, ngettext
from ...rapi.client import RapiError
from ...rapi.structures import (
    FILE_ATTRIBUTE_ARCHIVE, FILE_ATTRIBUTE_DIRECTORY, FILE_ATTRIBUTE_HIDDEN, FILE_ATTRIBUTE_INROM, FILE_ATTRIBUTE_READONLY,
    FILE_ATTRIBUTE_SYSTEM, FindData, datetime_to_filetime, filetime_to_datetime,
)
from .file_icons import FileIcons
from .icon_grid import ItemListView
from .layout import dialog_size, place
from .printing import print_file
from .replace_dialog import FileFacts, ReplacePrompt
from .transfers import (
    REPLACE_CANCEL, REPLACE_OVERWRITE, TransferTree, copy_name, device_join, device_moment, device_tree, local_moment, local_tree,
    lower_key, plan_transfer, shortcut_name, unused_path,
)

COMMAND_OPEN = wx.NewIdRef()
COMMAND_COPY_TO_COMPUTER = wx.NewIdRef()
COMMAND_COPY_FROM_COMPUTER = wx.NewIdRef()
COMMAND_DELETE = wx.NewIdRef()
COMMAND_RENAME = wx.NewIdRef()
COMMAND_PROPERTIES = wx.NewIdRef()
COMMAND_NEW_FOLDER = wx.NewIdRef()
COMMAND_UP = wx.NewIdRef()
COMMAND_REFRESH = wx.NewIdRef()
COMMAND_SELECT_ALL = wx.NewIdRef()
COMMAND_INVERT_SELECTION = wx.NewIdRef()
COMMAND_CUT = wx.NewIdRef()
COMMAND_COPY = wx.NewIdRef()
COMMAND_PASTE = wx.NewIdRef()
COMMAND_PASTE_SHORTCUT = wx.NewIdRef()
COMMAND_CREATE_SHORTCUT = wx.NewIdRef()

CUT = "cut"
COPY = "copy"

VIEW_LARGE = "large"
VIEW_SMALL = "small"
VIEW_LIST = "list"
VIEW_DETAILS = "details"
VIEW_STYLES = {VIEW_LARGE: wx.LC_ICON, VIEW_SMALL: wx.LC_SMALL_ICON, VIEW_LIST: wx.LC_LIST, VIEW_DETAILS: wx.LC_REPORT}

COLUMNS = [(N_("Name"), 220, wx.LIST_FORMAT_LEFT), (N_("Size"), 80, wx.LIST_FORMAT_RIGHT),
           (N_("Type"), 160, wx.LIST_FORMAT_LEFT), (N_("Modified"), 130, wx.LIST_FORMAT_LEFT)]

SORT_NAME = 0
SORT_SIZE = 1
SORT_TYPE = 2
SORT_DATE = 3

FILE_TYPES = {
    ".pwd": N_("Pocket Word Document"), ".pwt": N_("Pocket Word Template"), ".pxl": N_("Pocket Excel Workbook"),
    ".pxt": N_("Pocket Excel Template"), ".exe": N_("Application"), ".dll": N_("Application Extension"),
    ".txt": N_("Text Document"), ".htm": N_("HTML Document"), ".html": N_("HTML Document"), ".lnk": N_("Shortcut"),
    ".2bp": N_("2bp Image"), ".bmp": N_("Bitmap Image"), ".wav": N_("Wave Sound"), ".cab": N_("Cabinet File"),
    ".fon": N_("Font file"), ".fnt": N_("Font file"), ".ttf": N_("TrueType Font"), ".cdb": N_("Pocket Access Database"),
    ".hlp": N_("Help File"), ".ini": N_("Configuration Settings"), ".pwi": N_("Pocket Word Ink"),
}

ROOT_NAMES = {"PocketPC": N_("My Pocket PC"), "Palm PC": N_("Palm PC"), "Palm PC2": N_("Palm PC")}
HANDHELD_ROOT_NAME = N_("My Handheld PC")
INVALID_NAME_CHARACTERS = '\\/:*?"<>|'

IMAGE_FOLDER = 0
IMAGE_FOLDER_OPEN = 1
IMAGE_FILE = 2
IMAGE_DEVICE = 3


def root_name(announcement):
    platform = announcement.info.platform if announcement and announcement.info else ""
    return _(ROOT_NAMES.get(platform, HANDHELD_ROOT_NAME))


def join(folder, name):
    return folder.rstrip("\\") + "\\" + name


def parent_folder(folder):
    if folder in ("", "\\"):
        return "\\"
    parent = folder.rstrip("\\").rsplit("\\", 1)[0]
    return parent or "\\"


def describe_type(entry):
    if entry.is_directory:
        return _("File Folder")
    extension = os.path.splitext(entry.name)[1].lower()
    if extension in FILE_TYPES:
        return _(FILE_TYPES[extension])
    return format_original(_("%s File"), extension[1:].upper()) if extension else _("File")


def format_size(size):
    if size < 1024:
        return format_original(_("%s bytes"), size) if size != 1 else _("1 byte")
    return format_original(_("%sKB"), f"{(size + 1023) // 1024:,}")


def existing_entries(entries):
    return {(entry.name.lower(),): (entry.is_directory, entry.size, device_moment(entry.last_write_time)) for entry in entries}


def system_clipboard_files():
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


def format_time(filetime):
    moment = filetime_to_datetime(filetime)
    if not moment:
        return ""
    return moment.replace(tzinfo=timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")


class FileDrop(wx.FileDropTarget):
    def __init__(self, browser):
        super().__init__()
        self.browser = browser

    def OnDropFiles(self, x, y, filenames):
        self.browser.upload(filenames)
        return True


class PropertiesDialog(wx.Dialog):
    def __init__(self, parent, entry, location):
        super().__init__(parent, title=format_original(_("%1 Properties"), entry.name))
        notebook = wx.Notebook(self)
        page = wx.Panel(notebook)
        notebook.AddPage(page, _("General"))
        page.SetClientSize(dialog_size(page, 212, 188))
        icon = wx.ArtProvider.GetBitmap(wx.ART_FOLDER if entry.is_directory else wx.ART_NORMAL_FILE, wx.ART_OTHER, wx.Size(32, 32))
        wx.StaticBitmap(page, bitmap=icon, pos=page.ConvertDialogToPixels(wx.Point(7, 7)))
        place(page, wx.TextCtrl, 52, 10, 150, 12, entry.name, style=wx.TE_READONLY)
        place(page, wx.StaticLine, 7, 32, 196, 1)
        rows = [(_("Type:"), describe_type(entry)), (_("Location:"), location)]
        if not entry.is_directory:
            rows.append((_("Size:"), format_original(_("%1 (%2!d! bytes)"), format_size(entry.size), entry.size)))
        rows.append((_("Modified:"), format_time(entry.last_write_time)))
        for index, (label, value) in enumerate(rows):
            place(page, wx.StaticText, 7, 40 + index * 14, 42, 9, label, style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
            place(page, wx.StaticText, 52, 40 + index * 14, 150, 9, value, style=wx.ST_ELLIPSIZE_MIDDLE)
        top = 40 + len(rows) * 14 + 4
        place(page, wx.StaticLine, 7, top, 196, 1)
        place(page, wx.StaticText, 7, top + 8, 42, 9, _("Attributes:"), style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
        attributes = [(_("&Read-only"), FILE_ATTRIBUTE_READONLY), (_("Hi&dden"), FILE_ATTRIBUTE_HIDDEN),
                      (_("Ar&chive"), FILE_ATTRIBUTE_ARCHIVE), (_("System"), FILE_ATTRIBUTE_SYSTEM)]
        for index, (label, bit) in enumerate(attributes):
            box = place(page, wx.CheckBox, 52 + (index % 2) * 70, top + 8 + (index // 2) * 12, 65, 10, label)
            box.SetValue(bool(entry.attributes & bit))
            box.Enable(False)
        if entry.attributes & FILE_ATTRIBUTE_INROM:
            place(page, wx.StaticText, 52, top + 34, 150, 9, _("This file is in ROM."))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(notebook, 1, wx.EXPAND | wx.ALL, 6)
        sizer.Add(self.CreateButtonSizer(wx.OK), 0, wx.ALIGN_RIGHT | wx.ALL, 6)
        self.SetSizerAndFit(sizer)
        self.CentreOnParent()


class DeviceBrowser(wx.SplitterWindow):
    def __init__(self, parent, application, root_label, on_status=None, on_title=None, on_folder=None, file_icons=None):
        super().__init__(parent, style=wx.SP_LIVE_UPDATE)
        self.application = application
        self.root_label = root_label
        self.on_status = on_status or (lambda text, field=0: None)
        self.on_title = on_title or (lambda title: None)
        self.on_folder = on_folder or (lambda folder: None)
        self.folder = "\\"
        self.entries = []
        self.entries_view = []
        self.sort_column = SORT_NAME
        self.sort_ascending = True
        self.view = VIEW_DETAILS
        self.tree_width = 190
        self.context_menu_factory = None
        self.connected = True

        self.file_icons = file_icons or FileIcons()
        self.small_images = self.file_icons.image_list(16)
        self.large_images = self.file_icons.image_list(32)
        self.tree = wx.TreeCtrl(self, style=wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT | wx.TR_SINGLE)
        self.tree.SetImageList(self.small_images)
        self.tree_root = self.tree.AddRoot(root_label, IMAGE_DEVICE)
        self.tree.SetItemData(self.tree_root, "\\")
        self.tree.SetItemHasChildren(self.tree_root, True)

        self.list = ItemListView(self, style=wx.LC_REPORT | wx.LC_EDIT_LABELS)
        self.list.SetImageList(self.small_images, wx.IMAGE_LIST_SMALL)
        self.list.SetImageList(self.large_images, wx.IMAGE_LIST_NORMAL)
        self._add_columns()
        self.SplitVertically(self.tree, self.list, self.tree_width)
        self.SetMinimumPaneSize(80)
        self.list.SetDropTarget(FileDrop(self))
        wx.CallAfter(self.tree.Expand, self.tree_root)

        self.tree.Bind(wx.EVT_TREE_ITEM_EXPANDING, self._on_tree_expanding)
        self.tree.Bind(wx.EVT_TREE_SEL_CHANGED, self._on_tree_selected)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_item_activated)
        self.list.Bind(wx.EVT_LIST_COL_CLICK, self._on_column_click)
        self.list.Bind(wx.EVT_LIST_END_LABEL_EDIT, self._on_rename_done)
        self.list.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_selection_changed)
        self.list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self._on_selection_changed)
        self.Bind(wx.EVT_MENU, self.on_command)

    def _add_columns(self):
        for index, (label, width, align) in enumerate(COLUMNS):
            self.list.InsertColumn(index, _(label), align, width)

    @property
    def tree_visible(self):
        return self.IsSplit()

    def set_tree_visible(self, visible):
        if visible and not self.IsSplit():
            self.tree.Show()
            self.SplitVertically(self.tree, self.list, self.tree_width)
        elif not visible and self.IsSplit():
            self.tree_width = self.GetSashPosition()
            self.Unsplit(self.tree)

    def set_view(self, view):
        self.view = view
        self.list.SetWindowStyleFlag((self.list.GetWindowStyleFlag() & ~(wx.LC_ICON | wx.LC_SMALL_ICON | wx.LC_LIST | wx.LC_REPORT)) | VIEW_STYLES[view])
        if view == VIEW_DETAILS and self.list.GetColumnCount() == 0:
            self._add_columns()
        self._fill_list()

    def sort_by(self, column):
        self.sort_column = column
        self.sort_ascending = True
        self._fill_list()

    def run(self, operation, on_success=None, on_error=None):
        def finished(future):
            error = future.exception()
            if error:
                wx.CallAfter(on_error or self.show_error, error)
            elif on_success:
                wx.CallAfter(on_success, future.result())
        service = self.application.service
        service.submit(service.with_rapi(operation)).add_done_callback(finished)

    def show_error(self, error):
        if not self:
            return
        self.on_status("", 0)
        wx.MessageBox(str(error), self.root_label, wx.OK | wx.ICON_ERROR, self)

    def location_label(self, folder=None):
        folder = self.folder if folder is None else folder
        return self.root_label if folder == "\\" else self.root_label + folder

    def navigate(self, folder, then=None):
        if not self.connected:
            return
        self.folder = folder
        self.on_title(self.root_label if folder == "\\" else folder.rsplit("\\", 1)[-1])
        self.on_folder(folder)
        self.on_status(_("Reading folder..."), 0)
        pattern = join(folder, "*.*")

        async def read(client):
            entries = await client.find_all_files(pattern)
            try:
                store = await client.get_store_information()
            except RapiError:
                store = None
            return entries, store

        def shown(result):
            self._show_folder(result)
            if then and self:
                then()

        self.run(read, shown)

    def refresh(self, then=None):
        self.navigate(self.folder, then)

    def go_up(self):
        self.navigate(parent_folder(self.folder))

    def _show_folder(self, result):
        if not self:
            return
        entries, store = result
        self.entries = entries
        self._fill_list()
        self.on_status(format_original(_("%1!d! object(s)"), len(entries)), 0)
        if store:
            self.on_status(_("Free space: {size}").format(size=format_size(store.free_size)), 1)

    def _fill_list(self):
        selected = {self.entries_view[index].name for index in self._selected_indices()} if self.entries_view else set()
        keys = [lambda entry: entry.name.lower(), lambda entry: entry.size, lambda entry: describe_type(entry).lower(),
                lambda entry: entry.last_write_time]
        ordered = sorted(self.entries, key=keys[self.sort_column], reverse=not self.sort_ascending)
        self.entries_view = sorted(ordered, key=lambda entry: not entry.is_directory)
        self.list.DeleteAllItems()
        for index, entry in enumerate(self.entries_view):
            self.list.InsertItem(index, entry.name, self.file_icons.index_for(entry))
            if self.view == VIEW_DETAILS:
                self.list.SetItem(index, 1, "" if entry.is_directory else format_size(entry.size))
                self.list.SetItem(index, 2, describe_type(entry))
                self.list.SetItem(index, 3, format_time(entry.last_write_time))
            if entry.name in selected:
                self.list.Select(index)

    def _selected_indices(self):
        indices = []
        index = self.list.GetFirstSelected()
        while index != -1:
            indices.append(index)
            index = self.list.GetNextSelected(index)
        return indices

    def selected_entries(self):
        return [self.entries_view[index] for index in self._selected_indices()]

    def select_all(self):
        for index in range(self.list.GetItemCount()):
            self.list.Select(index)

    def invert_selection(self):
        for index in range(self.list.GetItemCount()):
            self.list.Select(index, not self.list.IsSelected(index))

    def _on_selection_changed(self, event):
        count = len(self._selected_indices())
        if count:
            self.on_status(format_original(_("%1!d! object(s) selected"), count), 0)
        else:
            self.on_status(format_original(_("%1!d! object(s)"), len(self.entries)), 0)
        event.Skip()

    def _on_tree_expanding(self, event):
        item = event.GetItem()
        if self.tree.GetChildrenCount(item, False):
            return
        folder = self.tree.GetItemData(item)

        async def read(client):
            return await client.find_all_files(join(folder, "*.*"))

        def show(entries):
            if not self:
                return
            folders = sorted((entry for entry in entries if entry.is_directory), key=lambda entry: entry.name.lower())
            for entry in folders:
                child = self.tree.AppendItem(item, entry.name, IMAGE_FOLDER, IMAGE_FOLDER_OPEN)
                self.tree.SetItemData(child, join(folder, entry.name))
                self.tree.SetItemHasChildren(child, True)
            if not folders:
                self.tree.SetItemHasChildren(item, False)

        self.run(read, show)

    def _on_tree_selected(self, event):
        item = event.GetItem()
        if item.IsOk():
            folder = self.tree.GetItemData(item)
            if folder and folder != self.folder:
                self.navigate(folder)

    def _on_item_activated(self, event):
        entry = self.entries_view[event.GetIndex()]
        if entry.is_directory:
            self.navigate(join(self.folder, entry.name))
        else:
            self.copy_to_computer([entry])

    def _on_column_click(self, event):
        column = event.GetColumn()
        self.sort_ascending = not self.sort_ascending if column == self.sort_column else True
        self.sort_column = column
        self._fill_list()

    def default_context_menu(self, entries):
        menu = wx.Menu()
        if entries:
            if len(entries) == 1 and entries[0].is_directory:
                menu.Append(COMMAND_OPEN, _("&Open"))
                menu.AppendSeparator()
            menu.Append(COMMAND_COPY_TO_COMPUTER, _("Copy to This Computer..."))
            menu.AppendSeparator()
            in_rom = self.in_rom(entries)
            menu.Append(COMMAND_CUT, _("Cu&t")).Enable(not in_rom)
            menu.Append(COMMAND_COPY, _("&Copy")).Enable(not in_rom)
            menu.Append(COMMAND_PASTE, _("&Paste")).Enable(self.can_paste())
            menu.AppendSeparator()
            menu.Append(COMMAND_CREATE_SHORTCUT, _("Create &Shortcut")).Enable(not in_rom)
            menu.Append(COMMAND_DELETE, _("&Delete")).Enable(not in_rom)
            menu.Append(COMMAND_RENAME, _("Rena&me")).Enable(len(entries) == 1 and not in_rom)
            menu.AppendSeparator()
            menu.Append(COMMAND_PROPERTIES, _("P&roperties")).Enable(len(entries) == 1)
        else:
            menu.Append(COMMAND_PASTE, _("&Paste")).Enable(self.can_paste())
            menu.Append(COMMAND_PASTE_SHORTCUT, _("Paste &Shortcut")).Enable(self.clipboard is not None)
            menu.AppendSeparator()
            menu.Append(COMMAND_NEW_FOLDER, _("Ne&w Folder"))
            menu.Append(COMMAND_COPY_FROM_COMPUTER, _("Copy &Files Here..."))
            menu.AppendSeparator()
            menu.Append(COMMAND_REFRESH, _("R&efresh"))
        return menu

    def _on_context_menu(self, event):
        entries = self.selected_entries()
        factory = self.context_menu_factory or self.default_context_menu
        menu = factory(entries)
        self.PopupMenu(menu)
        menu.Destroy()

    def on_command(self, event):
        identifier = event.GetId()
        entries = self.selected_entries()
        if identifier == COMMAND_UP:
            self.go_up()
        elif identifier == COMMAND_REFRESH:
            self.refresh()
        elif identifier == COMMAND_OPEN and entries:
            self.open_selected()
        elif identifier == COMMAND_COPY_TO_COMPUTER and entries:
            self.copy_to_computer(entries)
        elif identifier == COMMAND_COPY_FROM_COMPUTER:
            self.add_files_dialog()
        elif identifier == COMMAND_DELETE and entries:
            self.delete(entries)
        elif identifier == COMMAND_RENAME and len(entries) == 1:
            self.rename_selected()
        elif identifier == COMMAND_PROPERTIES and len(entries) == 1:
            self.show_properties()
        elif identifier == COMMAND_NEW_FOLDER:
            self.new_folder()
        elif identifier == COMMAND_SELECT_ALL:
            self.select_all()
        elif identifier == COMMAND_INVERT_SELECTION:
            self.invert_selection()
        elif identifier in (COMMAND_CUT, COMMAND_COPY) and entries:
            self.set_clipboard(CUT if identifier == COMMAND_CUT else COPY, entries)
        elif identifier == COMMAND_PASTE:
            self.paste()
        elif identifier == COMMAND_PASTE_SHORTCUT:
            self.paste_shortcut()
        elif identifier == COMMAND_CREATE_SHORTCUT and entries:
            self.create_shortcut_selected()
        else:
            event.Skip()

    def open_selected(self):
        entries = self.selected_entries()
        if len(entries) == 1 and entries[0].is_directory:
            self.navigate(join(self.folder, entries[0].name))
        elif entries:
            self.copy_to_computer(entries)

    def rename_selected(self):
        indices = self._selected_indices()
        if len(indices) == 1:
            self.list.EditLabel(indices[0])

    def show_properties(self):
        entries = self.selected_entries()
        if len(entries) != 1:
            return
        with PropertiesDialog(self, entries[0], self.location_label()) as dialog:
            dialog.ShowModal()

    def remember_folder(self, name, folder):
        settings = self.application.settings
        if getattr(settings, name, None) != str(folder):
            setattr(settings, name, str(folder))
            settings.save()

    def add_files_dialog(self):
        start = getattr(self.application.settings, "last_upload_folder", "")
        with wx.FileDialog(self, _("Copy to Mobile Device"), defaultDir=start,
                           style=wx.FD_OPEN | wx.FD_MULTIPLE | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                paths = dialog.GetPaths()
                if paths:
                    self.remember_folder("last_upload_folder", Path(paths[0]).parent)
                self.upload(paths)

    def new_folder(self):
        existing = {entry.name.lower() for entry in self.entries}
        base_name = _("New Folder")
        name = base_name
        counter = 2
        while name.lower() in existing:
            name = f"{base_name} ({counter})"
            counter += 1
        target = join(self.folder, name)

        async def create(client):
            await client.create_directory(target)

        self.run(create, lambda _: self.refresh())

    def _on_rename_done(self, event):
        if event.IsEditCancelled():
            return
        entry = self.entries_view[event.GetIndex()]
        new_name = event.GetLabel().strip()
        if not new_name or new_name == entry.name:
            return
        if any(character in new_name for character in INVALID_NAME_CHARACTERS):
            event.Veto()
            wx.MessageBox(_("A file name cannot contain any of the following characters: \\ / : * ? \" < > |"), self.root_label,
                          wx.OK | wx.ICON_WARNING, self)
            return
        source = join(self.folder, entry.name)
        destination = join(self.folder, new_name)

        async def rename(client):
            await client.move_file(source, destination)

        self.run(rename, lambda _: self.refresh(), lambda error: (self.show_error(error), self.refresh()))

    def delete_selected(self):
        entries = self.selected_entries()
        if entries:
            self.delete(entries)

    def delete(self, entries):
        if len(entries) == 1:
            question = _("Are you sure you want to delete '{name}'?").format(name=entries[0].name)
        else:
            question = _("Are you sure you want to delete these items?")
        caption = _("Confirm File Delete") if len(entries) == 1 and not entries[0].is_directory else _("Confirm Delete")
        if wx.MessageBox(question, caption, wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            return
        paths = [(join(self.folder, entry.name), entry.is_directory) for entry in entries]

        async def remove_tree(client, path):
            for child in await client.find_all_files(join(path, "*.*")):
                child_path = join(path, child.name)
                if child.is_directory:
                    await remove_tree(client, child_path)
                else:
                    await client.delete_file(child_path)
            await client.remove_directory(path)

        async def remove(client):
            for path, is_directory in paths:
                if is_directory:
                    await remove_tree(client, path)
                else:
                    await client.delete_file(path)

        self.run(remove, lambda _: self.refresh(), lambda error: (self.show_error(error), self.refresh()))

    def _transfer(self, title, jobs, operation, on_finished, prepare=None, animation=None):
        total = sum(size for _, _, size in jobs) or 1
        progress = wx.ProgressDialog(title, _("Preparing..."), maximum=1000, parent=self.GetTopLevelParent(),
                                     style=wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_AUTO_HIDE | wx.PD_ELAPSED_TIME | wx.PD_REMAINING_TIME)
        state = {"cancelled": False}

        def report(label, done_in_file, base):
            def update():
                if not progress:
                    return
                keep_going, _ = progress.Update(min(999, int((base + done_in_file) * 1000 / total)), label)
                if not keep_going:
                    state["cancelled"] = True
            wx.CallAfter(update)
            if state["cancelled"]:
                raise InterruptedError("cancelled")

        async def run_all(client):
            if prepare:
                await prepare(client)
            base = 0
            for source, destination, size in jobs:
                label = _("Copying '{name}'").format(name=os.path.basename(str(source).replace(chr(92), "/")))
                await operation(client, source, destination, lambda done, base=base, label=label: report(label, done, base))
                base += size
            return len(jobs)

        def finish(result):
            progress.Destroy()
            on_finished(result)

        def fail(error):
            progress.Destroy()
            if not isinstance(error, InterruptedError):
                self.show_error(error)
            on_finished(None)

        self.run(run_all, finish, fail)

    def transfer_summary(self, count, target, outcomes, warnings):
        message = ngettext("Copied {count} file to {target}", "Copied {count} files to {target}", count).format(count=count, target=target)
        details = [text for text in (
            ngettext("{count} replaced", "{count} replaced", outcomes["replaced"]).format(count=outcomes["replaced"]) if outcomes["replaced"] else "",
            ngettext("{count} saved under a new name", "{count} saved under new names", outcomes["renamed"]).format(count=outcomes["renamed"])
            if outcomes["renamed"] else "",
            ngettext("{count} skipped", "{count} skipped", outcomes["skipped"]).format(count=outcomes["skipped"]) if outcomes["skipped"] else "",
        ) if text] + warnings[:2]
        self.on_status(message + (" (" + "; ".join(details) + ")" if details else ""), 0)


    def conversion_enabled(self):
        return getattr(self.application.settings, "convert_files", True)

    def conversion_rules(self, direction):
        settings = self.application.settings
        return dict(getattr(settings, "device_to_desktop" if direction == DEVICE_TO_DESKTOP else "desktop_to_device", {}) or {})

    def device_version(self):
        major = self.application.device_major_version(self.application.service.announcement)
        return 1 if major == 1 else 2

    def entry_bitmap(self, name, is_directory=False):
        entry = FindData(name=name, attributes=FILE_ATTRIBUTE_DIRECTORY if is_directory else 0)
        return self.large_images.GetBitmap(self.file_icons.index_for(entry))

    def replace_prompt(self, keep_both=False):
        return ReplacePrompt(self, self.file_icons.artwork, keep_both)

    def copy_to_computer(self, entries=None, target=None):
        entries = entries if entries is not None else self.selected_entries()
        if not entries:
            return
        if target is None:
            start = getattr(self.application.settings, "last_download_folder", "") or str(Path.home() / "Desktop")
            with wx.DirDialog(self, _("Copy to which folder on this computer?"), start) as dialog:
                if dialog.ShowModal() != wx.ID_OK:
                    return
                target = Path(dialog.GetPath())
            self.remember_folder("last_download_folder", target)
        target = Path(target)
        source_folder = self.folder
        tree = TransferTree()
        for entry in entries:
            if not entry.is_directory:
                tree.files.append((join(source_folder, entry.name), (entry.name,), entry.size))
                tree.modified[(entry.name,)] = device_moment(entry.last_write_time)
        folders = [entry.name for entry in entries if entry.is_directory]
        if not folders:
            self.download_tree(tree, target)
            return

        async def gather(client):
            for name in folders:
                tree.folders.append((name,))
                tree.add(await device_tree(client, join(source_folder, name), (name,)))
            return tree

        self.on_status(_("Reading folder..."), 0)
        self.run(gather, lambda gathered: self.download_tree(gathered, target))

    def download_tree(self, tree, target):
        convert = self.conversion_enabled()
        rules = self.conversion_rules(DEVICE_TO_DESKTOP)

        def destination(relative):
            plan = desktop_conversion(relative[-1], rules) if convert and relative in tree.modified else None
            return relative[:-1] + (plan[2] if plan else relative[-1],)

        def existing_file(relative):
            path = target.joinpath(*relative)
            if not path.is_file():
                return None
            return FileFacts(path.stat().st_size, local_moment(path), self.entry_bitmap(relative[-1]))

        def incoming(source, relative, size):
            return FileFacts(size, tree.modified.get(relative), self.entry_bitmap(relative[-1]))

        def keep_both(relative, taken):
            taken_paths = {target.joinpath(*key) for key in taken}
            return unused_path(target.joinpath(*relative), taken_paths).relative_to(target).parts

        plan = plan_transfer(tree, self.replace_prompt(keep_both=True), destination, existing_file,
                             lambda relative: target.joinpath(*relative).is_dir(), incoming, keep_both)
        if plan.cancelled or not (plan.jobs or plan.folders):
            self.on_status(_("No files copied"), 0)
            return
        jobs = [(source, target.joinpath(*relative), size) for source, relative, size in plan.jobs]
        local_folders = [target.joinpath(*relative) for relative in plan.folders]
        warnings = []

        async def make_folders(client):
            for folder in local_folders:
                folder.mkdir(parents=True, exist_ok=True)

        async def download(client, source, destination_path, progress):
            data = await client.read_file_contents(source, progress=progress)
            conversion_plan = desktop_conversion(source.rsplit("\\", 1)[-1], rules) if convert else None
            if conversion_plan:
                try:
                    conversion = converter(conversion_plan[0], conversion_plan[1])(data)
                    data = conversion.data
                    warnings.extend(conversion.warnings)
                except (ConversionError, ValueError) as error:
                    warnings.append(str(error))
                    destination_path = destination_path.with_name(source.rsplit("\\", 1)[-1])
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            destination_path.write_bytes(data)

        def finished(count):
            if count is not None:
                self.transfer_summary(count, target, plan.outcomes, warnings)

        self._transfer(_("Copying..."), jobs, download, finished, prepare=make_folders)

    def convert_fonts(self, tree):
        if not self.conversion_enabled():
            return tree
        from .font_conversion import ask_font_conversion
        rules = self.conversion_rules(DESKTOP_TO_DEVICE)
        version = self.device_version()
        converted = TransferTree(folders=list(tree.folders), modified=dict(tree.modified))
        folder = None
        for path, relative, size in tree.files:
            plan = device_conversion(relative[-1], version, rules)
            if not plan or plan[1] != "fnt":
                converted.files.append((path, relative, size))
                continue
            files = ask_font_conversion(self, str(path))
            if not files:
                continue
            folder = folder or Path(tempfile.mkdtemp(prefix="classicsync-fonts-"))
            for name, data in files:
                output = folder / name
                output.write_bytes(data)
                output_relative = relative[:-1] + (name,)
                converted.files.append((output, output_relative, len(data)))
                converted.modified[output_relative] = tree.modified.get(relative)
        return converted

    def upload(self, filenames):
        tree = self.convert_fonts(local_tree(filenames))
        if not tree.files and not tree.folders:
            return
        destination_folder = self.folder
        existing = existing_entries(self.entries)
        merging = [relative[0] for relative in tree.folders if len(relative) == 1 and existing.get(lower_key(relative), (False,))[0]]
        if not merging:
            self.upload_tree(tree, destination_folder, existing)
            return

        async def gather(client):
            found = dict(existing)
            for name in merging:
                below = await device_tree(client, join(destination_folder, name), (name,))
                for source, relative, size in below.files:
                    found[lower_key(relative)] = (False, size, below.modified.get(relative))
                for relative in below.folders:
                    found[lower_key(relative)] = (True, 0, None)
            return found

        self.on_status(_("Reading folder..."), 0)
        self.run(gather, lambda found: self.upload_tree(tree, destination_folder, found))

    def upload_tree(self, tree, destination_folder, existing):
        convert = self.conversion_enabled()
        version = self.device_version()
        rules = self.conversion_rules(DESKTOP_TO_DEVICE)

        def destination(relative):
            plan = device_conversion(relative[-1], version, rules) if convert and relative in tree.modified else None
            return relative[:-1] + (plan[2] if plan else relative[-1],)

        def existing_file(relative):
            is_directory, size, moment = existing.get(lower_key(relative), (True, 0, None))
            return None if is_directory else FileFacts(size, moment, self.entry_bitmap(relative[-1]))

        def existing_folder(relative):
            return existing.get(lower_key(relative), (False,))[0]

        def incoming(source, relative, size):
            return FileFacts(size, tree.modified.get(relative), self.entry_bitmap(relative[-1]))

        plan = plan_transfer(tree, self.replace_prompt(), destination, existing_file, existing_folder, incoming)
        if plan.cancelled or not (plan.jobs or plan.folders):
            return
        jobs = [(str(source), device_join(destination_folder, *relative), size) for source, relative, size in plan.jobs]
        device_folders = [device_join(destination_folder, *relative) for relative in plan.folders]
        warnings = []

        async def make_folders(client):
            for folder in device_folders:
                try:
                    await client.create_directory(folder)
                except RapiError:
                    pass

        async def send(client, source, destination_path, progress):
            data = Path(source).read_bytes()
            conversion_plan = device_conversion(Path(source).name, version, rules) if convert else None
            if conversion_plan:
                conversion = converter(conversion_plan[0], conversion_plan[1])(data, version=version)
                data = conversion.data
                warnings.extend(conversion.warnings)
            modified = datetime_to_filetime(datetime.fromtimestamp(Path(source).stat().st_mtime, timezone.utc))
            await client.write_file_contents(destination_path, data, modified=modified, progress=progress)

        def finished(count):
            if count is None:
                self.refresh()
                return
            self.refresh(lambda: self.transfer_summary(count, self.location_label(destination_folder), plan.outcomes, warnings))

        self._transfer(_("Copying..."), jobs, send, finished, prepare=make_folders)

    @property
    def clipboard(self):
        return getattr(self.application, "device_clipboard", None)

    @clipboard.setter
    def clipboard(self, value):
        self.application.device_clipboard = value

    def in_rom(self, entries):
        return any(entry.attributes & FILE_ATTRIBUTE_INROM for entry in entries)

    def set_clipboard(self, mode, entries=None):
        entries = entries if entries is not None else self.selected_entries()
        if not entries or (mode == CUT and self.in_rom(entries)):
            return
        self.clipboard = (mode, self.folder, entries)

    def can_paste(self):
        return self.clipboard is not None or system_clipboard_files() is not None

    def paste(self):
        if self.clipboard:
            if self.paste_from_device(self.clipboard):
                self.clipboard = None
            return
        files = system_clipboard_files()
        if files:
            self.upload(files)

    def paste_animation(self, mode):
        return None

    def paste_from_device(self, clipboard):
        mode, source_folder, entries = clipboard
        if mode == CUT:
            return self.move_here(source_folder, entries)
        destination_folder = self.folder
        existing = existing_entries(self.entries)
        names = {}
        if source_folder == destination_folder:
            taken = {entry.name.lower() for entry in self.entries}
            for entry in entries:
                names[entry.name] = copy_name(entry.name, taken)
                taken.add(names[entry.name].lower())
        tree = TransferTree()
        for entry in entries:
            if not entry.is_directory:
                tree.files.append((join(source_folder, entry.name), (entry.name,), entry.size))
                tree.modified[(entry.name,)] = device_moment(entry.last_write_time)
        folders = [entry.name for entry in entries if entry.is_directory]
        if not folders:
            self.copy_here(tree, names, existing, destination_folder)
            return False

        async def gather(client):
            for name in folders:
                tree.folders.append((name,))
                tree.add(await device_tree(client, join(source_folder, name), (name,)))
                if name not in names and existing.get((name.lower(),), (False,))[0]:
                    there = await device_tree(client, join(destination_folder, name), (name,))
                    for source, relative, size in there.files:
                        existing[lower_key(relative)] = (False, size, there.modified.get(relative))
                    for relative in there.folders:
                        existing[lower_key(relative)] = (True, 0, None)
            return tree

        self.on_status(_("Reading folder..."), 0)
        self.run(gather, lambda gathered: self.copy_here(gathered, names, existing, destination_folder))
        return False

    def copy_here(self, tree, names, existing, destination_folder):
        def destination(relative):
            return (names.get(relative[0], relative[0]),) + relative[1:]

        def existing_file(relative):
            is_directory, size, moment = existing.get(lower_key(relative), (True, 0, None))
            return None if is_directory else FileFacts(size, moment, self.entry_bitmap(relative[-1]))

        def incoming(source, relative, size):
            return FileFacts(size, tree.modified.get(relative), self.entry_bitmap(relative[-1]))

        plan = plan_transfer(tree, self.replace_prompt(), destination, existing_file,
                             lambda relative: existing.get(lower_key(relative), (False,))[0], incoming)
        if plan.cancelled or not (plan.jobs or plan.folders):
            return
        jobs = [(source, device_join(destination_folder, *relative), size) for source, relative, size in plan.jobs]
        new_folders = [device_join(destination_folder, *relative) for relative in plan.folders]

        async def make_folders(client):
            for folder in new_folders:
                try:
                    await client.create_directory(folder)
                except RapiError:
                    pass

        async def copy(client, source, destination_path, progress):
            await client.copy_file(source, destination_path)
            progress(0)

        self._transfer(_("Copying..."), jobs, copy, lambda count: self.refresh(), prepare=make_folders, animation=self.paste_animation(COPY))

    def move_here(self, source_folder, entries):
        if source_folder == self.folder:
            return True
        existing = existing_entries(self.entries)
        prompt = self.replace_prompt()
        jobs = []
        replacing = set()
        for entry in entries:
            destination_path = join(self.folder, entry.name)
            current = existing.get((entry.name.lower(),))
            if current is not None:
                if entry.is_directory or current[0]:
                    wx.MessageBox(_("A folder with the name you specified already exists. Specify a different file name."), self.root_label,
                                  wx.OK | wx.ICON_INFORMATION, self)
                    continue
                choice = prompt.ask_file(entry.name, FileFacts(current[1], current[2], self.entry_bitmap(entry.name)),
                                         FileFacts(entry.size, device_moment(entry.last_write_time), self.entry_bitmap(entry.name)))
                if choice == REPLACE_CANCEL:
                    return False
                if choice != REPLACE_OVERWRITE:
                    continue
                replacing.add(destination_path)
            jobs.append((join(source_folder, entry.name), destination_path, entry.size))
        if not jobs:
            return True

        async def move(client, source, destination_path, progress):
            if destination_path in replacing:
                await client.delete_file(destination_path)
            await client.move_file(source, destination_path)
            progress(0)

        self._transfer(_("Moving..."), jobs, move, lambda count: self.refresh(), animation=self.paste_animation(CUT))
        return True

    def create_shortcuts(self, targets):
        folder = self.folder
        taken = {entry.name.lower() for entry in self.entries}
        shortcuts = []
        for target_folder, entry in targets:
            name = shortcut_name(entry.name, taken)
            taken.add(name.lower())
            shortcuts.append((join(folder, name), join(target_folder, entry.name), entry.name))

        async def create(client):
            for shortcut, target, label in shortcuts:
                try:
                    await client.create_shortcut(shortcut, target)
                except RapiError as error:
                    raise RapiError(format_original(_("Unable to create a shortcut to '%1'."), label), error.code) from error

        self.run(create, lambda _: self.refresh(), lambda error: (self.show_error(error), self.refresh()))

    def create_shortcut_selected(self):
        entries = self.selected_entries()
        if entries and not self.in_rom(entries):
            self.create_shortcuts([(self.folder, entry) for entry in entries])

    def paste_shortcut(self):
        if self.clipboard:
            mode, source_folder, entries = self.clipboard
            self.create_shortcuts([(source_folder, entry) for entry in entries])

    def print_selected(self, entries=None):
        entries = [entry for entry in (entries if entries is not None else self.selected_entries()) if not entry.is_directory]
        if not entries:
            return
        folder = Path(tempfile.mkdtemp(prefix="classicsync-print-"))
        convert = self.conversion_enabled()
        rules = self.conversion_rules(DEVICE_TO_DESKTOP)
        jobs = []
        for entry in entries:
            plan = desktop_conversion(entry.name, rules) if convert else None
            jobs.append((join(self.folder, entry.name), folder / (plan[2] if plan else entry.name), entry.size))
        fetched = []

        async def fetch(client, source, destination_path, progress):
            data = await client.read_file_contents(source, progress=progress)
            plan = desktop_conversion(source.rsplit("\\", 1)[-1], rules) if convert else None
            if plan:
                try:
                    data = converter(plan[0], plan[1])(data).data
                except (ConversionError, ValueError):
                    destination_path = destination_path.with_name(source.rsplit("\\", 1)[-1])
            destination_path.write_bytes(data)
            fetched.append(destination_path)

        def report_failure(path):
            if self:
                wx.MessageBox(format_original(_("Cannot print file '%s'. Check to make sure enough Windows system resources are available "
                                                "and that the application is installed correctly."), path.name),
                              _("Print Failure"), wx.OK | wx.ICON_ERROR, self)

        def print_all(paths):
            for path in paths:
                try:
                    print_file(path)
                except OSError:
                    wx.CallAfter(report_failure, path)

        def finished(count):
            if count is not None and fetched:
                threading.Thread(target=print_all, args=(list(fetched),), name="classicsync-print", daemon=True).start()

        self._transfer(_("Copying..."), jobs, fetch, finished)

    def device_disconnected(self):
        self.connected = False
        self.clipboard = None
        self.on_status(_("Disconnected"), 0)
        self.list.DeleteAllItems()
        self.list.Enable(False)
        self.tree.Enable(False)

    def device_connected(self, root_label):
        self.connected = True
        self.root_label = root_label
        self.folder = "\\"
        self.tree.DeleteChildren(self.tree_root)
        self.tree.SetItemText(self.tree_root, root_label)
        self.tree.SetItemHasChildren(self.tree_root, True)
        self.tree.SelectItem(self.tree_root)
        self.list.Enable(True)
        self.tree.Enable(True)
        self.navigate("\\")
        wx.CallAfter(self.tree.Expand, self.tree_root)
