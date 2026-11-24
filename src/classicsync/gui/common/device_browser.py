import os
from datetime import datetime, timezone
from pathlib import Path

import wx

from ...convert import DESKTOP_DEFAULTS, FORMATS, ConversionError, converter, format_for_extension
from ...i18n import N_, _, format_original, ngettext
from ...rapi.client import RapiError
from ...rapi.structures import (
    FILE_ATTRIBUTE_ARCHIVE, FILE_ATTRIBUTE_HIDDEN, FILE_ATTRIBUTE_INROM, FILE_ATTRIBUTE_READONLY, FILE_ATTRIBUTE_SYSTEM,
    datetime_to_filetime, filetime_to_datetime,
)
from .layout import dialog_size, place

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


def format_time(filetime):
    moment = filetime_to_datetime(filetime)
    if not moment:
        return ""
    return moment.replace(tzinfo=timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")


def desktop_conversion(name):
    source = format_for_extension(os.path.splitext(name)[1])
    if source not in DESKTOP_DEFAULTS:
        return None
    target = DESKTOP_DEFAULTS[source]
    return source, target, os.path.splitext(name)[0] + FORMATS[target].extensions[0]


AUTOMATIC_DEVICE_CONVERSIONS = {"docx": "pwd", "rtf": "pwd", "xlsx": "pxl"}
AUTOMATIC_LEGACY_DEVICE_CONVERSIONS = {"bmp": "2bp", "png": "2bp"}


def device_conversion(name, version=2):
    source = format_for_extension(os.path.splitext(name)[1])
    target = AUTOMATIC_DEVICE_CONVERSIONS.get(source)
    if not target and version == 1:
        target = AUTOMATIC_LEGACY_DEVICE_CONVERSIONS.get(source)
    if not target:
        return None
    return source, target, os.path.splitext(name)[0] + FORMATS[target].extensions[0]


def make_image_list(size):
    images = wx.ImageList(size, size)
    art_size = wx.Size(size, size)
    for art in (wx.ART_FOLDER, wx.ART_FOLDER_OPEN, wx.ART_NORMAL_FILE, wx.ART_HARDDISK):
        images.Add(wx.ArtProvider.GetBitmap(art, wx.ART_OTHER, art_size))
    return images


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
    def __init__(self, parent, application, root_label, on_status=None, on_title=None, on_folder=None):
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

        self.small_images = make_image_list(16)
        self.large_images = make_image_list(32)
        self.tree = wx.TreeCtrl(self, style=wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT | wx.TR_SINGLE)
        self.tree.SetImageList(self.small_images)
        self.tree_root = self.tree.AddRoot(root_label, IMAGE_DEVICE)
        self.tree.SetItemData(self.tree_root, "\\")
        self.tree.SetItemHasChildren(self.tree_root, True)

        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_EDIT_LABELS)
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

    def navigate(self, folder):
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

        self.run(read, self._show_folder)

    def refresh(self):
        self.navigate(self.folder)

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
            self.list.InsertItem(index, entry.name, IMAGE_FOLDER if entry.is_directory else IMAGE_FILE)
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
            menu.Append(COMMAND_COPY_TO_COMPUTER, _("&Copy to This Computer..."))
            menu.AppendSeparator()
            in_rom = any(entry.attributes & FILE_ATTRIBUTE_INROM for entry in entries)
            menu.Append(COMMAND_DELETE, _("&Delete")).Enable(not in_rom)
            menu.Append(COMMAND_RENAME, _("Rena&me")).Enable(len(entries) == 1 and not in_rom)
            menu.AppendSeparator()
            menu.Append(COMMAND_PROPERTIES, _("P&roperties")).Enable(len(entries) == 1)
        else:
            menu.Append(COMMAND_COPY_FROM_COMPUTER, _("Copy &Files Here..."))
            menu.Append(COMMAND_NEW_FOLDER, _("Ne&w Folder"))
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

    def add_files_dialog(self):
        with wx.FileDialog(self, _("Copy to Mobile Device"), style=wx.FD_OPEN | wx.FD_MULTIPLE | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.upload(dialog.GetPaths())

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

    def _transfer(self, title, jobs, operation, on_finished):
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

    def conversion_enabled(self):
        return getattr(self.application.settings, "convert_files", True)

    def device_version(self):
        major = self.application.device_major_version(self.application.service.announcement)
        return 1 if major == 1 else 2

    def copy_to_computer(self, entries=None, target=None):
        entries = entries if entries is not None else self.selected_entries()
        files = [entry for entry in entries if not entry.is_directory]
        if not files:
            wx.MessageBox(_("Folders can't be copied to this computer yet; open the folder and select its files."), self.root_label,
                          wx.OK | wx.ICON_INFORMATION, self)
            return
        if target is None:
            with wx.DirDialog(self, _("Copy to which folder on this computer?"), str(Path.home() / "Desktop")) as dialog:
                if dialog.ShowModal() != wx.ID_OK:
                    return
                target = Path(dialog.GetPath())
        convert = self.conversion_enabled()
        jobs = []
        for entry in files:
            plan = desktop_conversion(entry.name) if convert else None
            jobs.append((join(self.folder, entry.name), Path(target) / (plan[2] if plan else entry.name), entry.size))
        warnings = []

        async def download(client, source, destination, progress):
            data = await client.read_file_contents(source, progress=progress)
            plan = desktop_conversion(source.rsplit("\\", 1)[-1]) if convert else None
            if plan:
                try:
                    conversion = converter(plan[0], plan[1])(data)
                    data = conversion.data
                    warnings.extend(conversion.warnings)
                except (ConversionError, ValueError) as error:
                    warnings.append(str(error))
                    destination = destination.with_name(source.rsplit("\\", 1)[-1])
            destination.write_bytes(data)

        def finished(count):
            if count:
                message = ngettext("Copied {count} file to {target}", "Copied {count} files to {target}", count).format(count=count, target=target)
                self.on_status(message + (" (" + "; ".join(warnings[:2]) + ")" if warnings else ""), 0)

        self._transfer(_("Copying..."), jobs, download, finished)

    def upload(self, filenames):
        paths = [Path(name) for name in filenames]
        if any(path.is_dir() for path in paths):
            wx.MessageBox(_("Folders can't be copied to the device yet; only the files will be copied."), self.root_label,
                          wx.OK | wx.ICON_INFORMATION, self)
        existing = {entry.name.lower() for entry in self.entries}
        convert = self.conversion_enabled()
        version = self.device_version()
        jobs = []
        for path in paths:
            if not path.is_file():
                continue
            plan = device_conversion(path.name, version) if convert else None
            device_name = plan[2] if plan else path.name
            if device_name.lower() in existing:
                answer = wx.MessageBox(_("This folder already contains a file named '{name}'.\n\nWould you like to replace the existing file?")
                                       .format(name=device_name), _("Confirm File Replace"), wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION, self)
                if answer == wx.CANCEL:
                    return
                if answer == wx.NO:
                    continue
            jobs.append((str(path), join(self.folder, device_name), path.stat().st_size))
        if not jobs:
            return
        warnings = []

        async def send(client, source, destination, progress):
            data = Path(source).read_bytes()
            plan = device_conversion(Path(source).name, version) if convert else None
            if plan:
                conversion = converter(plan[0], plan[1])(data, version=version)
                data = conversion.data
                warnings.extend(conversion.warnings)
            modified = datetime_to_filetime(datetime.fromtimestamp(Path(source).stat().st_mtime, timezone.utc))
            await client.write_file_contents(destination, data, modified=modified, progress=progress)

        def finished(_count):
            self.refresh()
            if warnings:
                self.on_status(_("Converted with changes: {details}").format(details="; ".join(warnings[:3])), 0)

        self._transfer(_("Copying..."), jobs, send, finished)

    def device_disconnected(self):
        self.connected = False
        self.on_status(_("Disconnected"), 0)
        self.list.DeleteAllItems()
        self.list.Enable(False)
        self.tree.Enable(False)
