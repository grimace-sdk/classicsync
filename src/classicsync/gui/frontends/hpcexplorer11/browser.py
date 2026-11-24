import os
from pathlib import Path

import wx

from ....i18n import N_, _, format_original
from ....rapi.structures import FILE_ATTRIBUTE_INROM
from ...common.animation import AnimationPlayer, load_clip
from ...common.device_browser import DeviceBrowser, join
from ...common.file_icons import FileIcons
from ...common.layout import dialog_rect, dialog_size, place
from .artwork import ANIMATION_DEVICE_COPY, ANIMATION_DEVICE_MOVE, ANIMATION_FROM_DEVICE, ANIMATION_TO_DEVICE, EXPLORER
from .commands import (
    ARRANGE_COMMANDS, ID_ARRANGE_BY_DATE, ID_ARRANGE_BY_NAME, ID_ARRANGE_BY_SIZE, ID_ARRANGE_BY_TYPE, ID_AUTO_ARRANGE,
    ID_COPY, ID_CREATE_SHORTCUT, ID_CUT, ID_DELETE, ID_DETAILS, ID_LARGE_ICONS, ID_LIST, ID_NEW_FOLDER, ID_OPEN, ID_PASTE,
    ID_PASTE_SHORTCUT, ID_PRINT, ID_PROPERTIES, ID_RENAME, ID_SMALL_ICONS, UNAVAILABLE, VIEW_COMMANDS,
)
from .properties import EntryPropertiesSheet

HIDDEN_EXTENSIONS = {".dll", ".cpl", ".drv"}
HIDDEN_TYPE_LABELS = [N_(".DLL     (Application extension)"), N_(".CPL     (Control Panel extension)"), N_(".DRV     (Device driver)")]

CUT = "cut"
COPY = "copy"


def display_name(root_label, folder):
    return root_label if folder in ("", "\\") else folder.rstrip("\\").rsplit("\\", 1)[-1]


def free_space_text(free_bytes):
    tenths = free_bytes * 10 // (1024 * 1024)
    return format_original(_(" (Free space: %d.%dMB)"), tenths // 10, tenths % 10)


def copy_name(name, existing):
    candidate = format_original(_("Copy of %s"), name)
    counter = 2
    while candidate.lower() in existing:
        candidate = format_original(_("Copy (%d) of %s"), counter, name)
        counter += 1
    return candidate


def append_items(menu, items):
    for item in items:
        if item is None:
            menu.AppendSeparator()
            continue
        identifier, label = item
        menu.Append(identifier, label).Enable(identifier not in UNAVAILABLE)


class TransferProgressDialog(wx.Dialog):
    def __init__(self, parent, artwork, animation_number, caption):
        super().__init__(parent, title=caption, style=wx.CAPTION)
        self.cancelled = False
        self.SetClientSize(dialog_size(self, 210, 138))
        position, size = dialog_rect(self, 10, 4, 190, 49)
        self.animation = AnimationPlayer(self, load_clip(artwork, EXPLORER, animation_number), position, size)
        self.action = place(self, wx.StaticText, 10, 53, 190, 10, "", style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
        self.gauge = place(self, wx.Gauge, 10, 75, 190, 12, 1000, style=wx.GA_SMOOTH)
        place(self, wx.StaticLine, 7, 95, 196, 1)
        self.detail = place(self, wx.StaticText, 10, 103, 190, 8, "", style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_MIDDLE)
        cancel = place(self, wx.Button, 155, 117, 45, 15, _("Cancel"), id=wx.ID_CANCEL)
        cancel.SetDefault()
        cancel.Bind(wx.EVT_BUTTON, self._on_cancel)
        self.CentreOnParent()
        self.disabler = None

    def start(self):
        self.Show()
        self.disabler = wx.WindowDisabler(self)
        self.animation.play()

    def update(self, fraction, action, detail):
        self.gauge.SetValue(min(1000, int(fraction * 1000)))
        if self.action.GetLabel() != action:
            self.action.SetLabel(action)
            self.detail.SetLabel(detail)

    def finish(self):
        self.animation.stop()
        self.disabler = None
        self.Destroy()

    def _on_cancel(self, event):
        self.cancelled = True
        self.FindWindow(wx.ID_CANCEL).Enable(False)


class HpcDeviceBrowser(DeviceBrowser):
    def __init__(self, parent, window, root_label):
        self.window = window
        self.artwork = window.artwork
        self.view_settings = window.view_settings
        self.store = None
        super().__init__(parent, window.application, root_label, on_status=window.set_status, on_folder=window.folder_changed,
                         file_icons=FileIcons(self.artwork))
        self.context_menu_factory = self.explorer_context_menu
        self.tree_width = self.view_settings.sash_position
        self.SetSashPosition(self.tree_width)
        self.set_view(self.view_settings.view)
        self.set_tree_visible(self.view_settings.show_folders)

    def _on_item_activated(self, event):
        entry = self.entries_view[event.GetIndex()]
        if entry.is_directory:
            self.navigate(join(self.folder, entry.name))
        else:
            self.show_properties()

    def open_selected(self):
        entries = self.selected_entries()
        if len(entries) == 1 and entries[0].is_directory:
            self.navigate(join(self.folder, entries[0].name))
        elif len(entries) == 1:
            self.show_properties()

    def visible_entries(self, entries):
        if not self.view_settings.hide_system_files:
            return list(entries)
        return [entry for entry in entries
                if entry.is_directory or os.path.splitext(entry.name)[1].lower() not in HIDDEN_EXTENSIONS]

    def _show_folder(self, result):
        if not self:
            return
        entries, store = result
        self.entries = self.visible_entries(entries)
        self.store = store
        self._fill_list()
        self.show_object_count()

    def show_object_count(self):
        text = format_original(_("%d object(s)"), len(self.entries))
        if self.store:
            text += free_space_text(self.store.free_size)
        self.on_status(text, 0)

    def _on_selection_changed(self, event):
        count = len(self._selected_indices())
        if count:
            self.on_status(format_original(_("%d object(s) selected"), count), 0)
        else:
            self.show_object_count()
        event.Skip()

    def show_properties(self):
        entries = self.selected_entries()
        if len(entries) != 1:
            return
        with EntryPropertiesSheet(self.GetTopLevelParent(), entries[0], self.location_label(), self.artwork,
                                  self.set_attributes) as sheet:
            sheet.ShowModal()

    def set_attributes(self, entry, attributes):
        path = join(self.folder, entry.name)

        async def update(client):
            await client.set_file_attributes(path, attributes)

        self.run(update, lambda _: self.refresh(), lambda error: (self.show_error(error), self.refresh()))

    def explorer_context_menu(self, entries):
        menu = wx.Menu()
        if not entries:
            view_menu = wx.Menu()
            for identifier, label in ((ID_LARGE_ICONS, _("&Large Icons")), (ID_SMALL_ICONS, _("&Small Icons")),
                                      (ID_LIST, _("&List")), (ID_DETAILS, _("&Details"))):
                view_menu.AppendRadioItem(identifier, label).Check(VIEW_COMMANDS[identifier] == self.view)
            menu.AppendSubMenu(view_menu, _("&View"))
            menu.AppendSeparator()
            arrange_menu = wx.Menu()
            append_items(arrange_menu, [(ID_ARRANGE_BY_NAME, _("by &Name")), (ID_ARRANGE_BY_TYPE, _("by &Type")),
                                        (ID_ARRANGE_BY_SIZE, _("by Si&ze")), (ID_ARRANGE_BY_DATE, _("by &Date")), None,
                                        (ID_AUTO_ARRANGE, _("&Auto Arrange"))])
            menu.AppendSubMenu(arrange_menu, _("&Arrange Icons"))
            menu.AppendSeparator()
            append_items(menu, [(ID_PASTE, _("&Paste")), (ID_PASTE_SHORTCUT, _("Paste &Shortcut")), None,
                                (ID_NEW_FOLDER, _("Ne&w Folder")), None, (ID_PROPERTIES, _("P&roperties"))])
            menu.Enable(ID_PASTE, self.window.can_paste())
            menu.Enable(ID_PROPERTIES, False)
            return menu
        if len(entries) == 1 and entries[0].is_directory:
            first = [(ID_OPEN, _("&Open"))]
        else:
            first = [(ID_PRINT, _("&Print"))]
        append_items(menu, first + [None, (ID_CUT, _("Cu&t")), (ID_COPY, _("&Copy")), None,
                                    (ID_CREATE_SHORTCUT, _("Create &Shortcut")), (ID_DELETE, _("&Delete")), (ID_RENAME, _("Rena&me")),
                                    None, (ID_PROPERTIES, _("P&roperties"))])
        in_rom = any(entry.attributes & FILE_ATTRIBUTE_INROM for entry in entries)
        menu.Enable(ID_CUT, not in_rom)
        menu.Enable(ID_DELETE, not in_rom)
        menu.Enable(ID_RENAME, len(entries) == 1 and not in_rom)
        menu.Enable(ID_PROPERTIES, len(entries) == 1)
        return menu

    def arrange(self, identifier):
        self.sort_by(ARRANGE_COMMANDS[identifier])

    def selection_in_rom(self):
        return any(entry.attributes & FILE_ATTRIBUTE_INROM for entry in self.selected_entries())

    def paste_from_device(self, clipboard):
        mode, source_folder, entries = clipboard
        existing = {entry.name.lower() for entry in self.entries}
        jobs = []
        for entry in entries:
            if mode == COPY and entry.is_directory:
                continue
            name = entry.name
            if source_folder == self.folder:
                if mode == CUT:
                    continue
                name = copy_name(name, existing)
                existing.add(name.lower())
            elif name.lower() in existing:
                answer = wx.MessageBox(format_original(_("File '%s' exists already. Do you want to replace it?"), name),
                                       _("Confirm File Replace"), wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION, self)
                if answer == wx.CANCEL:
                    return False
                if answer == wx.NO:
                    continue
            jobs.append((join(source_folder, entry.name), join(self.folder, name), entry.size))
        if not jobs:
            return mode == CUT

        async def transfer(client, source, destination, progress):
            if mode == CUT:
                await client.move_file(source, destination)
            else:
                await client.copy_file(source, destination)
            progress(0)

        animation = ANIMATION_DEVICE_MOVE if mode == CUT else ANIMATION_DEVICE_COPY
        caption = _("Moving...") if mode == CUT else _("Copying...")
        self._transfer(caption, jobs, transfer, lambda _: self.refresh(), animation=animation)
        return mode == CUT

    def _transfer(self, title, jobs, operation, on_finished, animation=None):
        total = sum(size for source, destination, size in jobs) or 1
        to_desktop = bool(jobs) and isinstance(jobs[0][1], Path)
        moving = animation == ANIMATION_DEVICE_MOVE
        if animation is None:
            animation = ANIMATION_FROM_DEVICE if to_desktop else ANIMATION_TO_DEVICE
        caption = _("Moving...") if moving else _("Copying...")
        progress = TransferProgressDialog(self.GetTopLevelParent(), self.artwork, animation, caption)
        progress.start()

        def folder_label(path):
            if isinstance(path, Path):
                return path.parent.name or str(path.parent)
            if "\\" in str(path):
                return display_name(self.root_label, str(path).rsplit("\\", 1)[0])
            return Path(path).parent.name

        def report(name, detail, done_in_file, base):
            def update():
                if progress:
                    action = _("Moving:  {name}").format(name=name) if moving else format_original(_("Copying:  %s"), name)
                    progress.update((base + done_in_file) / total, action, detail)
            wx.CallAfter(update)
            if progress.cancelled:
                raise InterruptedError("cancelled")

        async def run_all(client):
            base = 0
            for source, destination, size in jobs:
                name = os.path.basename(str(source).replace("\\", "/"))
                detail = format_original(_("From '%s' to '%s'"), folder_label(source), folder_label(destination))
                report(name, detail, 0, base)
                await operation(client, source, destination,
                                lambda done, base=base, name=name, detail=detail: report(name, detail, done, base))
                base += size
            return len(jobs)

        def finish(result):
            progress.finish()
            on_finished(result)

        def fail(error):
            progress.finish()
            if not isinstance(error, InterruptedError):
                self.show_error(error)
            on_finished(None)

        self.run(run_all, finish, fail)
