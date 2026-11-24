import concurrent.futures

import wx

from ....connection.scanner import (
    STATUS_CHECKING, STATUS_FOUND, STATUS_LOOKING, STATUS_NOT_AVAILABLE, STATUS_NOT_FOUND, scan_ports,
)
from ....i18n import N_, _, format_original, plain_newlines
from ...branding import rebrand
from ...common.animation import AnimationPlayer
from ...common.layout import dialog_rect, dialog_size, place
from ..activesync31.connection_settings import available_ports
from .artwork import CABLE_ANIMATION, CHECK_PORT, SEARCH_ANIMATION

INSTRUCTIONS = N_("Turn on and connect your mobile device to the desktop computer using the serial cable.  Then click Start and "
                  "Windows CE Services will automatically connect to your device.")
UNABLE_TO_CONNECT = N_("Unable to connect.  Please confirm that your serial cable is properly connected and then press Retry.  "
                       "Press Cancel to manually select the port.")
STATUS_TEXT = {
    STATUS_CHECKING: N_("Available, looking for device..."),
    STATUS_LOOKING: N_("Available, looking for device..."),
    STATUS_NOT_AVAILABLE: N_("Not Available"),
    STATUS_FOUND: N_("Device found, establishing connection..."),
}
ORIGINAL_BAUD = "19200"
FRONTEND_KEY = "ceservices22"
DEFAULT_BAUD = 19200
CLOSE_DELAY_MS = 1500


class GetConnectedDialog(wx.Dialog):
    def __init__(self, parent, frontend):
        super().__init__(parent, title=_("Get Connected"))
        self.frontend = frontend
        self.retries = 0
        self.scan = None
        self.finished = False
        self.SetClientSize(dialog_size(self, 261, 135))
        position, size = dialog_rect(self, 0, 0, 261, 66)
        artwork = frontend.artwork
        self.cable_animation = AnimationPlayer(self, artwork.animation(CHECK_PORT, CABLE_ANIMATION), position, size)
        self.search_animation = AnimationPlayer(self, artwork.animation(CHECK_PORT, SEARCH_ANIMATION), position, size)
        self.search_animation.Hide()
        if not self.cable_animation.bitmaps:
            placeholder = wx.ArtProvider.GetBitmap(wx.ART_HARDDISK, wx.ART_MESSAGE_BOX, wx.Size(48, 48))
            self.cable_animation.Hide()
            wx.StaticBitmap(self, bitmap=placeholder, pos=wx.Point(position.x + (size.width - 48) // 2, position.y + (size.height - 48) // 2))
        self.message = place(self, wx.StaticText, 21, 73, 219, 32, rebrand(_(INSTRUCTIONS), FRONTEND_KEY), style=wx.ST_NO_AUTORESIZE)
        self.start = place(self, wx.Button, 72, 114, 50, 14, _("&Start"))
        self.start.SetDefault()
        place(self, wx.Button, 138, 114, 50, 14, _("Cancel"), id=wx.ID_CANCEL)
        self.start.Bind(wx.EVT_BUTTON, self.on_start)
        self.Bind(wx.EVT_BUTTON, self.on_cancel, id=wx.ID_CANCEL)
        self.Bind(wx.EVT_CLOSE, self.on_cancel)
        self.cable_animation.play()
        self.CentreOnScreen()

    def set_message(self, text):
        self.message.SetLabel(text)
        self.message.Wrap(self.message.GetSize().width)

    def candidate_ports(self):
        configured = self.frontend.settings.serial_port
        ports = [configured] if configured else []
        ports += [device for device, _ in available_ports() if device != configured]
        return ports

    def on_start(self, event):
        ports = self.candidate_ports()
        if not ports:
            self.set_message(_("Not Valid"))
            return
        self.start.Enable(False)
        self.cable_animation.stop()
        self.cable_animation.Hide()
        self.search_animation.Show()
        self.search_animation.play()
        self.set_message(" ")
        service = self.frontend.service
        baud = self.frontend.settings.serial_baud
        speeds = [baud] if baud else None

        def report(port, speed, status):
            wx.CallAfter(self.show_progress, port, speed, status)

        def suspended():
            if not self or self.finished:
                return
            self.scan = service.submit(scan_ports(ports, speeds, report))
            self.scan.add_done_callback(lambda scan: wx.CallAfter(self.scan_finished, scan))

        service.suspend("Get Connected").add_done_callback(lambda future: wx.CallAfter(suspended))

    def show_progress(self, port, speed, status):
        if not self or self.finished or status == STATUS_NOT_FOUND:
            return
        checking = _("Now Checking: ") + port
        if self.retries:
            checking += " " + format_original(_("(Retry %d)"), self.retries)
        text = checking + _("\r\nStatus: ") + (_(STATUS_TEXT[status]) if status in STATUS_TEXT else " ")
        if not port.startswith("tcp:"):
            text += _("\r\nBaud Rate: 19200").replace(ORIGINAL_BAUD, str(speed or DEFAULT_BAUD))
        self.set_message(plain_newlines(text))

    def scan_finished(self, scan):
        if not self or self.finished:
            return
        self.scan = None
        try:
            result = scan.result()
        except (concurrent.futures.CancelledError, Exception):
            result = None
        settings = self.frontend.settings
        if result:
            settings.serial_enabled = True
            settings.serial_port = result.port
            if not result.port.startswith("tcp:"):
                settings.last_baud = result.baud
            settings.save()
            self.frontend.service.restart()
            self.finished = True
            wx.CallLater(CLOSE_DELAY_MS, self.close_found)
            return
        self.frontend.service.restart()
        self.retries += 1
        self.search_animation.stop()
        self.set_message(_(UNABLE_TO_CONNECT))
        self.start.SetLabel(_("&Retry"))
        self.start.Enable(True)

    def close_found(self):
        if self and self.IsModal():
            self.EndModal(wx.ID_OK)

    def on_cancel(self, event):
        if self.finished:
            return
        self.finished = True
        if self.scan:
            self.scan.cancel()
            self.scan = None
            self.frontend.service.restart()
        elif not self.start.IsEnabled():
            self.frontend.service.restart()
        self.search_animation.stop()
        self.cable_animation.stop()
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Destroy()
