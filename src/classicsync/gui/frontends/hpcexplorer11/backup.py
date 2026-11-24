import wx

from ....backup import VERSION_HPC_EXPLORER
from ....i18n import N_, _
from ...common.backup import (
    MISMATCH_DEVICE_TYPE, MISMATCH_LANGUAGE, MISMATCH_OEM, MISMATCH_PARTNERSHIP, MISMATCH_PROCESSOR, MISMATCH_VERSION,
    BackupSettings,
)
from ...common.backup_dialogs import (
    OUTCOME_DATA_ONLY, OUTCOME_FULL, BackupFlow, BackupWording, MismatchRule, choose_backup_file, warning_bitmap,
)
from ...common.backup_pages import ExplorerBackupPage, ExplorerPageText, ExplorerRestorePage
from ...common.layout import dialog_size, place
from .artwork import EXPLORER
from .sheet import PropertySheet

READABLE_VERSIONS = (4, VERSION_HPC_EXPLORER)

DEVICE_MISMATCH = N_("Device Mismatch")
DEVICE_MISMATCH_TEXT = N_("The backup file you have selected was created from an incompatible H/PC. Should you proceed with this "
                          "restore operation, the following could result:\n\nPrograms will not be restored.\nSome data may not be "
                          "restored.\nSome restored data may be unusable.\nYour device may not work properly.\n\nContinue with "
                          "restore?")

WORDING = BackupWording(
    file_version=VERSION_HPC_EXPLORER,
    readable_versions=READABLE_VERSIONS,
    animation_module=EXPLORER,
    confirm_backup_title=N_("Confirm Backup"),
    confirm_restore_title=N_("Confirm Restore"),
    full_backup_description=N_("Full backup of all data from H/PC to desktop computer."),
    incremental_backup_description=N_("Incremental backup of changed data from H/PC to desktop computer."),
    complete_restore_description=N_("Complete restore of all data from desktop computer to H/PC."),
    restore_from=N_("&Restore from:"),
    proceed_restore_texts=(
        N_("Restore will remove all current data from your H/PC. Your data will be returned to the state it was when this backup "
           "file was last updated."),
        N_("Note: you may not cancel restore after it has been started."),
        N_("Proceed with Restore?"),
    ),
    synchronize_now=(N_("Synchronize Now"), N_("To minimize the possibility of database losses or duplicates, Backup strongly "
                                               "recommends that you Synchronize Now before proceeding.\r\n\r\nSynchronize Now "
                                               "(recommended)?")),
    backing_up_status=(N_("Now backing up to '%s'\r\nPlease do not use the H/PC until backup is finished."), ""),
    restoring_status=(N_("Now restoring from '%s'\r\nPlease do not use the H/PC until restore is finished."), ""),
    backup_complete=(N_("Backup Complete"), N_("Backup operation completed successfully.")),
    backup_canceled=(N_("Backup Canceled"), N_("Backup operation has been canceled.\r\nYour backup file has been returned to its "
                                               "previous state.")),
    backup_connection_broken=(N_("Backup: Connection Broken"), N_("Connection to H/PC was broken during backup.\r\nThe operation was "
                                                                  "canceled. Your backup file has been returned to its previous "
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
                                                               "continue (recommended) backup will overwrite this file, creating a new "
                                                               "full backup file.\r\n\r\nContinue Backup?")),
    backup_files_not_copied=(N_("Backup: File(s) Could Not Be Copied"),
                             N_("Backup could not copy the following file(s). To correct this error, please close any programs on "
                                "your H/PC that may have locked these files, and then press Retry.  "),
                             N_("You may choose to Skip these files; backup will retain any previous backup copies in the storage "
                                "file.")),
    restore_files_not_copied=(N_("Restore: File(s) Could Not Be Copied"),
                              N_("Restore could not copy the following file(s) to the H/PC.  To correct this error, close any "
                                 "programs on your H/PC that may have these files locked and then press Retry."),
                              N_(" You may choose to Skip these files, however they will not be correctly restored on your H/PC.")),
    restore_complete=(N_("Restore Complete: Restart H/PC"),
                      N_("Restore complete. You must disconnect and then reset your H/PC for these changes to take effect.\r\n\r\n"
                         "Consult your User's Guide for instructions for resetting your H/PC.\r\n\r\nNote: When you reconnect, "
                         "Synchronization Manager may prompt you to combine or discard items in any synchronized databases "
                         "(Appointments, Contacts, or Tasks).")),
    restore_connection_broken=(N_("Restore: Connection Broken"),
                               N_("Connection to H/PC was broken during restore.\r\nThe operation was canceled. Your H/PC may not "
                                  "function correctly until you complete the restore operation successfully. Please reconnect and "
                                  "restart restore.")),
    restore_unrecoverable=(N_("Restore: Unrecoverable Error"),
                           N_("Restore operation has been canceled. An unrecoverable error has occurred.\r\n\r\nYou must complete a "
                              "new Restore operation to ensure your H/PC is correctly working.\r\n\r\nIf the problem persists, "
                              "disconnect and then full reset the H/PC as instructed in your User's Guide before attempting to "
                              "restore.")),
    restore_invalid_file=(N_("Restore: Invalid Storage File"), N_("The selected backup file is not valid. Please select\r\nanother "
                                                                  "storage file.")),
    restore_invalid_version=(N_("Restore: Invalid Storage File Version"),
                             N_("The selected backup file was created by an incompatible version of backup. Please select another "
                                "storage file.")),
    mismatch_rules=[
        MismatchRule(MISMATCH_DEVICE_TYPE, DEVICE_MISMATCH, DEVICE_MISMATCH_TEXT, OUTCOME_DATA_ONLY),
        MismatchRule(MISMATCH_LANGUAGE, DEVICE_MISMATCH, DEVICE_MISMATCH_TEXT, OUTCOME_DATA_ONLY),
        MismatchRule(MISMATCH_VERSION, DEVICE_MISMATCH, DEVICE_MISMATCH_TEXT, OUTCOME_DATA_ONLY),
        MismatchRule(MISMATCH_OEM, DEVICE_MISMATCH, DEVICE_MISMATCH_TEXT, OUTCOME_DATA_ONLY),
        MismatchRule(MISMATCH_PROCESSOR, N_("Processor Mismatch"),
                     N_("The selected backup file was created by an H/PC that uses a different processor than the current H/PC. "
                        "While the data stored in this file will work on the current H/PC, the stored programs will not and may "
                        "disable the H/PC if you try to run them.\n\nIf you restore from this file, remove the restored programs "
                        "from the H/PC and then reinstall them correctly.\n\nContinue with restore?"), OUTCOME_FULL),
        MismatchRule(MISMATCH_PARTNERSHIP, N_("Backup Warning: Backup Mismatch"),
                     N_("The backup file was not created from this H/PC. Do you wish to continue ?"), OUTCOME_FULL),
    ],
    busy_synchronizing=(N_("Synchronization Manager"), N_("Synchronization is in progress. Please try again later.")),
    busy_backing_up=(N_("Backup/Restore Properties"), N_("A backup is in progress. Please try again later.")),
    busy_restoring=(N_("Backup/Restore Properties"), N_("A restore is in progress. Please try again later.")),
)

PAGE_TEXT = ExplorerPageText(
    back_up_group=N_("Back Up Now"),
    full=N_("F&ull: back up all data"),
    incremental=N_("&Incremental: back up only data that has changed since the last backup"),
    automatic_group=N_("Automatic Backup (incremental only)"),
    automatic=N_("Auto&matically back up upon connecting"),
    path_label=N_("Automatic backup &path and filename:"),
    restore_texts=(
        N_("The Restore operation allows you to return your H/PC to the state it was in at the time you last backed up.  This "
           "operation should be used only as a last resort as it removes all current files and data from your H/PC."),
        N_("To ensure a successful restore, quit all programs on your H/PC. Then click Restore Now."),
        N_("Please do not use your H/PC until after the Restore operation has completed."),
    ),
)


class BackupRestoreSheet(PropertySheet):
    def __init__(self, parent, frontend):
        super().__init__(parent, _("Backup/Restore Properties"))
        self.frontend = frontend
        partnership = frontend.application.partnership
        self.backup_settings = BackupSettings.load(partnership)
        self.backup_page = ExplorerBackupPage(self.notebook, self.backup_settings, PAGE_TEXT, WORDING, partnership is None,
                                              self.back_up_now, self.changed)
        self.notebook.AddPage(self.backup_page, _("Backup"))
        self.notebook.AddPage(ExplorerRestorePage(self.notebook, PAGE_TEXT, self.restore_now), _("Restore"))
        self.finish()

    def apply(self):
        self.backup_page.apply(self.backup_settings)
        self.backup_settings.save()

    def back_up_now(self):
        self.apply()
        if self.apply_button:
            self.apply_button.Enable(False)
        BackupFlow(self.frontend, self, WORDING).back_up_now(full=not self.backup_settings.incremental)

    def restore_now(self):
        BackupFlow(self.frontend, self, WORDING).restore_now()


class BackupNotCompleteDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Backup Not Complete"))
        self.SetClientSize(dialog_size(self, 254, 55))
        wx.StaticBitmap(self, bitmap=warning_bitmap(), pos=self.ConvertDialogToPixels(wx.Point(7, 7)))
        place(self, wx.StaticText, 37, 7, 210, 16, _("You have not completed a full backup. Setup recommends you complete a full "
                                                     "backup before proceeding."))
        place(self, wx.Button, 70, 34, 56, 14, _("Back Up &Now"), id=wx.ID_OK).SetDefault()
        place(self, wx.Button, 132, 34, 50, 14, _("&Skip"), id=wx.ID_CANCEL)
        if parent:
            self.CentreOnParent()
        else:
            self.CentreOnScreen()


def show_backup_restore(parent, frontend):
    with BackupRestoreSheet(parent, frontend) as sheet:
        sheet.ShowModal()


def back_up_now(frontend, parent):
    BackupFlow(frontend, parent, WORDING).back_up_now()


def run_automatic_backup(frontend, parent):
    settings = BackupSettings.load(frontend.application.partnership)
    BackupFlow(frontend, parent, WORDING).start_backup(settings.path, False, automatic=True)


def restore_guest(frontend, parent):
    path = choose_backup_file(parent, WORDING, None, False)
    if path:
        BackupFlow(frontend, parent, WORDING).restore_now(path)


def offer_full_backup(frontend, parent):
    with BackupNotCompleteDialog(parent) as dialog:
        if dialog.ShowModal() != wx.ID_OK:
            return
    settings = BackupSettings.load(frontend.application.partnership)
    BackupFlow(frontend, parent, WORDING).start_backup(settings.path, True)
