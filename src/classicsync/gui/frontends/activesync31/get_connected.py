import wx

from ....connection.scanner import AUTOBAUD_SPEEDS, STATUS_CHECKING, STATUS_FOUND, STATUS_LOOKING, STATUS_NOT_AVAILABLE, scan_ports
from ....i18n import N_, _, format_original
from ...branding import identity
from ...common.animation import AnimationPlayer, load_clip
from ...common.layout import bold, dialog_size, place
from .artwork import AGENT
from .connection_settings import available_ports

FRONTEND_KEY = "activesync31"
PAGE_WIDTH = 331
EXTERIOR_HEIGHT = 194
HEADER_HEIGHT = 36
INTERIOR_HEIGHT = 143
LISTEN_SECONDS = 6.0

IGNORED_PORT_WORDS = ("bluetooth", "debug-console", "wlan-debug")

STATUS_TEXT = {
    STATUS_CHECKING: N_("Available, looking for device..."),
    STATUS_LOOKING: N_("Available, looking for device..."),
    STATUS_NOT_AVAILABLE: N_("Not Available"),
    STATUS_FOUND: N_("Device found, establishing connection..."),
}


def candidate_ports(settings):
    ports = [device for device, _ in available_ports() if not any(word in device.lower() for word in IGNORED_PORT_WORDS)]
    if settings.serial_port.startswith("tcp:"):
        ports.insert(0, settings.serial_port)
    elif settings.serial_port in ports:
        ports.remove(settings.serial_port)
        ports.insert(0, settings.serial_port)
    return ports


class GetConnectedWizard(wx.Dialog):
    def __init__(self, parent, frontend):
        super().__init__(parent, title=_("Get Connected"))
        self.frontend = frontend
        self.service = frontend.service
        self.settings = frontend.settings
        self.scan_future = None
        self.port_results = {}
        self.found = None
        self.SetClientSize(dialog_size(self, PAGE_WIDTH, EXTERIOR_HEIGHT + 26))
        self.pages = [self._build_welcome(), self._build_progress(), self._build_result()]
        place(self, wx.StaticLine, 0, EXTERIOR_HEIGHT, PAGE_WIDTH, 1)
        self.back = place(self, wx.Button, 147, EXTERIOR_HEIGHT + 7, 50, 14, _("< &Back"))
        self.next = place(self, wx.Button, 197, EXTERIOR_HEIGHT + 7, 50, 14, _("&Next >"))
        self.cancel = place(self, wx.Button, 254, EXTERIOR_HEIGHT + 7, 50, 14, _("Cancel"), id=wx.ID_CANCEL)
        self.back.Bind(wx.EVT_BUTTON, lambda event: self.show_page(0))
        self.next.Bind(wx.EVT_BUTTON, self.on_next)
        self.Bind(wx.EVT_BUTTON, self.on_cancel, id=wx.ID_CANCEL)
        self.Bind(wx.EVT_CLOSE, self.on_cancel)
        self.show_page(0)
        self.CentreOnScreen()

    def _page(self, interior, title="", subtitle=""):
        page = wx.Panel(self, pos=(0, 0), size=dialog_size(self, PAGE_WIDTH, EXTERIOR_HEIGHT))
        if interior:
            header = wx.Panel(page, pos=(0, 0), size=dialog_size(self, PAGE_WIDTH, HEADER_HEIGHT))
            header.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))
            bold(place(header, wx.StaticText, 15, 7, 290, 9, title))
            place(header, wx.StaticText, 25, 18, 280, 9, subtitle)
            place(page, wx.StaticLine, 0, HEADER_HEIGHT, PAGE_WIDTH, 1)
            body = wx.Panel(page, pos=page.ConvertDialogToPixels(wx.Point(0, HEADER_HEIGHT + 1)),
                            size=dialog_size(self, PAGE_WIDTH, INTERIOR_HEIGHT))
            return page, body
        return page, page

    def _build_welcome(self):
        page, body = self._page(False)
        bitmap = self.frontend.artwork.bitmap(AGENT, "bitmap_165.bmp", transparent=False)
        if bitmap.IsOk():
            image = bitmap.ConvertToImage().Scale(*dialog_size(self, 111, EXTERIOR_HEIGHT), wx.IMAGE_QUALITY_HIGH)
            wx.StaticBitmap(body, bitmap=wx.Bitmap(image), pos=(0, 0))
        else:
            stripe = place(body, wx.Panel, 0, 0, 111, EXTERIOR_HEIGHT)
            stripe.SetBackgroundColour(wx.Colour(0, 51, 153))
        bold(place(body, wx.StaticText, 120, 6, 184, 11, _("Get Connected")), 1.3)
        place(body, wx.StaticText, 120, 35, 188, 20, _("After installing batteries or plugging in the AC adapter, do one of the following:"))
        place(body, wx.StaticText, 120, 68, 196, 20, _("* Use the serial cable to connect to a serial port of this desktop computer and click Next."))
        place(body, wx.StaticText, 120, 97, 196, 28, _("* Use a USB cradle that appears as a serial port, choose it in Connection Settings, and click Next."))
        place(body, wx.StaticText, 120, 151, 196, 17, _("You can also connect your mobile device using infrared (IR) through an IR serial port."))
        return page

    def _build_progress(self):
        page, body = self._page(True, _("Checking COM Ports"),
                                _("Please wait while {product} locates your mobile device.").format(product=identity(FRONTEND_KEY)))
        position, size = body.ConvertDialogToPixels(wx.Point(7, 8)), dialog_size(self, 313, 66)
        self.animation = AnimationPlayer(body, load_clip(self.frontend.artwork, AGENT, 164), position, size)
        place(body, wx.StaticBox, 16, 82, 295, 47, _("Progress"))
        self.progress_text = place(body, wx.StaticText, 30, 96, 241, 24, _("Looking for a mobile device..."), style=wx.ST_NO_AUTORESIZE)
        return page

    def _build_result(self):
        page, body = self._page(True, _("Your device was not detected"), _("Verify that the connection you are using is available."))
        place(body, wx.StaticText, 17, 3, 284, 14, _("Verify that the connection you are using is available."))
        self.result_list = place(body, wx.ListCtrl, 17, 21, 300, 77, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.result_list.InsertColumn(0, _("Port"), width=dialog_size(self, 150, 0).width)
        self.result_list.InsertColumn(1, _("Status"), width=dialog_size(self, 140, 0).width)
        self.result_text = place(body, wx.StaticText, 17, 104, 300, 38, "")
        return page

    def show_page(self, index):
        for number, page in enumerate(self.pages):
            page.Show(number == index)
        self.page_index = index
        self.back.Show(index == 2)
        self.next.SetLabel(_("&Retry") if index == 2 else _("&Next >"))
        self.next.Enable(index != 1)
        if index == 1:
            self.animation.play()
        else:
            self.animation.stop()
        self.Layout()

    def on_next(self, event):
        if self.page_index in (0, 2):
            self.start_scan()

    def start_scan(self):
        ports = candidate_ports(self.settings)
        self.port_results = {port: N_("Not installed") for port in ports}
        self.show_page(1)
        if not ports:
            self.show_result(_("Unable to connect.  No comm ports are available.  Please confirm your computer configuration.  "
                               "Press Cancel to continue."))
            return
        speeds = [self.settings.serial_baud] if self.settings.serial_baud else list(AUTOBAUD_SPEEDS)
        self.progress_text.SetLabel(_("Looking for a mobile device..."))

        def report(port, baud, status):
            wx.CallAfter(self._report, port, baud, status)

        def run():
            if not self or not self.IsModal() or self.page_index != 1:
                return
            self.scan_future = self.service.submit(scan_ports(ports, speeds, report, LISTEN_SECONDS))
            self.scan_future.add_done_callback(lambda future: wx.CallAfter(self._scan_finished, future))

        self.service.suspend(_("Looking for a mobile device...")).add_done_callback(lambda future: wx.CallAfter(run))

    def _report(self, port, baud, status):
        if not self:
            return
        if status == STATUS_NOT_AVAILABLE:
            self.port_results[port] = N_("Not available")
        elif status in (STATUS_CHECKING, STATUS_LOOKING, STATUS_FOUND):
            self.port_results[port] = N_("Available")
        status_text = _(STATUS_TEXT[status]) if status in STATUS_TEXT else status
        lines = [_("Looking for a mobile device..."), "    " + _("Now Checking: ") + port,
                 "    " + _("\r\nStatus: ").lstrip("\r\n") + status_text]
        if baud:
            lines.append("    " + format_original(_("\r\nBaud Rate: %d"), baud).lstrip("\r\n"))
        self.progress_text.SetLabel("\n".join(lines))
        self.progress_text.Wrap(dialog_size(self, 260, 0).width)

    def _scan_finished(self, future):
        if not self:
            return
        self.scan_future = None
        if future.cancelled():
            return
        error = future.exception()
        result = None if error else future.result()
        if result:
            self.settings.serial_port = result.port
            self.settings.serial_enabled = True
            if not result.port.startswith("tcp:"):
                self.settings.last_baud = result.baud
            self.settings.save()
            self.service.restart()
            self.EndModal(wx.ID_OK)
            return
        self.show_result(_("Unable to connect.  Please confirm that your serial cable is properly connected and then press Retry.  "
                           "Press Cancel to manually select the port."))

    def show_result(self, text):
        self.result_list.DeleteAllItems()
        for index, (port, status) in enumerate(sorted(self.port_results.items())):
            self.result_list.InsertItem(index, port)
            self.result_list.SetItem(index, 1, _(status))
        self.result_text.SetLabel(text)
        self.result_text.Wrap(dialog_size(self, 300, 0).width)
        self.show_page(2)

    def on_cancel(self, event):
        if self.scan_future:
            self.scan_future.cancel()
            self.scan_future = None
        self.service.restart()
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Destroy()


def show_get_connected(parent, frontend):
    wizard = GetConnectedWizard(parent, frontend)
    try:
        return wizard.ShowModal() == wx.ID_OK
    finally:
        wizard.Destroy()
