import wx

from ....i18n import N_, _
from ...common.layout import place
from ...service import STATE_CONNECTED, STATE_CONNECTING, STATE_DISABLED, STATE_WAITING
from ..activesync31.connection_settings import available_ports
from .sheet import PropertySheet

SPEEDS = [0, 19200, 38400, 57600, 115200]
SPEED_LABELS = [N_("Automatic"), "19200", "38400", "57600", "115200"]

STATUS_TEXT = {
    STATE_CONNECTED: N_("Connected to H/PC"),
    STATE_CONNECTING: N_("Establishing connection to H/PC..."),
    STATE_WAITING: N_("Waiting for connection"),
}

ICON_STATES = {STATE_CONNECTED: "connected", STATE_CONNECTING: "connecting", STATE_WAITING: "waiting"}


def status_text(state, port):
    if state == STATE_DISABLED:
        return _("Communications disabled") if port else _("No port selected")
    return _(STATUS_TEXT[state]) if state in STATUS_TEXT else ""


class CommunicationsSheet(PropertySheet):
    def __init__(self, parent, frontend):
        super().__init__(parent, _("Communications Properties"))
        self.frontend = frontend
        settings = frontend.settings
        page = self.add_page(_("Communications"), 225, 217)
        self.page = page
        place(page, wx.StaticText, 7, 7, 211, 24,
              _("The H/PC is automatically connected when attached to your desktop computer. Upon connection, automatic "
                "operations (such as Synchronization and Backup) may proceed. "))
        place(page, wx.StaticBox, 7, 37, 211, 58, _("Communications Port"))
        place(page, wx.StaticText, 17, 51, 194, 21,
              _("Select the communications port that you have used to attach your H/PC to the desktop computer:"))
        place(page, wx.StaticText, 21, 76, 28, 8, _("&Port:"), style=wx.ALIGN_RIGHT | wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
        self.ports = available_ports()
        choices = [device for device, description in self.ports]
        if settings.serial_port and settings.serial_port not in choices:
            choices.insert(0, settings.serial_port)
        self.port = place(page, wx.ComboBox, 61, 74, 96, 92, settings.serial_port, choices=choices, style=wx.CB_DROPDOWN)
        self.port.SetToolTip(_("A serial port, or tcp:HOST:PORT for an emulator's serial port"))
        self.speed = place(page, wx.Choice, 161, 74, 50, 92, choices=[_(label) for label in SPEED_LABELS])
        self.speed.SetSelection(SPEEDS.index(settings.serial_baud) if settings.serial_baud in SPEEDS else 0)
        self.speed.SetToolTip(_("Connection speed. H/PC Explorer used 19200. Automatic tries 19200, 57600, 115200 and 38400 in turn."))
        place(page, wx.StaticBox, 7, 101, 211, 41, _("Current Status"))
        self.status_icon = wx.StaticBitmap(page, bitmap=frontend.artwork.state_bitmap("waiting"),
                                           pos=page.ConvertDialogToPixels(wx.Point(30, 115)))
        self.status = place(page, wx.StaticText, 61, 121, 150, 8, "", style=wx.ST_NO_AUTORESIZE)
        place(page, wx.StaticText, 7, 156, 211, 54,
              _("Note:  While waiting to connect, or connected, the selected port is not available for other applications "
                "and devices.\n\nTo free the port, switch to another or close all applications that require communications "
                "with your H/PC."))
        self.port.Bind(wx.EVT_TEXT, self.on_port_change)
        self.port.Bind(wx.EVT_COMBOBOX, self.on_port_change)
        self.speed.Bind(wx.EVT_CHOICE, self.changed)
        self.update_state(frontend.service.state)
        self.on_port_change(None, mark_changed=False)
        self.finish()

    def update_state(self, state):
        self.status.SetLabel(status_text(state, self.frontend.settings.serial_port))
        icon_state = ICON_STATES.get(state, "disabled")
        self.status_icon.SetBitmap(self.frontend.artwork.state_bitmap(icon_state))

    def on_port_change(self, event, mark_changed=True):
        self.speed.Enable(not self.port.GetValue().strip().startswith("tcp:"))
        if mark_changed:
            self.changed()

    def apply(self):
        settings = self.frontend.settings
        port = self.port.GetValue().strip()
        speed = SPEEDS[self.speed.GetSelection()]
        changed = settings.serial_port != port or settings.serial_baud != speed or not settings.serial_enabled
        restart = changed or self.frontend.service.state == STATE_DISABLED
        settings.serial_enabled = True
        settings.serial_port = port
        settings.serial_baud = speed
        settings.save()
        self.frontend.application.apply_settings(restart)
