from dataclasses import dataclass
from pathlib import Path

import wx

from ...i18n import N_, _, format_original, plain_newlines
from ..service import STATE_CONNECTED
from .animation import AnimationPlayer, load_clip
from .backup import (
    FAILURE_CANCELLED, FAILURE_CONNECTION, FAILURE_DISK_FULL, FAILURE_LOCKED, MISMATCH_NEWER_VERSION, OPERATION_RESTORE,
    BackupSettings,
    failure_kind, partnerships_with_backups, read_backup_information,
)
from .layout import dialog_rect, dialog_size, place

OUTCOME_ABORT = "abort"
OUTCOME_DATA_ONLY = "data only"
OUTCOME_FULL = "full"

BUTTONS_OK = "ok"
BUTTONS_OK_CANCEL = "ok cancel"
BUTTONS_YES_NO = "yes no"

FILES_LAYOUT_ACTIVESYNC = "activesync"
FILES_LAYOUT_EXPLORER = "explorer"

ANIMATION_RESTORE = 147
ANIMATION_BACKUP = 148
PROGRESS_STEPS = 1000

CANCEL_BACKUP_TEXT = N_("Canceling backup will return your backup file to its previous state without any updates from this session.")
CANCEL_BACKUP_QUESTION = N_("Cancel backup?")
COPYING_PHASES = ("files", "databases", "registry")


@dataclass
class MismatchRule:
    kind: str
    title: str
    text: str
    outcome: str
    buttons: str = BUTTONS_YES_NO


@dataclass
class BackupWording:
    file_version: int
    readable_versions: tuple
    animation_module: str
    confirm_backup_title: str
    confirm_restore_title: str
    full_backup_description: str
    incremental_backup_description: str
    complete_restore_description: str
    restore_from: str
    proceed_restore_texts: tuple
    synchronize_now: tuple
    backing_up_status: tuple
    restoring_status: tuple
    backup_complete: tuple
    backup_canceled: tuple
    backup_connection_broken: tuple
    backup_disk_full: tuple
    backup_file_locked: tuple
    backup_unrecoverable: tuple
    invalid_backup_file: tuple
    backup_files_not_copied: tuple
    restore_files_not_copied: tuple
    restore_complete: tuple
    restore_connection_broken: tuple
    restore_unrecoverable: tuple
    restore_invalid_file: tuple
    restore_invalid_version: tuple
    mismatch_rules: list
    busy_synchronizing: tuple
    busy_backing_up: tuple
    busy_restoring: tuple
    files_layout: str = FILES_LAYOUT_EXPLORER
    restore_progress_has_cancel: bool = False
    cannot_locate: tuple = None
    partnership_selection: tuple = None
    titles_include_device: bool = False
    back_up_to: str = N_("Back up to")
    proceed_backup: str = N_("Proceed with Backup?")
    select_backup_set: str = N_("Select Backup Set")
    storage_filter: str = N_("Storage (*.STG)|*.STG|All Files (*.*)|*.*|")
    backup_in_progress: str = N_("Backup In Progress")
    automatic_backup_in_progress: str = N_("Automatic Backup In Progress")
    restore_in_progress: str = N_("Restore In Progress")
    copying: str = N_("Copying:  %s")
    removing: str = N_("Removing:  %s")


def warning_bitmap():
    return wx.ArtProvider.GetBitmap(wx.ART_WARNING, wx.ART_MESSAGE_BOX, wx.Size(32, 32))


def message_bitmap(kind):
    art = {wx.ICON_ERROR: wx.ART_ERROR, wx.ICON_QUESTION: wx.ART_QUESTION, wx.ICON_INFORMATION: wx.ART_INFORMATION}
    return wx.ArtProvider.GetBitmap(art.get(kind, wx.ART_WARNING), wx.ART_MESSAGE_BOX, wx.Size(32, 32))


def storage_wildcard(wording):
    return _(wording.storage_filter).rstrip("|")


class MessageDialog(wx.Dialog):
    def __init__(self, parent, title, text, buttons=BUTTONS_OK, icon=wx.ICON_WARNING, default=wx.ID_OK):
        super().__init__(parent, title=title)
        self.answer = wx.ID_CANCEL
        body = wx.BoxSizer(wx.HORIZONTAL)
        body.Add(wx.StaticBitmap(self, bitmap=message_bitmap(icon)), 0, wx.ALL, 12)
        message = wx.StaticText(self, label=plain_newlines(text))
        message.Wrap(dialog_size(self, 230, 0).width)
        body.Add(message, 1, wx.TOP | wx.RIGHT | wx.BOTTOM, 12)
        row = wx.BoxSizer(wx.HORIZONTAL)
        labels = {BUTTONS_OK: [(wx.ID_OK, _("OK"))], BUTTONS_OK_CANCEL: [(wx.ID_OK, _("OK")), (wx.ID_CANCEL, _("Cancel"))],
                  BUTTONS_YES_NO: [(wx.ID_YES, _("&Yes")), (wx.ID_NO, _("&No"))]}[buttons]
        for identifier, label in labels:
            button = wx.Button(self, identifier, label, size=dialog_size(self, 50, 14))
            button.Bind(wx.EVT_BUTTON, self.on_button)
            row.Add(button, 0, wx.LEFT | wx.RIGHT, 3)
            if identifier == default or len(labels) == 1:
                button.SetDefault()
                button.SetFocus()
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(body, 1, wx.EXPAND)
        sizer.Add(row, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)
        self.SetSizerAndFit(sizer)
        self.SetEscapeId({BUTTONS_YES_NO: wx.ID_NO, BUTTONS_OK_CANCEL: wx.ID_CANCEL}.get(buttons, wx.ID_OK))
        if parent:
            self.CentreOnParent()
        else:
            self.CentreOnScreen()

    def on_button(self, event):
        self.answer = event.GetId()
        self.EndModal(self.answer)


def show_message(parent, pair, buttons=BUTTONS_OK, icon=wx.ICON_WARNING, default=wx.ID_OK, detail="", title_value=None):
    title, text = pair
    title = format_original(_(title), title_value) if title_value is not None else _(title)
    text = _(text) + (f"\n\n{detail}" if detail else "")
    with MessageDialog(parent, title, text, buttons, icon, default) as dialog:
        return dialog.ShowModal()


class BackupProgressDialog(wx.Dialog):
    def __init__(self, parent, artwork, module, animation, title, status, show_cancel=True, cancel_enabled=True):
        super().__init__(parent, title=title, style=wx.CAPTION)
        self.cancel_handler = None
        self.SetClientSize(dialog_size(self, 210, 138 if show_cancel else 119))
        position, size = dialog_rect(self, 10, 4, 190, 49)
        self.animation = AnimationPlayer(self, load_clip(artwork, module, animation), position, size)
        for index, line in enumerate(status.split("\n")[:2]):
            place(self, wx.StaticText, 10, 53 + index * 8, 190, 8, line, style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_MIDDLE)
        self.gauge = place(self, wx.Gauge, 10, 75, 190, 12, PROGRESS_STEPS, style=wx.GA_SMOOTH)
        place(self, wx.StaticLine, 7, 95, 196, 1)
        self.detail = place(self, wx.StaticText, 10, 103, 190, 8, "", style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_MIDDLE)
        self.cancel = None
        if show_cancel:
            self.cancel = place(self, wx.Button, 155, 117, 45, 15, _("Cancel"), id=wx.ID_CANCEL)
            self.cancel.SetDefault()
            self.cancel.Enable(cancel_enabled)
            self.cancel.Bind(wx.EVT_BUTTON, self.on_cancel)
        self.disabler = None
        if parent:
            self.CentreOnParent()
        else:
            self.CentreOnScreen()

    def start(self):
        self.Show()
        self.disabler = wx.WindowDisabler(self)
        self.animation.play()

    def update(self, detail, fraction):
        if not self:
            return
        self.gauge.SetValue(max(0, min(PROGRESS_STEPS, int(fraction * PROGRESS_STEPS))))
        if detail != self.detail.GetLabel():
            self.detail.SetLabel(detail)

    def on_cancel(self, event):
        if self.cancel_handler:
            self.cancel_handler()

    def disable_cancel(self):
        if self.cancel:
            self.cancel.Enable(False)

    def finish(self):
        if not self:
            return
        self.animation.stop()
        self.disabler = None
        self.Destroy()


class ConfirmDialog(wx.Dialog):
    def __init__(self, parent, title, description, group, path, proceed, wording, save):
        super().__init__(parent, title=title)
        self.wording = wording
        self.save = save
        self.SetClientSize(dialog_size(self, 200, 128))
        place(self, wx.StaticText, 7, 6, 186, 21, description)
        place(self, wx.StaticBox, 7, 34, 186, 53, group)
        self.path = place(self, wx.TextCtrl, 20, 47, 160, 14, str(path), style=wx.TE_READONLY)
        browse = place(self, wx.Button, 140, 66, 40, 14, _("&Browse..."))
        browse.Bind(wx.EVT_BUTTON, self.on_browse)
        place(self, wx.StaticText, 7, 93, 80, 9, proceed)
        place(self, wx.Button, 87, 105, 50, 14, _("OK"), id=wx.ID_OK).SetDefault()
        place(self, wx.Button, 143, 105, 50, 14, _("Cancel"), id=wx.ID_CANCEL)
        self.CentreOnParent()

    def on_browse(self, event):
        chosen = choose_backup_file(self, self.wording, Path(self.path.GetValue()), self.save)
        if chosen:
            self.path.SetValue(str(chosen))

    def chosen_path(self):
        return Path(self.path.GetValue())


def choose_backup_file(parent, wording, current, save):
    style = wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT if save else wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
    directory = str(current.parent) if current and current.parent.exists() else ""
    name = current.name if current else ""
    with wx.FileDialog(parent, _(wording.select_backup_set), directory, name, storage_wildcard(wording), style) as dialog:
        if dialog.ShowModal() != wx.ID_OK:
            return None
        chosen = Path(dialog.GetPath())
    if save and not chosen.suffix:
        chosen = chosen.with_suffix(".stg")
    return chosen


class ConfirmCancelDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Confirm Backup Cancel"))
        self.SetClientSize(dialog_size(self, 200, 78))
        wx.StaticBitmap(self, bitmap=warning_bitmap(), pos=self.ConvertDialogToPixels(wx.Point(7, 7)))
        place(self, wx.StaticText, 43, 7, 150, 27, _(CANCEL_BACKUP_TEXT))
        place(self, wx.StaticText, 43, 36, 75, 9, _(CANCEL_BACKUP_QUESTION))
        place(self, wx.Button, 47, 57, 50, 14, _("&Resume"), id=wx.ID_OK).SetDefault()
        place(self, wx.Button, 103, 57, 50, 14, _("Cancel"), id=wx.ID_CANCEL)
        self.SetEscapeId(wx.ID_OK)
        self.CentreOnParent()


class ProceedRestoreDialog(wx.Dialog):
    def __init__(self, parent, texts):
        super().__init__(parent, title=_("Proceed with Restore?"))
        warning, note, question = texts
        self.SetClientSize(dialog_size(self, 200, 100))
        wx.StaticBitmap(self, bitmap=warning_bitmap(), pos=self.ConvertDialogToPixels(wx.Point(7, 7)))
        place(self, wx.StaticText, 43, 7, 150, 24, _(warning))
        place(self, wx.StaticText, 43, 37, 150, 16, _(note))
        place(self, wx.StaticText, 43, 60, 150, 8, _(question))
        cancel = place(self, wx.Button, 46, 79, 50, 14, _("Cancel"), id=wx.ID_CANCEL)
        place(self, wx.Button, 104, 79, 50, 14, _("&Restore"), id=wx.ID_OK)
        cancel.SetDefault()
        cancel.SetFocus()
        self.CentreOnParent()


class FilesNotCopiedDialog(wx.Dialog):
    def __init__(self, parent, title, text, skipped, layout, can_retry):
        super().__init__(parent, title=title)
        self.SetClientSize(dialog_size(self, 305, 157))
        wx.StaticBitmap(self, bitmap=warning_bitmap(), pos=self.ConvertDialogToPixels(wx.Point(7, 7)))
        place(self, wx.StaticText, 38, 7, 260, 40, text)
        files = place(self, wx.ListCtrl, 7, 53, 291, 74, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        files.InsertColumn(0, _("Name"), width=dialog_size(self, 170, 0).width)
        files.InsertColumn(1, _("Problem"), width=dialog_size(self, 110, 0).width)
        for index, (path, reason) in enumerate(skipped):
            files.InsertItem(index, path)
            files.SetItem(index, 1, str(reason))
        if layout == FILES_LAYOUT_ACTIVESYNC:
            retry = place(self, wx.Button, 193, 138, 50, 14, _("&Retry All"), id=wx.ID_RETRY)
            place(self, wx.Button, 251, 138, 50, 14, _("&Skip All"), id=wx.ID_IGNORE)
        else:
            retry = place(self, wx.Button, 68, 136, 50, 14, _("&Retry All"), id=wx.ID_RETRY)
            place(self, wx.Button, 122, 136, 50, 14, _("&Skip All"), id=wx.ID_IGNORE)
            place(self, wx.Button, 176, 136, 50, 14, _("&Help"), id=wx.ID_HELP).Enable(False)
        retry.Enable(can_retry)
        (retry if can_retry else self.FindWindow(wx.ID_IGNORE)).SetDefault()
        self.Bind(wx.EVT_BUTTON, lambda event: self.EndModal(event.GetId()), id=wx.ID_RETRY)
        self.Bind(wx.EVT_BUTTON, lambda event: self.EndModal(event.GetId()), id=wx.ID_IGNORE)
        self.SetEscapeId(wx.ID_IGNORE)
        self.CentreOnParent()


class PartnershipSelectionDialog(wx.Dialog):
    def __init__(self, parent, title, text, partnerships, wording):
        super().__init__(parent, title=title)
        self.wording = wording
        self.choices = partnerships_with_backups(partnerships)
        self.chosen = None
        self.SetClientSize(dialog_size(self, 186, 111))
        place(self, wx.StaticText, 7, 7, 166, 33, text)
        self.list = place(self, wx.ListBox, 7, 38, 105, 38, choices=[partnership.name for partnership, _path in self.choices])
        browse = place(self, wx.Button, 129, 48, 50, 14, _("Browse..."))
        self.ok = place(self, wx.Button, 31, 90, 50, 14, _("OK"), id=wx.ID_OK)
        self.ok.Enable(False)
        place(self, wx.Button, 95, 90, 50, 14, _("Cancel"), id=wx.ID_CANCEL).SetDefault()
        browse.Bind(wx.EVT_BUTTON, self.on_browse)
        self.list.Bind(wx.EVT_LISTBOX, lambda event: self.ok.Enable(self.list.GetSelection() != wx.NOT_FOUND))
        self.list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_ok)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.CentreOnParent()

    def on_browse(self, event):
        chosen = choose_backup_file(self, self.wording, None, False)
        if chosen:
            self.chosen = chosen
            self.EndModal(wx.ID_OK)

    def on_ok(self, event):
        selection = self.list.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        self.chosen = self.choices[selection][1]
        self.EndModal(wx.ID_OK)


def progress_fraction(progress):
    return progress.done / progress.total if progress.total else 0


class BackupFlow:
    def __init__(self, frontend, parent, wording):
        self.frontend = frontend
        self.application = frontend.application
        self.runner = self.application.backup
        self.parent = parent
        self.wording = wording
        self.progress_dialog = None

    def title(self, msgid):
        text = _(msgid)
        if self.wording.titles_include_device:
            return format_original(text, self.application.device_name(self.application.service.announcement))
        return text

    def message(self, pair, buttons=BUTTONS_OK, icon=wx.ICON_WARNING, default=wx.ID_OK, detail=""):
        parent = self.parent if self.parent else None
        return show_message(parent, pair, buttons, icon, default, detail)

    def connected(self):
        return self.application.service.state == STATE_CONNECTED

    def refuse_when_busy(self):
        if self.application.sync.running:
            self.message(self.wording.busy_synchronizing, icon=wx.ICON_INFORMATION)
            return True
        if self.runner.running:
            busy = self.wording.busy_restoring if self.runner.operation == OPERATION_RESTORE else self.wording.busy_backing_up
            self.message(busy, icon=wx.ICON_INFORMATION)
            return True
        return False

    def settings(self):
        return BackupSettings.load(self.application.partnership)

    def back_up_now(self, full=None, path=None, recommend_sync=True):
        if not self.connected() or self.refuse_when_busy():
            return
        settings = self.settings()
        full = not settings.incremental if full is None else full
        path = Path(path) if path else settings.path
        if recommend_sync and self.frontend.can_synchronize():
            answer = self.message(self.wording.synchronize_now, BUTTONS_YES_NO, wx.ICON_QUESTION, wx.ID_YES)
            if answer == wx.ID_YES and self.application.sync.start():
                self.runner.after_sync(lambda: self.confirm_backup(full, path))
                return
        self.confirm_backup(full, path)

    def confirm_backup(self, full, path):
        if not self.connected():
            return
        description = self.wording.full_backup_description if full else self.wording.incremental_backup_description
        with ConfirmDialog(self.parent, self.title(self.wording.confirm_backup_title), _(description), _(self.wording.back_up_to),
                           path, _(self.wording.proceed_backup), self.wording, True) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            chosen = dialog.chosen_path()
        settings = self.settings()
        if chosen != settings.path:
            settings.file = str(chosen)
            settings.save()
        if not full and chosen.exists() and read_backup_information(chosen) is None:
            if self.message(self.wording.invalid_backup_file, BUTTONS_YES_NO, wx.ICON_WARNING, wx.ID_YES) != wx.ID_YES:
                return
            full = True
        self.start_backup(chosen, full)

    def start_backup(self, path, full, automatic=False):
        if self.runner.busy:
            return False
        first, second = self.wording.backing_up_status
        status = format_original(_(first), str(path)) + plain_newlines(_(second))
        title = _(self.wording.automatic_backup_in_progress if automatic else self.wording.backup_in_progress)
        self.progress_dialog = BackupProgressDialog(self.parent, self.frontend.artwork, self.wording.animation_module,
                                                    ANIMATION_BACKUP, title, status)
        self.progress_dialog.cancel_handler = self.confirm_cancel
        started = self.runner.back_up(path, full, self.wording.file_version, self.show_progress,
                                      lambda result, error: self.backup_finished(path, automatic, result, error))
        if not started:
            self.progress_dialog.finish()
            self.progress_dialog = None
            return False
        self.progress_dialog.start()
        self.frontend.backup_state_changed()
        return True

    def confirm_cancel(self):
        dialog = self.progress_dialog
        if not dialog or not self.runner.running:
            return
        with ConfirmCancelDialog(dialog) as confirm:
            if confirm.ShowModal() == wx.ID_CANCEL and self.runner.running:
                self.runner.cancel()
                dialog.disable_cancel()

    def show_progress(self, progress):
        dialog = self.progress_dialog
        if not dialog:
            return
        if progress.phase == "removing":
            detail = format_original(_(self.wording.removing), progress.item)
        elif progress.phase in COPYING_PHASES and progress.item:
            detail = format_original(_(self.wording.copying), progress.item)
        else:
            detail = dialog.detail.GetLabel()
        dialog.update(detail, progress_fraction(progress))

    def close_progress(self):
        if self.progress_dialog:
            self.progress_dialog.finish()
            self.progress_dialog = None

    def backup_finished(self, path, automatic, result, error):
        self.close_progress()
        self.frontend.backup_state_changed()
        if error:
            kind = failure_kind(error)
            messages = {FAILURE_CANCELLED: self.wording.backup_canceled, FAILURE_CONNECTION: self.wording.backup_connection_broken,
                        FAILURE_DISK_FULL: self.wording.backup_disk_full, FAILURE_LOCKED: self.wording.backup_file_locked}
            detail = "" if kind in messages else str(error)
            icon = wx.ICON_INFORMATION if kind == FAILURE_CANCELLED else wx.ICON_ERROR
            self.message(messages.get(kind, self.wording.backup_unrecoverable), icon=icon, detail=detail)
            return
        if result.skipped:
            title, *parts = self.wording.backup_files_not_copied
            text = "".join(_(part) for part in parts)
            with FilesNotCopiedDialog(self.parent, _(title), text, result.skipped, self.wording.files_layout, True) as dialog:
                if dialog.ShowModal() == wx.ID_RETRY and self.connected():
                    self.start_backup(path, False, automatic)
                    return
        if not automatic:
            self.message(self.wording.backup_complete, icon=wx.ICON_INFORMATION)

    def restore_now(self, path=None, choose=False):
        if not self.connected() or self.refuse_when_busy():
            return
        if path is None:
            path = self.locate_backup(choose)
            if path is None:
                return
        self.confirm_restore(Path(path))

    def locate_backup(self, choose):
        settings_path = self.settings().path
        if not choose and settings_path.exists():
            return settings_path
        if self.wording.partnership_selection is None:
            return choose_backup_file(self.parent, self.wording, settings_path if settings_path.exists() else None, False)
        if not choose and self.wording.cannot_locate:
            if self.message(self.wording.cannot_locate, BUTTONS_OK_CANCEL) != wx.ID_OK:
                return None
        title, text = self.wording.partnership_selection
        with PartnershipSelectionDialog(self.parent, _(title), _(text), self.application.partnerships(), self.wording) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return None
            return dialog.chosen

    def confirm_restore(self, path):
        with ConfirmDialog(self.parent, self.title(self.wording.confirm_restore_title), _(self.wording.complete_restore_description),
                           _(self.wording.restore_from), path, _(self.wording.proceed_restore_texts[2]), self.wording,
                           False) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = dialog.chosen_path()
        information = read_backup_information(path)
        if information is None:
            self.message(self.wording.restore_invalid_file, icon=wx.ICON_ERROR)
            return
        if information.version not in self.wording.readable_versions:
            self.message(self.wording.restore_invalid_version, icon=wx.ICON_ERROR)
            return
        with ProceedRestoreDialog(self.parent, self.wording.proceed_restore_texts) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
        if not self.runner.check_restore(path, lambda check, error: self.restore_checked(path, check, error)):
            self.refuse_when_busy()

    def restore_checked(self, path, check, error):
        if error:
            kind = failure_kind(error)
            pair = self.wording.restore_connection_broken if kind == FAILURE_CONNECTION else self.wording.restore_invalid_file
            self.message(pair, icon=wx.ICON_ERROR, detail="" if kind == FAILURE_CONNECTION else str(error))
            return
        data_only = None
        allow_mismatch = False
        for rule in self.wording.mismatch_rules:
            if not check.has(rule.kind):
                continue
            if rule.outcome == OUTCOME_ABORT:
                self.message((rule.title, rule.text), icon=wx.ICON_ERROR)
                return
            default = wx.ID_NO if rule.buttons == BUTTONS_YES_NO else wx.ID_OK
            answer = self.message((rule.title, rule.text), rule.buttons, wx.ICON_WARNING, default)
            if answer not in (wx.ID_OK, wx.ID_YES):
                return
            if rule.kind != MISMATCH_NEWER_VERSION:
                allow_mismatch = True
            if rule.outcome == OUTCOME_DATA_ONLY:
                data_only = True
            elif data_only is None:
                data_only = False
        if any(not any(rule.kind == kind for rule in self.wording.mismatch_rules) for kind in check.mismatches):
            allow_mismatch = True
            data_only = True
        self.start_restore(path, data_only, allow_mismatch)

    def start_restore(self, path, data_only, allow_mismatch):
        first, second = self.wording.restoring_status
        status = format_original(_(first), str(path)) + plain_newlines(_(second))
        has_cancel = self.wording.restore_progress_has_cancel
        self.progress_dialog = BackupProgressDialog(self.parent, self.frontend.artwork, self.wording.animation_module,
                                                    ANIMATION_RESTORE, _(self.wording.restore_in_progress), status,
                                                    show_cancel=has_cancel, cancel_enabled=False)
        started = self.runner.restore(path, data_only, allow_mismatch, self.show_progress,
                                      lambda result, error: self.restore_finished(result, error))
        if not started:
            self.close_progress()
            self.refuse_when_busy()
            return
        self.progress_dialog.start()
        self.frontend.backup_state_changed()

    def restore_finished(self, result, error):
        self.close_progress()
        self.frontend.backup_state_changed()
        if error:
            if failure_kind(error) == FAILURE_CONNECTION:
                self.message(self.wording.restore_connection_broken, icon=wx.ICON_ERROR)
            else:
                self.message(self.wording.restore_unrecoverable, icon=wx.ICON_ERROR, detail=str(error))
            return
        if result.skipped:
            title, *parts = self.wording.restore_files_not_copied
            text = "".join(_(part) for part in parts)
            with FilesNotCopiedDialog(self.parent, _(title), text, result.skipped, self.wording.files_layout, False) as dialog:
                dialog.ShowModal()
        self.message(self.wording.restore_complete, icon=wx.ICON_INFORMATION)
