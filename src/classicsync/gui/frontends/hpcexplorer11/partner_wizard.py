from pathlib import Path

import wx

from ....i18n import N_, _
from ...common.backup import BackupSettings
from ...common.backup_dialogs import BackupFlow, warning_bitmap
from ...common.classic_wizard import ClassicWizard
from ...common.layout import dialog_size, place
from ...common.sync_runner import SYNC_MODE_CONNECT, SYNC_MODE_MANUAL
from .artwork import EXPLORER
from .backup import WORDING, BackupNotCompleteDialog

TITLE = N_("Setup New Partner Wizard")
SIDE_BITMAP = "bitmap_158.bmp"

PAGE_SYNC_ON_CONNECT = 149
PAGE_DEVICE_PARTNERED = 151
PAGE_INTRO = 159
PAGE_ALREADY_PARTNERED = 162
PAGE_SUCCESS = 163
PAGE_FAILURE = 164
PAGE_AUTOMATIC_BACKUP = 165
PAGE_FULL_BACKUP = 166
PAGE_COMPLETE = 170
PAGE_SYNCHRONIZE = 188

PAGE_TEXT = {
    PAGE_INTRO: [
        (N_("This wizard will help you set up a partner H/PC for this desktop computer."), 92, 0, 180, 16),
        (N_("Note: This desktop computer may have only one partner H/PC. In addition, each H/PC may only have one partner "
            "desktop computer."), 92, 24, 181, 24),
        (N_("To begin setup, click Next."), 92, 56, 178, 8),
    ],
    PAGE_DEVICE_PARTNERED: [
        (N_("Warning: Partner desktop computer already established."), 92, 0, 184, 8),
        (N_("The H/PC you have connected has already established another computer as its partner desktop computer. Proceeding "
            "with this wizard will remove the other computer as the partner, replacing it with this desktop computer."), 92, 16, 184, 32),
        (N_("You will no longer be able to synchronize or automatically back up this H/PC with the other desktop computer."),
         92, 56, 184, 16),
        (N_("To proceed, click Next. To abort, click Cancel."), 92, 80, 184, 8),
    ],
    PAGE_ALREADY_PARTNERED: [
        (N_("Partnership already established."), 92, 0, 184, 16),
        (N_("The H/PC you have connected has already been established as the partner H/PC for this desktop computer."), 92, 16, 184, 28),
        (N_("To complete setup, click Finish."), 92, 49, 184, 8),
    ],
    PAGE_SUCCESS: [
        (N_("Partnership successfully established."), 92, 0, 184, 8),
        (N_("Partnership has been successfully established between this desktop computer and the connected H/PC."), 92, 16, 184, 16),
        (N_("Click Next to proceed with initial backup and database synchronization setup."), 92, 40, 184, 16),
    ],
    PAGE_FAILURE: [
        (N_("Failed to establish partnership."), 92, 0, 184, 8),
        (N_("Setup has encountered an unknown error while attempting to establish partnership between this desktop computer and "
            "the connected H/PC."), 92, 16, 184, 24),
        (N_("Setup of partner H/PC has failed."), 92, 48, 184, 8),
        (N_("Restart Windows and reset the H/PC and run the Setup New Partner Wizard again."), 92, 64, 184, 16),
    ],
    PAGE_AUTOMATIC_BACKUP: [
        (N_("To ensure the safety of your future data, H/PC Explorer can automatically back up each time you connect your H/PC."),
         92, 0, 181, 24),
        (N_("Note: Automatic backup copies only the data that has changed since the last backup and generally completes very "
            "quickly."), 92, 30, 184, 24),
        (N_("To enable automatic backup (recommended), click Next."), 92, 60, 184, 8),
        (N_("Automatic backup path and filename:"), 92, 96, 184, 8),
    ],
    PAGE_FULL_BACKUP: [
        (N_("Full Backup"), 92, 0, 184, 8),
        (N_("To ensure the safety of your current data you should complete a full backup of your H/PC."), 92, 16, 184, 16),
        (N_("To complete backup now (recommended) select the Back Up Now button."), 92, 40, 179, 16),
        (N_("Note: Full backup copies all data on your H/PC and may take a few minutes to complete."), 92, 64, 181, 16),
    ],
    PAGE_SYNCHRONIZE: [
        (N_("The Synchronization Manager keeps your Appointment, Contact, and Task data current between the H/PC and your "
            "desktop computer."), 92, 0, 184, 24),
        (N_("Click the Synchronize Now button below to set up synchronization and add your desktop data to your H/PC."),
         92, 32, 184, 24),
    ],
    PAGE_SYNC_ON_CONNECT: [
        (N_("Synchronization Manager can automatically synchronize your Appointments, Contacts, and Tasks each time you connect "
            "your H/PC to your desktop computer."), 92, 0, 184, 24),
        (N_("To enable synchronization upon connecting, click Next."), 92, 32, 184, 8),
        (N_("To disable synchronization upon connecting, clear the check box, and then click Next."), 92, 48, 184, 16),
    ],
    PAGE_COMPLETE: [
        (N_("Setup completed successfully!"), 92, 0, 184, 8),
        (N_("Setup of partner H/PC is complete. To finish, select the Finish button."), 92, 16, 184, 16),
    ],
}
FINISH_PAGES = {PAGE_ALREADY_PARTNERED, PAGE_FAILURE, PAGE_COMPLETE}


class ChoiceNag(wx.Dialog):
    def __init__(self, parent, title, width, lines, accept, decline, accept_x, decline_x, accept_width=56, button_top=55):
        super().__init__(parent, title=title)
        self.SetClientSize(dialog_size(self, width, button_top + 21))
        wx.StaticBitmap(self, bitmap=warning_bitmap(), pos=self.ConvertDialogToPixels(wx.Point(7, 7)))
        for text, top in lines:
            place(self, wx.StaticText, 37, top, width - 44, 16, text)
        place(self, wx.Button, accept_x, button_top, accept_width, 14, accept, id=wx.ID_OK).SetDefault()
        place(self, wx.Button, decline_x, button_top, 50, 14, decline, id=wx.ID_CANCEL)
        self.CentreOnParent()


def exit_setup_dialog(parent):
    return ChoiceNag(parent, _("Exit Setup"), 254, [
        (_("Partner H/PC Setup is not complete. If you quit Setup, you may not have access to some partner H/PC features."), 7),
        (_("To continue (recommended), choose Resume. To quit, choose Exit Setup."), 31),
    ], _("&Resume"), _("&Exit Setup"), 74, 130, accept_width=50)


def sync_not_complete_dialog(parent):
    return ChoiceNag(parent, _("Synchronization Not Complete"), 272, [
        (_("You have not synchronized your Appointment, Contact, and Task data. Setup recommends you perform this "
           "synchronization before proceeding."), 7),
        (_("If you choose to skip this step, you can set up synchronization in the future via the Tools->Synchronization "
           "Manager menu."), 31),
    ], _("Synchronize &Now"), _("&Skip"), 75, 145, accept_width=64)


class PartnerWizard(ClassicWizard):
    page_text = PAGE_TEXT
    finish_pages = FINISH_PAGES
    first_page = PAGE_INTRO

    def __init__(self, parent, frontend):
        self.backed_up = False
        self.synchronized = False
        self.side = frontend.artwork.bitmap(EXPLORER, SIDE_BITMAP, transparent=False)
        super().__init__(parent, frontend, _(TITLE))

    def side_bitmap(self, number):
        return self.side

    def build_page(self, number, page):
        if number == PAGE_AUTOMATIC_BACKUP:
            place(page, wx.StaticLine, 92, 74, 184, 1)
            self.automatic_backup = place(page, wx.CheckBox, 92, 82, 184, 10, _("&Automatically back up upon connecting"))
            self.automatic_backup.SetValue(True)
            self.backup_path = place(page, wx.TextCtrl, 92, 107, 184, 14, "")
            browse = place(page, wx.Button, 230, 126, 46, 14, _("Br&owse..."))
            browse.Bind(wx.EVT_BUTTON, self.on_browse)
        elif number == PAGE_FULL_BACKUP:
            place(page, wx.Button, 154, 88, 56, 14, _("B&ack Up Now")).Bind(wx.EVT_BUTTON, lambda event: self.back_up())
        elif number == PAGE_SYNCHRONIZE:
            place(page, wx.Button, 146, 64, 68, 14, _("&Synchronize Now")).Bind(wx.EVT_BUTTON, lambda event: self.synchronize())
        elif number == PAGE_SYNC_ON_CONNECT:
            place(page, wx.StaticLine, 92, 72, 184, 1)
            self.sync_on_connect = place(page, wx.CheckBox, 92, 80, 184, 10, _("&Automatically synchronize upon connecting"))
            self.sync_on_connect.SetValue(True)

    def page_shown(self, number):
        if number == PAGE_AUTOMATIC_BACKUP and not self.backup_path.GetValue() and self.application.partnership:
            self.backup_path.SetValue(str(BackupSettings.load(self.application.partnership).path))

    def can_go_back(self):
        if not self.history:
            return False
        return not (self.application.partnership and self.history[-1] in (PAGE_INTRO, PAGE_DEVICE_PARTNERED))

    def device_has_other_partner(self):
        partners = self.application.device_partners
        return bool(partners and partners.partners)

    def on_next(self, event):
        current = self.current
        if current in FINISH_PAGES:
            self.EndModal(wx.ID_OK if current != PAGE_FAILURE else wx.ID_CANCEL)
        elif current == PAGE_INTRO:
            if self.application.partnership:
                self.go(PAGE_ALREADY_PARTNERED)
            elif self.device_has_other_partner():
                self.go(PAGE_DEVICE_PARTNERED)
            else:
                self.create_partnership()
        elif current == PAGE_DEVICE_PARTNERED:
            self.create_partnership()
        elif current == PAGE_SUCCESS:
            self.go(PAGE_AUTOMATIC_BACKUP)
        elif current == PAGE_AUTOMATIC_BACKUP:
            self.save_backup_settings()
            self.go(PAGE_FULL_BACKUP)
        elif current == PAGE_FULL_BACKUP:
            if not self.backed_up:
                with BackupNotCompleteDialog(self) as dialog:
                    if dialog.ShowModal() == wx.ID_OK:
                        self.back_up()
            self.go(PAGE_SYNCHRONIZE)
        elif current == PAGE_SYNCHRONIZE:
            if not self.synchronized:
                with sync_not_complete_dialog(self) as dialog:
                    if dialog.ShowModal() == wx.ID_OK:
                        self.synchronize()
            self.go(PAGE_SYNC_ON_CONNECT)
        elif current == PAGE_SYNC_ON_CONNECT:
            settings = self.application.settings
            settings.sync_mode = SYNC_MODE_CONNECT if self.sync_on_connect.GetValue() else SYNC_MODE_MANUAL
            settings.save()
            self.go(PAGE_COMPLETE)

    def confirm_cancel(self):
        with exit_setup_dialog(self) as dialog:
            return dialog.ShowModal() == wx.ID_CANCEL

    def on_browse(self, event):
        current = self.backup_path.GetValue()
        with wx.FileDialog(self, _("Automatic backup path and filename:"), defaultFile=Path(current).name if current else "",
                           wildcard=_("Backup Files (*.stg)|*.stg"), style=wx.FD_SAVE) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.backup_path.SetValue(dialog.GetPath())

    def create_partnership(self):
        self.set_busy(True)

        def created(partnership, error):
            if not self:
                return
            self.busy = False
            if partnership is None or error:
                self.history = []
                self.show_page(PAGE_FAILURE)
                return
            self.go(PAGE_SUCCESS)

        self.application.create_partnership(created, exclusive=True)

    def save_backup_settings(self):
        if not self.application.partnership:
            return
        settings = BackupSettings.load(self.application.partnership)
        settings.automatic = self.automatic_backup.GetValue()
        path = self.backup_path.GetValue().strip()
        if path and Path(path) != settings.path:
            settings.file = path
        settings.save()

    def back_up(self):
        if not self.application.partnership:
            return
        settings = BackupSettings.load(self.application.partnership)
        if BackupFlow(self.frontend, self, WORDING).start_backup(settings.path, True) is not False:
            self.backed_up = True

    def synchronize(self):
        self.frontend.sync.start()
        self.synchronized = True


def run_partner_wizard(parent, frontend):
    with PartnerWizard(parent, frontend) as wizard:
        return wizard.ShowModal() == wx.ID_OK
