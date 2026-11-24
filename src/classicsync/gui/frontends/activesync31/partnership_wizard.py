import wx

from ....i18n import N_, _, format_original, plain_newlines
from ....sync.partners import valid_device_name
from ...branding import rebrand
from ...common.layout import bold, dialog_size, place
from .artwork import MANAGER

FRONTEND_KEY = "activesync31"
PAGE_WIDTH = 317
HEADER_HEIGHT = 36
BODY_TOP = HEADER_HEIGHT + 7
PAGE_HEIGHT = BODY_TOP + 143
EXTERIOR_BITMAP_WIDTH = 109
BUTTON_TOP = PAGE_HEIGHT + 7

PAGE_START = 136
PAGE_NAME = 118
PAGE_COUNT = 126
PAGE_DELETE = 120
PAGE_TYPES = 122
PAGE_COMPLETE = 127

FLAG_NAME = 0x02
FLAG_HAS_PARTNERSHIP = 0x04
FLAG_TWO_PARTNERSHIPS = 0x08
FLAG_TYPES = 0x10
FLAG_COMPLETE = 0x40

PAGE_ORDER = [(PAGE_NAME, FLAG_NAME), (PAGE_COUNT, FLAG_HAS_PARTNERSHIP), (PAGE_DELETE, FLAG_TWO_PARTNERSHIPS),
              (PAGE_TYPES, FLAG_TYPES), (PAGE_COMPLETE, FLAG_COMPLETE)]

TITLE = N_("New Partnership")
GUEST_TITLE = N_("Partnership Not Set Up")
GUEST_TEXT = (N_("Your device will be set up as a guest. You will be able to copy and move information between your device and "
              "this computer, but you will not be able to synchronize information.\r\n\r\nTo synchronize information, you need "
              "to set up a partnership. Disconnect and then reconnect the device to start the New Partnership Wizard."))
FAILED_TITLE = N_("Failed to Set Up Partnership")
FAILED_TEXT = (N_("An system error has prevented Microsoft ActiveSync from setting up a partnership between your mobile device and "
               "this computer.\n\nTo set up a partnership, disconnect your device, restart Windows on this computer, and then "
               "reconnect your device."))
INCOMPATIBLE_TEXT = (N_("This version of Microsoft ActiveSync is not compatible with the connected mobile device. Please upgrade "
                     "to the latest version of Microsoft ActiveSync and reconnect."))
NAME_TAKEN_TITLE = N_("Device Name Not Unique")
NAME_TAKEN_TEXT = N_("This device name is already in use.\r\n\r\nYou must enter a different name for your mobile device.")
NAME_INVALID_TITLE = N_("Invalid Character in Mobile Device Name")
NAME_INVALID_TEXT = (N_("Cannot rename device to '%s'. The device name contains characters which are not valid or is an illegal "
                     "device name.\r\n\r\nPlease type in another name now."))


def wizard_flags(device_name, partners, partnerships):
    flags = FLAG_TYPES | FLAG_COMPLETE
    taken = {partnership.name.lower() for partnership in partnerships}
    if not valid_device_name(device_name) or device_name.lower() in taken:
        flags |= FLAG_NAME
    if partners and partners.partners:
        flags |= FLAG_HAS_PARTNERSHIP
    if partners and partners.full:
        flags |= FLAG_TWO_PARTNERSHIPS
    return flags


class NewPartnershipWizard(wx.Dialog):
    def __init__(self, parent, frontend):
        super().__init__(parent, title=_(TITLE))
        self.frontend = frontend
        self.application = frontend.application
        self.partners = self.application.device_partners
        self.device_name = self.application.device_details.get("name") or ""
        self.flags = wizard_flags(self.device_name, self.partners, self.application.partnerships())
        self.history = []
        self.created = None
        self.chose_guest = False
        self.finishing = False
        self.SetClientSize(dialog_size(self, PAGE_WIDTH, BUTTON_TOP + 21))
        self.pages = {
            PAGE_START: self._build_start(), PAGE_NAME: self._build_name(), PAGE_COUNT: self._build_count(),
            PAGE_DELETE: self._build_delete(), PAGE_TYPES: self._build_types(), PAGE_COMPLETE: self._build_complete(),
        }
        place(self, wx.StaticLine, 0, PAGE_HEIGHT, PAGE_WIDTH, 1)
        self.back = place(self, wx.Button, 147, BUTTON_TOP, 50, 14, _("< &Back"))
        self.next = place(self, wx.Button, 197, BUTTON_TOP, 50, 14, _("&Next >"))
        self.cancel = place(self, wx.Button, 260, BUTTON_TOP, 50, 14, _("Cancel"), id=wx.ID_CANCEL)
        self.back.Bind(wx.EVT_BUTTON, self.on_back)
        self.next.Bind(wx.EVT_BUTTON, self.on_next)
        self.show_page(PAGE_START)
        self.CentreOnScreen()

    def _exterior(self, title):
        page = wx.Panel(self, pos=(0, 0), size=dialog_size(self, PAGE_WIDTH, PAGE_HEIGHT))
        page.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))
        bitmap = self.frontend.artwork.bitmap(MANAGER, "bitmap_6023.bmp", transparent=False)
        width = dialog_size(self, EXTERIOR_BITMAP_WIDTH, 0).width
        height = dialog_size(self, 0, PAGE_HEIGHT).height
        if bitmap.IsOk():
            image = bitmap.ConvertToImage()
            scaled_height = max(height, image.GetHeight() * width // image.GetWidth())
            image = image.Scale(width, scaled_height, wx.IMAGE_QUALITY_HIGH).GetSubImage(wx.Rect(0, 0, width, height))
            wx.StaticBitmap(page, bitmap=wx.Bitmap(image), pos=(0, 0))
        else:
            stripe = wx.Panel(page, pos=(0, 0), size=(width, height))
            stripe.SetBackgroundColour(wx.Colour(0, 51, 153))
        bold(place(page, wx.StaticText, 115, 9, 184, 19, title), 1.3)
        return page

    def _interior(self, title, subtitle):
        page = wx.Panel(self, pos=(0, 0), size=dialog_size(self, PAGE_WIDTH, PAGE_HEIGHT))
        header = wx.Panel(page, pos=(0, 0), size=dialog_size(self, PAGE_WIDTH, HEADER_HEIGHT))
        header.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))
        bold(place(header, wx.StaticText, 15, 7, 290, 9, title))
        place(header, wx.StaticText, 25, 18, 280, 9, subtitle)
        place(page, wx.StaticLine, 0, HEADER_HEIGHT, PAGE_WIDTH, 1)
        body = wx.Panel(page, pos=page.ConvertDialogToPixels(wx.Point(0, BODY_TOP)), size=dialog_size(self, PAGE_WIDTH, 143))
        return page, body

    def _build_start(self):
        page = self._exterior(_("Set Up a Partnership"))
        place(page, wx.StaticText, 115, 38, 184, 43, _("Before you can synchronize information between your mobile device and "
              "this computer, you must set up a partnership between them.\n\nWould you like to set up a partnership?"))
        self.partnership_yes = place(page, wx.RadioButton, 115, 85, 34, 10, _("&Yes"), style=wx.RB_GROUP)
        place(page, wx.StaticText, 127, 96, 172, 18, _("Set up a partnership so that I can synchronize information between my "
              "device and this computer."))
        self.partnership_no = place(page, wx.RadioButton, 115, 115, 34, 10, _("N&o"))
        place(page, wx.StaticText, 127, 128, 172, 25, _("I don't want to synchronize information. Set up my device as a guest "
              "so that I can copy or move information between my device and this computer."))
        self.partnership_yes.SetValue(True)
        return page

    def _build_name(self):
        page, body = self._interior(_("Name your Device"), _("Enter a unique name for your mobile device."))
        place(body, wx.StaticText, 21, 1, 282, 27, rebrand(_("Your device's name is part of the partnership information stored on both "
              "your device and this computer. Microsoft ActiveSync uses this name to identify which device is currently "
              "connected."), FRONTEND_KEY))
        place(body, wx.StaticText, 21, 35, 282, 23, _("Your device uses this information to identify itself to other computers. "
              "Enter a unique name that starts with a letter and contains the characters _, A-Z, or 0-9."))
        place(body, wx.StaticText, 21, 66, 55, 8, _("Device n&ame:"))
        self.name = place(body, wx.TextCtrl, 87, 64, 117, 12, self.device_name)
        self.name.SetMaxLength(15)
        return page

    def _build_count(self):
        page, body = self._interior(_("Select Number of Partnerships"), _("Select whether you want to synchronize with just this "
                                    "computer."))
        place(body, wx.StaticText, 21, 1, 282, 18, _("Do you want your mobile device to be synchronized with only this computer?"))
        self.only_this = place(body, wx.RadioButton, 21, 28, 206, 10, _("&Yes, I want to synchronize with only this computer."),
                               style=wx.RB_GROUP)
        place(body, wx.StaticText, 34, 43, 279, 18, _("Remove any existing partnerships on my device and set up a new partnership "
              "with just this computer."))
        self.two_computers = place(body, wx.RadioButton, 21, 69, 185, 11, _("N&o, I want to synchronize with two computers."))
        place(body, wx.StaticText, 34, 84, 279, 30, _("Set up a partnership with this computer, but do not remove any existing "
              "partnerships on my device."))
        self.two_computers.SetValue(True)
        return page

    def _build_delete(self):
        page, body = self._interior(_("Delete a Partnership"), _("Delete an existing partnership before setting up a new one."))
        place(body, wx.StaticText, 21, 1, 282, 30, _("Your mobile device has two partnerships. You cannot set up a partnership "
              "with this computer until you delete one of the existing partnerships. Deleting a partnership results in your "
              "device losing all settings associated with that partnership."))
        place(body, wx.StaticText, 21, 39, 282, 12, _("To delete a partnership, select it from the list and then click Delete."))
        self.existing = place(body, wx.ListBox, 21, 59, 120, 24, style=wx.LB_SINGLE | wx.LB_SORT)
        self.delete = place(body, wx.Button, 151, 59, 46, 14, _("&Delete"))
        self.delete.Bind(wx.EVT_BUTTON, self.on_delete)
        self.existing.Bind(wx.EVT_LISTBOX, lambda event: self.update_buttons())
        return page

    def _build_types(self):
        page, body = self._interior(_("Select Synchronization Settings"), _("Select the type of information you want to "
                                    "synchronize."))
        place(body, wx.StaticText, 21, 1, 282, 17, _("To synchronize a particular type of information, select its check box. "
              "To stop synchronization of that information, clear its check box."))
        self.types = place(body, wx.ListCtrl, 21, 24, 282, 89, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.types.EnableCheckBoxes(True)
        self.types.InsertColumn(0, _("Information Type"), width=dialog_size(self, 140, 0).width)
        self.types.InsertColumn(1, _("Status"), width=dialog_size(self, 130, 0).width)
        self.object_types = sorted(self.frontend.sync.object_types(), key=lambda entry: _(entry[0].display_name))
        for index, (object_type, enabled) in enumerate(self.object_types):
            self.types.InsertItem(index, _(object_type.display_name))
            self.types.CheckItem(index, enabled)
        place(body, wx.StaticText, 24, 120, 221, 18, _("To find out more about and to customize what gets synchronized, click "
              "on that information type in the list and then click Settings."))
        self.type_settings = place(body, wx.Button, 255, 120, 48, 14, _("&Settings..."))
        self.type_settings.Enable(False)
        self.type_settings.Bind(wx.EVT_BUTTON, self.on_type_settings)
        self.types.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda event: self.type_settings.Enable(True))
        self.types.Bind(wx.EVT_LIST_ITEM_DESELECTED, lambda event: self.type_settings.Enable(False))
        return page

    def on_type_settings(self, event):
        from ...common.plugin_settings import show_type_settings
        index = self.types.GetFirstSelected()
        if index >= 0:
            show_type_settings(self, self.frontend.sync, self.object_types[index][0].key)

    def _build_complete(self):
        page = self._exterior(_("Setup Complete"))
        place(page, wx.StaticText, 115, 40, 199, 19, _("You are now ready to start exchanging information between your mobile "
              "device and this computer."))
        place(page, wx.StaticText, 115, 64, 199, 10, rebrand(_("Upon exiting this wizard, Microsoft ActiveSync will open and:"),
                                                                   FRONTEND_KEY))
        place(page, wx.StaticText, 121, 81, 8, 8, "*")
        place(page, wx.StaticText, 130, 81, 184, 19, _("If your device is a guest, click Explore on the toolbar and start "
              "exploring your device."))
        place(page, wx.StaticText, 121, 106, 8, 8, "*")
        place(page, wx.StaticText, 130, 106, 185, 26, _("If your device has a partnership, synchronization starts. Please wait "
              "until synchronization is complete before using your device."))
        place(page, wx.StaticText, 115, 138, 184, 11, _("Click Finish to exit this wizard."))
        return page

    @property
    def guest(self):
        return self.partnership_no.GetValue()

    def next_page(self, current):
        if current == PAGE_START and self.guest:
            return PAGE_COMPLETE
        position = 0 if current == PAGE_START else [page for page, _ in PAGE_ORDER].index(current) + 1
        for page, flag in PAGE_ORDER[position:]:
            if page == PAGE_DELETE and (self.only_this.GetValue() or not self.partners or not self.partners.full):
                continue
            if self.flags & flag:
                return page
        return None

    def show_page(self, page):
        for number, panel in self.pages.items():
            panel.Show(number == page)
        self.current = page
        if page == PAGE_DELETE:
            self.fill_existing()
        self.update_buttons()
        self.Layout()

    def update_buttons(self):
        self.back.Enable(bool(self.history))
        finishing = self.current == PAGE_COMPLETE
        self.next.SetLabel(_("Finish") if finishing else _("&Next >"))
        if self.current == PAGE_DELETE:
            self.delete.Enable(self.existing.GetSelection() != wx.NOT_FOUND)
            self.next.Enable(not self.partners.full)
        else:
            self.next.Enable(True)

    def fill_existing(self):
        self.existing.Clear()
        for partner in self.partners.partners:
            self.existing.Append(partner.desktop_name or _("Partnership {number}").format(number=partner.slot), partner.slot)

    def on_delete(self, event):
        selection = self.existing.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        slot = self.existing.GetClientData(selection)
        self.delete.Enable(False)

        def removed(partners, error):
            if not self:
                return
            if error:
                wx.MessageBox(str(error), _("Delete a Partnership"), wx.OK | wx.ICON_ERROR, self)
            else:
                self.partners = partners
            self.fill_existing()
            self.update_buttons()

        self.application.remove_device_partner(slot, removed)

    def validate_name(self):
        name = self.name.GetValue().strip()
        if not valid_device_name(name):
            wx.MessageBox(plain_newlines(format_original(_(NAME_INVALID_TEXT), name)), _(NAME_INVALID_TITLE), wx.OK | wx.ICON_EXCLAMATION, self)
            return False
        if name.lower() in {partnership.name.lower() for partnership in self.application.partnerships()}:
            wx.MessageBox(plain_newlines(_(NAME_TAKEN_TEXT)), _(NAME_TAKEN_TITLE), wx.OK | wx.ICON_EXCLAMATION, self)
            return False
        return True

    def on_back(self, event):
        if self.history:
            self.show_page(self.history.pop())

    def on_next(self, event):
        if self.current == PAGE_COMPLETE:
            self.finish()
            return
        if self.current == PAGE_NAME and not self.validate_name():
            return
        following = self.next_page(self.current)
        if following is None:
            return
        self.history.append(self.current)
        self.show_page(following)

    def chosen_types(self):
        return [object_type.key for index, (object_type, _) in enumerate(self.object_types) if self.types.IsItemChecked(index)]

    def finish(self):
        if self.finishing:
            return
        self.finishing = True
        if self.guest:
            self.chose_guest = True
            self.EndModal(wx.ID_CANCEL)
            return
        name = self.name.GetValue().strip() if self.flags & FLAG_NAME else None
        exclusive = bool(self.flags & FLAG_HAS_PARTNERSHIP) and self.only_this.GetValue()
        chosen = self.chosen_types()
        for button in (self.back, self.next, self.cancel):
            button.Enable(False)
        wx.BeginBusyCursor()

        def created(partnership, error):
            wx.EndBusyCursor()
            if not self:
                return
            if error or partnership is None:
                text = rebrand(_(FAILED_TEXT), FRONTEND_KEY)
                wx.MessageBox(f"{text}\n\n{error}" if error else text, _(FAILED_TITLE), wx.OK | wx.ICON_ERROR, self)
                self.EndModal(wx.ID_CANCEL)
                return
            options = partnership.load_options()
            options.object_types = chosen
            partnership.save_options(options)
            self.created = partnership
            self.EndModal(wx.ID_OK)

        self.application.create_partnership(created, name=name, exclusive=exclusive)


def partnership_override_held():
    return wx.GetKeyState(wx.WXK_SHIFT) and wx.GetKeyState(wx.WXK_CONTROL)


def run_partnership_wizard(parent, frontend):
    partners = frontend.application.device_partners
    if partners is not None and not partners.services_supported and not partnership_override_held():
        wx.MessageBox(rebrand(_(INCOMPATIBLE_TEXT), FRONTEND_KEY), _(TITLE), wx.OK | wx.ICON_INFORMATION, parent)
        return None
    wizard = NewPartnershipWizard(parent, frontend)
    try:
        wizard.ShowModal()
        partnership = wizard.created
        chose_guest = wizard.chose_guest
    finally:
        wizard.Destroy()
    if partnership is None and not chose_guest:
        wx.MessageBox(plain_newlines(_(GUEST_TEXT)), _(GUEST_TITLE), wx.OK | wx.ICON_INFORMATION, parent)
    return partnership
