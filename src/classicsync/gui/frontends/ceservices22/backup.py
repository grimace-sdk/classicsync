import wx

from ....backup import VERSION_ACTIVESYNC
from ....i18n import N_, _, format_original
from ...common.backup import (
    MISMATCH_DEVICE_TYPE, MISMATCH_LANGUAGE, MISMATCH_NEWER_VERSION, MISMATCH_OEM, MISMATCH_PARTNERSHIP, MISMATCH_PROCESSOR,
    MISMATCH_VERSION, BackupSettings,
)
from ...common.backup_dialogs import (
    BUTTONS_OK_CANCEL, OUTCOME_ABORT, OUTCOME_DATA_ONLY, OUTCOME_FULL, BackupFlow, BackupWording, MismatchRule,
)
from ...common.backup_pages import ExplorerBackupPage, ExplorerPageText, ExplorerRestorePage
from .artwork import VIEWER
from .sheet import lay_out_property_sheet

DEVICE_MISMATCH = N_("Device Mismatch")
DEVICE_MISMATCH_CONTINUE = N_("The backup file you have selected was created from an incompatible device. Should you proceed with "
                              "this restore operation, the following could result:\n\nPrograms will not be restored.\nSome data may "
                              "not be restored.\nSome restored data may be unusable.\nYour device may not work properly.\n\n"
                              "Continue with restore?")

WORDING = BackupWording(
    file_version=VERSION_ACTIVESYNC,
    readable_versions=(VERSION_ACTIVESYNC,),
    animation_module=VIEWER,
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
                        "Unit (CPU) than the device you have connected. Restore will copy only your data files (such as Pocket "
                        "Excel files) and Pocket Outlook data.\n\nAfter restore is complete, you will need to reinstall any "
                        "applications that had been installed on the previous mobile device and re-enter your settings."),
                     OUTCOME_DATA_ONLY, BUTTONS_OK_CANCEL),
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
    busy_synchronizing=(N_("Synchronization in Progress:"), N_("Synchronization is in progress from another Explorer window. Please "
                                                               "try again later.")),
    busy_backing_up=(N_("Backup in Progress:"), N_("Backup is in progress from another Explorer window. Please try again later.")),
    busy_restoring=(N_("Restore in Progress:"), N_("Restore is in progress from another Explorer window. Please try again later.")),
    cannot_locate=(N_("Backup Cannot Locate Backup File"), N_("Backup was unable to locate your backup file. Click OK to\r\nspecify a "
                                                              "backup file. Click Cancel to cancel the backup.")),
    partnership_selection=(N_("Partnership Profile Selection"),
                           N_("Select the partnership profile in the list below that contains your backup file.  Click Browse if "
                              "your backup file is not stored with your profile.")),
)

PAGE_TEXT = ExplorerPageText(
    back_up_group=N_("Back up now"),
    full=N_("F&ull: Back up all data"),
    incremental=N_("&Incremental: Back up only data that has changed since the last backup"),
    automatic_group=N_("Automatic backup (incremental only)"),
    automatic=N_("Auto&matically back up upon connecting"),
    path_label=N_("Backup &path and filename:"),
    restore_texts=(
        N_("Performing a restore allows you to return your device to the state it was in when you last did a backup.  This "
           "operation should be used only as a last resort as it removes all current files and data from your device."),
        N_("To restore successfully, quit all programs on your device. Then click Restore Now."),
        N_("Do not use your device until after the restore has completed."),
    ),
)


class BackupRestoreSheet(wx.Dialog):
    def __init__(self, parent, frontend):
        device = frontend.application.device_name(frontend.service.announcement)
        super().__init__(parent, title=format_original(_("%s Backup/Restore Properties"), device))
        self.frontend = frontend
        partnership = frontend.application.partnership
        self.backup_settings = BackupSettings.load(partnership)
        notebook = wx.Notebook(self)
        self.backup_page = ExplorerBackupPage(notebook, self.backup_settings, PAGE_TEXT, WORDING, partnership is None,
                                              self.back_up_now, self.changed)
        notebook.AddPage(self.backup_page, _("Backup"))
        notebook.AddPage(ExplorerRestorePage(notebook, PAGE_TEXT, self.restore_now), _("Restore"))
        lay_out_property_sheet(self, notebook, apply_enabled=False)
        self.apply_button = self.FindWindow(wx.ID_APPLY)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.Bind(wx.EVT_BUTTON, self.on_apply, id=wx.ID_APPLY)
        self.CentreOnParent()

    def changed(self):
        self.apply_button.Enable(True)

    def apply(self):
        self.backup_page.apply(self.backup_settings)
        self.backup_settings.save()
        self.apply_button.Enable(False)

    def on_apply(self, event):
        self.apply()

    def on_ok(self, event):
        self.apply()
        self.EndModal(wx.ID_OK)

    def back_up_now(self):
        self.apply()
        BackupFlow(self.frontend, self, WORDING).back_up_now(full=not self.backup_settings.incremental)

    def restore_now(self):
        BackupFlow(self.frontend, self, WORDING).restore_now()


def show_backup_restore(parent, frontend):
    with BackupRestoreSheet(parent, frontend) as sheet:
        sheet.ShowModal()


def back_up_now(frontend, parent):
    BackupFlow(frontend, parent, WORDING).back_up_now()


def run_automatic_backup(frontend, parent):
    settings = BackupSettings.load(frontend.application.partnership)
    BackupFlow(frontend, parent, WORDING).start_backup(settings.path, False, automatic=True)


def restore_guest(frontend, parent):
    BackupFlow(frontend, parent, WORDING).restore_now(choose=True)
