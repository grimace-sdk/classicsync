from pathlib import Path

import wx

from ....backup import VERSION_ACTIVESYNC
from ....i18n import N_, _
from ...common.backup import (
    MISMATCH_DEVICE_TYPE, MISMATCH_LANGUAGE, MISMATCH_NEWER_VERSION, MISMATCH_OEM, MISMATCH_PARTNERSHIP, MISMATCH_PROCESSOR,
    MISMATCH_VERSION, BACKUP_FILE_NAME, BackupSettings,
)
from ...common.backup_dialogs import (
    BUTTONS_OK_CANCEL, FILES_LAYOUT_ACTIVESYNC, OUTCOME_ABORT, OUTCOME_DATA_ONLY, OUTCOME_FULL, BackupFlow, BackupWording, MismatchRule,
    choose_backup_file,
)
from ...common.layout import dialog_size, place
from .artwork import MANAGER

PAGE_WIDTH = 235
PAGE_HEIGHT = 199
BACKUP_ICON = 163
RESTORE_ICON = 164

DEVICE_MISMATCH = N_("Device Mismatch")
DEVICE_MISMATCH_CONTINUE = N_("The backup file you have selected was created from an incompatible device. Should you proceed with "
                              "this restore operation, the following could result:\n\nPrograms will not be restored.\nSome data may "
                              "not be restored.\nSome restored data may be unusable.\nYour device may not work properly.\n\n"
                              "Continue with restore?")

WORDING = BackupWording(
    file_version=VERSION_ACTIVESYNC,
    readable_versions=(VERSION_ACTIVESYNC,),
    animation_module=MANAGER,
    titles_include_device=True,
    confirm_backup_title=N_("%s Confirm Backup"),
    confirm_restore_title=N_("%s Confirm Restore"),
    full_backup_description=N_("Full backup of all data from device to desktop computer."),
    incremental_backup_description=N_("Incremental backup of changed data from device to desktop computer."),
    complete_restore_description=N_("Complete restore of all data from desktop computer to your mobile device."),
    restore_from=N_("&Restore from:"),
    proceed_restore_texts=(
        N_("Restore will remove all current data from your device. Your data will be returned to the state it was when this "
           "backup file was last updated."),
        N_("Note: You cannot cancel restore after it has been started."),
        N_("Proceed with Restore?"),
    ),
    synchronize_now=(N_("Synchronize Now"), N_("To minimize the possibility of database losses or duplicates, Backup strongly "
                                               "recommends that you Synchronize Now before proceeding.\r\n\r\nSynchronize Now "
                                               "(recommended)?")),
    backing_up_status=(N_("Now backing up to '%s'"), N_("\nPlease do not use the device until backup is finished.")),
    restoring_status=(N_("Now restoring from '%s'"), N_("\nPlease do not use the device until restore is finished.")),
    backup_complete=(N_("Backup Complete"), N_("Backup operation completed successfully.")),
    backup_canceled=(N_("Backup Canceled"), N_("Backup operation has been canceled.\r\nYour backup file has been returned to its "
                                               "previous state.")),
    backup_connection_broken=(N_("Backup: Connection Broken"), N_("Connection to device was broken during backup.\r\nThe operation "
                                                                  "was canceled. Your backup file has been returned to its previous "
                                                                  "state.")),
    backup_disk_full=(N_("Backup: Disk Full"), N_("The backup path and filename destination disk is full. The operation was "
                                                  "canceled. Your backup file has been returned to its previous state.")),
    backup_file_locked=(N_("Backup: Storage File Locked"), N_("Cannot access storage file or backup storage file. These files have "
                                                              "been locked by another process. Please unlock the file(s) or choose "
                                                              "another backup path and filename.")),
    backup_unrecoverable=(N_("Backup: Unrecoverable Error"), N_("Backup operation has been canceled. An unrecoverable error has "
                                                                "occurred. Your backup file may now be corrupt.\r\n\r\nPlease complete "
                                                                "a new full backup as soon as possible.")),
    invalid_backup_file=(N_("Backup: Invalid Backup File"), N_("The existing backup file is invalid or corrupt.\r\n\r\nIf you choose to "
                                                               "continue (recommended), backup will overwrite this file, creating a new "
                                                               "full backup file.\r\n\r\nContinue Backup?")),
    backup_files_not_copied=(N_("Backup: File(s) Could Not Be Copied"),
                             N_("Backup could not copy the following file(s). To correct this error, please close any programs on "
                                "your device that may have locked these files, and then click Retry.  "),
                             N_("You may choose to skip these files; backup will retain any previous backup copies in the storage "
                                "file.")),
    restore_files_not_copied=(N_("Restore: File(s) Could Not Be Copied"),
                              N_("Restore could not copy the following file(s) to the device.  To correct this error, close any "
                                 "programs on your device that may have these files locked and then press Retry."),
                              N_(" You may choose to skip these files; however, they will not be correctly restored on your "
                                 "device.")),
    restore_complete=(N_("Restore Complete: Restart device"),
                      N_("Restore complete. You must disconnect and then reset your device for these changes to take effect.\r\n\r\n"
                         "Consult your manufacturer's documentation for instructions on resetting your device.\r\n\r\nNote: When you "
                         "reconnect, ActiveSync may prompt you to combine or discard items in any synchronized databases "
                         "(Appointments, Contacts, or Tasks).")),
    restore_connection_broken=(N_("Restore: Connection Broken"),
                               N_("Connection to device was broken during restore.\r\nThe operation was canceled. Your device may "
                                  "not function correctly until you complete the restore operation successfully. Please reconnect "
                                  "and restart restore.")),
    restore_unrecoverable=(N_("Restore: Unrecoverable Error"),
                           N_("Restore operation has been canceled. An unrecoverable error has occurred.\r\n\r\nYou must complete a "
                              "new Restore operation to ensure your device is correctly working.\r\n\r\nIf the problem persists, "
                              "disconnect and then fully reset the device as instructed in your manufacturer's documentation before "
                              "attempting to restore.")),
    restore_invalid_file=(N_("Restore: Invalid Storage File"), N_("The selected backup file is not valid. Please select\r\nanother "
                                                                  "storage file.")),
    restore_invalid_version=(N_("Restore: Invalid Storage File Version"),
                             N_("The selected backup file was created by an incompatible version of backup. Please select another "
                                "storage file.")),
    mismatch_rules=[
        MismatchRule(MISMATCH_DEVICE_TYPE, N_("Device Mismatch"),
                     N_("The backup file you have selected was created from a mobile device of a different type than the device "
                        "you have connected. Restore cannot continue with this operation.\n\nYou must manually transfer the data "
                        "to the new device (via file transfer and Pocket Outlook synchronization)."), OUTCOME_ABORT),
        MismatchRule(MISMATCH_LANGUAGE, N_("Language Mismatch"),
                     N_("The backup file you have selected was created from a mobile device using an incompatible language than "
                        "the device you have connected. Restore cannot continue with this operation.\n\nYou must manually "
                        "transfer the data to the new device (via file transfer and Pocket Outlook synchronization)."),
                     OUTCOME_ABORT),
        MismatchRule(MISMATCH_PROCESSOR, N_("Device Processor Mismatch"),
                     N_("The backup file you have selected was created from a mobile device using a different Central Processing "
                        "Unit (CPU) than the device you have connected. Cannot restore to mobile device."), OUTCOME_ABORT),
        MismatchRule(MISMATCH_VERSION, DEVICE_MISMATCH, DEVICE_MISMATCH_CONTINUE, OUTCOME_DATA_ONLY),
        MismatchRule(MISMATCH_OEM, DEVICE_MISMATCH, DEVICE_MISMATCH_CONTINUE, OUTCOME_DATA_ONLY),
        MismatchRule(MISMATCH_NEWER_VERSION, N_("Version Mismatch"),
                     N_("The backup file you have selected was created from a mobile device using a different version of Windows "
                        "CE than the device you have connected. Restore will copy only your data files (such as Pocket Excel "
                        "files).\n\nAfter restore is complete, you will need to synchronize Pocket Outlook, reinstall any "
                        "applications that had been installed on the previous mobile device and re-enter your settings."),
                     OUTCOME_DATA_ONLY, BUTTONS_OK_CANCEL),
        MismatchRule(MISMATCH_PARTNERSHIP, N_("Backup Warning: Backup Mismatch"),
                     N_("The backup file was not created from this device. Do you want to continue ?"), OUTCOME_FULL),
    ],
    busy_synchronizing=(N_("Synchronization in Progress:"), N_("Synchronization is in progress. Please try again later.")),
    busy_backing_up=(N_("Backup In Progress"), N_("A backup is in progress. Please try again later.")),
    busy_restoring=(N_("Restore In Progress"), N_("A restore is in progress. Please try again later.")),
    files_layout=FILES_LAYOUT_ACTIVESYNC,
    restore_progress_has_cancel=True,
    cannot_locate=(N_("Backup Cannot Locate Backup File"), N_("Backup was unable to locate your backup file. Click OK to\r\nspecify a "
                                                              "backup file. Click Cancel to cancel the backup.")),
    partnership_selection=(N_("Partnership Selection"), N_("Select a partnership from the list. Click Browse if your backup file is "
                                                           "not stored as part of your partnership.")),
)


def page_icon(page, artwork, number):
    bitmap = artwork.icon_as_bitmap(MANAGER, number, 32,
                                    lambda: wx.ArtProvider.GetBitmap(wx.ART_INFORMATION, wx.ART_MESSAGE_BOX, wx.Size(32, 32)))
    wx.StaticBitmap(page, bitmap=bitmap, pos=page.ConvertDialogToPixels(wx.Point(7, 7)))


def radio_with_description(page, label, top, width, description_height, first=False):
    title, _newline, description = label.replace("\r\n", "\n").partition("\n")
    radio = place(page, wx.RadioButton, 7, top, width, 9, title, style=wx.RB_GROUP if first else 0)
    place(page, wx.StaticText, 19, top + 9, width - 12, description_height, description)
    return radio


class BackupPage(wx.Panel):
    def __init__(self, parent, sheet):
        super().__init__(parent)
        self.sheet = sheet
        settings = sheet.backup_settings
        guest = sheet.frontend.application.partnership is None
        self.SetMinSize(dialog_size(self, PAGE_WIDTH, PAGE_HEIGHT))
        page_icon(self, sheet.frontend.artwork, BACKUP_ICON)
        place(self, wx.StaticText, 44, 7, 184, 36, _("Use Backup to create a file on this computer that contains all the files, "
              "databases, personal information, RAM-based programs and other information currently on your mobile device."))
        self.full = radio_with_description(self, _("F&ull backup\r\nBack up all information."), 49, 180, 9, first=True)
        self.incremental = radio_with_description(self, _("&Incremental backup\r\nBack up only the information that has changed since "
                                                          "the last backup."), 71, 207, 17)
        (self.incremental if settings.incremental else self.full).SetValue(True)
        place(self, wx.StaticText, 7, 107, 217, 9, _("&Back up to this file:"))
        self.path = place(self, wx.TextCtrl, 7, 119, 163, 14, str(settings.path), style=wx.TE_READONLY)
        change = place(self, wx.Button, 173, 119, 55, 14, _("&Change..."))
        place(self, wx.StaticText, 7, 140, 163, 17, _("Click Back Up Now to begin backing up your mobile device."))
        back_up = place(self, wx.Button, 173, 140, 55, 14, _("Back Up &Now"))
        back_up.SetDefault()
        self.automatic = place(self, wx.CheckBox, 7, 170, 187, 9, _("Au&tomatically back up each time the device connects."))
        self.automatic.SetValue(settings.automatic and not guest)
        self.automatic.Enable(not guest)
        change.Bind(wx.EVT_BUTTON, self.on_change)
        back_up.Bind(wx.EVT_BUTTON, lambda event: sheet.back_up_now())

    def on_change(self, event):
        chosen = choose_backup_file(self, WORDING, Path(self.path.GetValue()), True)
        if chosen:
            self.path.SetValue(str(chosen))

    def apply(self, settings):
        settings.incremental = self.incremental.GetValue()
        path = Path(self.path.GetValue())
        settings.file = "" if path == settings.directory / BACKUP_FILE_NAME else str(path)
        if self.automatic.IsEnabled():
            settings.automatic = self.automatic.GetValue()


class RestorePage(wx.Panel):
    def __init__(self, parent, sheet):
        super().__init__(parent)
        self.SetMinSize(dialog_size(self, PAGE_WIDTH, PAGE_HEIGHT))
        page_icon(self, sheet.frontend.artwork, RESTORE_ICON)
        place(self, wx.StaticText, 45, 7, 183, 29, _("Use Restore to remove all current information from your mobile device and "
              "replace it with the contents stored in the backup file."))
        place(self, wx.StaticText, 7, 41, 222, 51, _("To restore successfully, quit all programs on your device before starting the "
              "restore process. Also, do not use your device until the restore process is complete.\r\n\r\nNote: You cannot cancel "
              "the restore process once it has started.").replace("\r\n", "\n"))
        place(self, wx.StaticText, 7, 98, 151, 16, _("Click Restore Now to begin restoring your mobile device."))
        restore = place(self, wx.Button, 169, 98, 60, 14, _("Restore &Now"))
        restore.SetDefault()
        restore.Bind(wx.EVT_BUTTON, lambda event: sheet.restore_now())


class BackupRestoreSheet(wx.Dialog):
    def __init__(self, parent, frontend):
        super().__init__(parent, title=_("Backup/Restore"))
        self.frontend = frontend
        self.backup_settings = BackupSettings.load(frontend.application.partnership)
        self.notebook = wx.Notebook(self)
        self.backup_page = BackupPage(self.notebook, self)
        self.notebook.AddPage(self.backup_page, _("Backup"))
        self.notebook.AddPage(RestorePage(self.notebook, self), _("Restore"))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 6)
        sizer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALIGN_RIGHT | wx.ALL, 6)
        self.SetSizerAndFit(sizer)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.CentreOnParent()

    def save(self):
        self.backup_page.apply(self.backup_settings)
        self.backup_settings.save()

    def back_up_now(self):
        self.save()
        BackupFlow(self.frontend, self, WORDING).back_up_now(full=not self.backup_settings.incremental)

    def restore_now(self):
        BackupFlow(self.frontend, self, WORDING).restore_now()

    def on_ok(self, event):
        self.save()
        self.EndModal(wx.ID_OK)


def show_backup_restore(parent, frontend):
    with BackupRestoreSheet(parent, frontend) as sheet:
        sheet.ShowModal()


def run_automatic_backup(frontend, parent):
    settings = BackupSettings.load(frontend.application.partnership)
    BackupFlow(frontend, parent, WORDING).start_backup(settings.path, False, automatic=True)
