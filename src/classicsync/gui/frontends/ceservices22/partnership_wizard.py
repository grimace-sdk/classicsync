import wx

from ....i18n import N_, _, format_original
from ....sync.partners import valid_device_name
from ...common.classic_wizard import ClassicWizard
from ...common.layout import dialog_size, place
from ...common.sync_runner import SYNC_MODE_CONNECT, SYNC_MODE_MANUAL
from .artwork import VIEWER

TITLE = N_("New Partnership Wizard")

PAGE_INTRO = 159
PAGE_ALREADY_PARTNERED = 161
PAGE_SUCCESS = 163
PAGE_FAILURE = 164
PAGE_NAME = 165
PAGE_COMPLETE = 170
PAGE_LIMIT = 183
PAGE_SYNC_MODE = 188
PAGE_SERVICES = 1018

SIDE_BITMAPS = {PAGE_INTRO: 594, PAGE_NAME: 594, PAGE_COMPLETE: 593, PAGE_SYNC_MODE: 595, PAGE_SERVICES: 595}
DEFAULT_SIDE_BITMAP = 592

PAGE_TEXT = {
    PAGE_INTRO: [
        (N_("This wizard will set up a partnership with this mobile device.  Partnership settings will be stored in the new "
            "partnership profile."), 92, 0, 184, 24),
        (N_("Note: Your device may partner with up to two desktop computers."), 92, 32, 184, 16),
        (N_("To begin Setup, click Next."), 92, 56, 184, 8),
    ],
    PAGE_ALREADY_PARTNERED: [
        (N_("Partnership already established."), 92, 0, 184, 16),
        (N_("The device you have connected has already been established as a partner device for this desktop computer."), 92, 16, 184, 24),
        (N_("To complete Setup, click Finish."), 92, 48, 184, 8),
    ],
    PAGE_NAME: [
        (N_("You must enter a unique name for your mobile device. This name is used to identify the partnership profile stored in "
            "the Mobile Devices folder on your desktop computer."), 92, 0, 184, 24),
        (N_("Please enter a name containing no spaces or any of the following characters: \\ / : * ? \" < > | &&.\n\nYou may also "
            "enter a device description at this time."), 92, 32, 184, 38),
        (N_("D&evice Name:"), 92, 75, 62, 8),
        (N_("Device &Description:"), 92, 95, 62, 8),
    ],
    PAGE_LIMIT: [
        (N_("Warning: Device partnership limit exceeded."), 92, 0, 184, 8),
        (N_("The number of partnerships your device can support has been exceeded. An existing partnership must be removed to "
            "proceed. Your device has established partnerships with the desktop computers in the list below. Select a desktop"),
         92, 16, 184, 32),
        (N_("computer from the list and click Delete to remove that partnership."), 92, 48, 184, 16),
        (N_("Note: The device will lose all services currently configured with the desktop computer whose partnership you remove."),
         92, 72, 184, 16),
        (N_("To proceed, click Next. To cancel, click Cancel."), 92, 128, 184, 8),
    ],
    PAGE_SUCCESS: [
        (N_("Partnership successfully established."), 92, 0, 184, 8),
        (N_("Partnership has been successfully established between this desktop computer and the connected device."), 92, 16, 184, 16),
        (N_("Click Next to proceed with setup of services for this device."), 92, 40, 184, 16),
    ],
    PAGE_FAILURE: [
        (N_("Failed to establish partnership."), 92, 0, 184, 8),
        (N_("Setup has encountered an unknown error while attempting to establish a partnership between this desktop computer and "
            "the connected device."), 92, 16, 184, 24),
        (N_("Setup of partnership has failed. You will be connected as a guest."), 92, 48, 184, 16),
        (N_("To retry partnership setup, restart Windows and the device, then reconnect the device to run this wizard again."),
         92, 72, 184, 24),
    ],
    PAGE_SYNC_MODE: [
        (N_("Windows CE Services ActiveSync gives you control over how your mobile device will synchronize when connected to this "
            "desktop computer.\n\nClick on your synchronization preference from the list below."), 92, 0, 184, 49),
        (N_("Synchronize my device only when I click Synchronize Now."), 159, 52, 116, 18),
        (N_("Synchronize my device each time it is connected."), 159, 74, 116, 17),
        (N_("Synchronize my device continuously when information needs updating."), 159, 95, 116, 18),
        (N_("Select ActiveSync Options on the Mobile Devices Tools menu to change synchronization options at any time."),
         92, 117, 183, 21),
    ],
    PAGE_SERVICES: [
        (N_("Now choose what to synchronize\n\nClick the check box next to an item in the list below to enable or disable that item "
            "for synchronization. A check indicates that the item will be synchronized."), 92, 0, 184, 45),
    ],
    PAGE_COMPLETE: [
        (N_("Partnership successfully established."), 92, 0, 184, 8),
        (N_("Partnership settings are stored in your device partnership profile, which appears in the Mobile Devices folder on "
            "your desktop computer."), 92, 16, 184, 24),
        (N_("To view partnership settings, select your device in the Mobile Devices folder and click a command on the Tools menu."),
         92, 48, 184, 24),
        (N_("To view the files and folders on your mobile device, double click your device in the Mobile Devices folder."),
         92, 80, 184, 16),
    ],
}
FINISH_PAGES = {PAGE_ALREADY_PARTNERED, PAGE_FAILURE, PAGE_COMPLETE}

CHOICE_SINGLE = "single"
CHOICE_MULTIPLE = "multiple"
CHOICE_BROWSE = "browse"


class MultiplePartnershipDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Multiple Partnership Synchronization"))
        self.SetClientSize(dialog_size(self, 296, 158))
        self.choice = None
        icon = wx.ArtProvider.GetBitmap(wx.ART_WARNING, wx.ART_MESSAGE_BOX, wx.Size(32, 32))
        wx.StaticBitmap(self, bitmap=icon, pos=self.ConvertDialogToPixels(wx.Point(7, 7)))
        place(self, wx.StaticText, 44, 7, 237, 24, _("This device has a partnership with another desktop computer. You may choose to "
                                                     "synchronize with only this desktop (\"Single\") or with more than one computer "
                                                     "(\"Multiple\")."))
        place(self, wx.StaticLine, 7, 40, 282, 1)
        rows = [
            (CHOICE_SINGLE, _("&Single"), 53, _("Remove previous partnership(s) and synchronize only with this desktop computer."), 20),
            (CHOICE_MULTIPLE, _("&Multiple"), 79, _("Keep previous partnership(s) and synchronize between both desktop computers. ActiveSync "
                                                    "will no longer remove items from your device as specified by your ActiveSync Options."), 24),
            (CHOICE_BROWSE, _("&Browse"), 105, _("I only want to transfer files for now, I do not want to synchronize."), 14),
        ]
        for choice, label, top, text, height in rows:
            button = place(self, wx.Button, 9, top, 62, 14, label)
            button.Bind(wx.EVT_BUTTON, lambda event, choice=choice: self.choose(choice))
            place(self, wx.StaticText, 79, top, 207, height, text)
        self.CentreOnParent()

    def choose(self, choice):
        self.choice = choice
        self.EndModal(wx.ID_OK)


def name_problem(name, partnerships):
    if not valid_device_name(name):
        return (_("Invalid Character in Mobile Device Name"),
                format_original(_("Cannot rename device to '%s'. The device name contains characters which are not valid.\r\n\r\n"
                                  "Please type in another name now."), name))
    if name.lower() in {partnership.name.lower() for partnership in partnerships}:
        return (_("Device Name In Use"),
                format_original(_("Cannot rename device to '%s'. This name may already in use by another partnership or is an "
                                  "illegal device name.\r\n\r\nPlease type in another name now."), name))
    return None


class NewPartnershipWizard(ClassicWizard):
    page_text = PAGE_TEXT
    finish_pages = FINISH_PAGES
    first_page = PAGE_INTRO

    def __init__(self, parent, frontend):
        self.chose_guest = False
        self.exclusive = False
        artwork = frontend.artwork
        self.bitmaps = {number: artwork.bitmap(VIEWER, f"bitmap_{number}.bmp", transparent=False)
                        for number in set(SIDE_BITMAPS.values()) | {DEFAULT_SIDE_BITMAP}}
        super().__init__(parent, frontend, _(TITLE))

    def side_bitmap(self, number):
        return self.bitmaps[SIDE_BITMAPS.get(number, DEFAULT_SIDE_BITMAP)]

    def build_page(self, number, page):
        details = self.application.device_details
        if number == PAGE_NAME:
            self.name = place(page, wx.TextCtrl, 160, 73, 116, 12, details.get("name", ""))
            self.description = place(page, wx.TextCtrl, 160, 93, 116, 12, details.get("description", ""))
        elif number == PAGE_LIMIT:
            self.existing = place(page, wx.ListBox, 92, 96, 120, 24, style=wx.LB_SINGLE | wx.LB_SORT)
            self.delete = place(page, wx.Button, 222, 102, 46, 14, _("&Delete"))
            self.delete.Bind(wx.EVT_BUTTON, self.on_delete)
            self.existing.Bind(wx.EVT_LISTBOX, lambda event: self.update_buttons())
        elif number == PAGE_SYNC_MODE:
            self.manual = place(page, wx.RadioButton, 92, 52, 62, 10, _("&Manual"), style=wx.RB_GROUP)
            self.on_connect = place(page, wx.RadioButton, 92, 73, 62, 10, _("&On Connect"))
            continuous = place(page, wx.RadioButton, 92, 94, 62, 10, _("&Continuous"))
            continuous.Enable(False)
            (self.on_connect if self.application.settings.sync_mode == SYNC_MODE_CONNECT else self.manual).SetValue(True)
        elif number == PAGE_SERVICES:
            self.services = place(page, wx.ListCtrl, 92, 54, 181, 86, style=wx.LC_REPORT | wx.LC_NO_HEADER | wx.LC_SINGLE_SEL)
            self.services.EnableCheckBoxes(True)
            self.services.InsertColumn(0, "", width=dialog_size(page, 170, 0).width)
            self.object_types = sorted(self.frontend.sync.object_types(), key=lambda entry: _(entry[0].display_name))
            for index, (object_type, enabled) in enumerate(self.object_types):
                self.services.InsertItem(index, _(object_type.display_name))
                self.services.CheckItem(index, enabled)
        elif number == PAGE_COMPLETE:
            place(page, wx.CheckBox, 92, 104, 184, 10, _("&Show me the Guided Tour")).Enable(False)

    def page_shown(self, number):
        if number == PAGE_LIMIT:
            self.existing.Clear()
            for partner in self.application.device_partners.partners:
                self.existing.Append(partner.desktop_name or _("Partnership {number}").format(number=partner.slot), partner.slot)

    def update_buttons(self):
        super().update_buttons()
        if self.current == PAGE_LIMIT:
            self.delete.Enable(not self.busy and self.existing.GetSelection() != wx.NOT_FOUND)

    def can_go_next(self):
        if self.current == PAGE_LIMIT:
            return not self.application.device_partners.full
        return True

    def can_go_back(self):
        if not self.history:
            return False
        return not (self.application.partnership and self.history[-1] in (PAGE_INTRO, PAGE_NAME, PAGE_LIMIT))

    def on_next(self, event):
        current = self.current
        if current in FINISH_PAGES:
            self.EndModal(wx.ID_OK if current == PAGE_COMPLETE else wx.ID_CANCEL)
        elif current == PAGE_INTRO:
            self.go(PAGE_ALREADY_PARTNERED if self.application.partnership else PAGE_NAME)
        elif current == PAGE_NAME:
            problem = name_problem(self.name.GetValue().strip(), self.application.partnerships())
            if problem:
                title, text = problem
                wx.MessageBox(text.replace("\r\n", "\n"), title, wx.OK | wx.ICON_EXCLAMATION, self)
                return
            partners = self.application.device_partners
            if partners and partners.full:
                self.go(PAGE_LIMIT)
            else:
                self.choose_partnership_kind()
        elif current == PAGE_LIMIT:
            self.create_partnership()
        elif current == PAGE_SUCCESS:
            self.go(PAGE_SYNC_MODE)
        elif current == PAGE_SYNC_MODE:
            settings = self.application.settings
            settings.sync_mode = SYNC_MODE_CONNECT if self.on_connect.GetValue() else SYNC_MODE_MANUAL
            settings.save()
            self.go(PAGE_SERVICES)
        elif current == PAGE_SERVICES:
            self.save_services()
            self.go(PAGE_COMPLETE)

    def choose_partnership_kind(self):
        partners = self.application.device_partners
        if partners and partners.partners:
            with MultiplePartnershipDialog(self) as dialog:
                dialog.ShowModal()
                choice = dialog.choice
            if choice is None:
                return
            if choice == CHOICE_BROWSE:
                self.chose_guest = True
                self.EndModal(wx.ID_CANCEL)
                return
            self.exclusive = choice == CHOICE_SINGLE
        self.create_partnership()

    def on_delete(self, event):
        selection = self.existing.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        slot = self.existing.GetClientData(selection)
        self.set_busy(True)

        def removed(partners, error):
            if not self:
                return
            self.set_busy(False)
            if error:
                wx.MessageBox(str(error), _(TITLE), wx.OK | wx.ICON_ERROR, self)
            self.page_shown(PAGE_LIMIT)
            self.update_buttons()

        self.application.remove_device_partner(slot, removed)

    def create_partnership(self):
        self.set_busy(True)
        name = self.name.GetValue().strip()
        description = self.description.GetValue().strip()

        def created(partnership, error):
            if not self:
                return
            self.busy = False
            if partnership is None or error:
                self.history = []
                self.show_page(PAGE_FAILURE)
                return
            self.go(PAGE_SUCCESS)

        self.application.create_partnership(created, name=name, exclusive=self.exclusive, description=description)

    def save_services(self):
        partnership = self.application.partnership
        if not partnership:
            return
        options = partnership.load_options()
        options.object_types = [object_type.key for index, (object_type, _enabled) in enumerate(self.object_types)
                                 if self.services.IsItemChecked(index)]
        partnership.save_options(options)


def run_partnership_wizard(parent, frontend):
    with NewPartnershipWizard(parent, frontend) as wizard:
        return wizard.ShowModal() == wx.ID_OK
