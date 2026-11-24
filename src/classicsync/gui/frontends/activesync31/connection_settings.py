import wx

from ....i18n import N_, _
from ....link.transport import port_has_baud
from ...common.layout import dialog_size, place
from ...service import STATE_CONNECTED, STATE_CONNECTING, STATE_DISABLED

SPEEDS = [0, 19200, 38400, 57600, 115200]
SPEED_LABELS = [N_("Automatic"), "19200", "38400", "57600", "115200"]

STATUS_TEXT = {
    STATE_CONNECTED: N_("Device connected"),
    STATE_CONNECTING: N_("Connecting"),
    STATE_DISABLED: N_("Connection disabled"),
}


def available_ports():
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    ports = []
    for port in list_ports.comports():
        description = port.description if port.description and port.description != "n/a" else ""
        ports.append((port.device, description))
    from ....link.usb import attached_devices
    usb_ports = [(spec, f"{known.manufacturer} {known.description}".strip()) for spec, known in attached_devices()]
    return sorted(ports) + usb_ports


def usb_status():
    from ....link.usb import attached_devices, require_pyusb
    try:
        require_pyusb()
    except OSError:
        return _("ActiveSync USB Driver Not Installed")
    attached = attached_devices()
    return _("USB is available") + (f": {attached[0][1].description}" if attached else "")


class ConnectionSettingsDialog(wx.Dialog):
    def __init__(self, parent, application):
        super().__init__(parent, title=_("Connection Settings"))
        self.application = application
        settings = application.settings
        self.SetClientSize(dialog_size(self, 238, 252))

        icon = wx.StaticBitmap(self, bitmap=application.artwork.connection_icon(), pos=self.ConvertDialogToPixels(wx.Point(8, 10)))
        icon.SetToolTip(_("Connection"))
        place(self, wx.StaticText, 36, 9, 183, 18, _("Choose the port your mobile device's cable is connected to, then click OK."))
        place(self, wx.StaticText, 36, 35, 22, 10, _("Status:"))
        self.connection_status = place(self, wx.StaticText, 60, 35, 105, 10, "")
        get_connected = place(self, wx.Button, 168, 32, 62, 15, _("Get &Connected..."))
        get_connected.Bind(wx.EVT_BUTTON, self.on_get_connected)
        place(self, wx.StaticLine, 8, 54, 223, 1)

        self.serial_enabled = place(self, wx.CheckBox, 8, 65, 214, 10, _("Allow &serial cable or infrared connection to this COM port:"))
        self.serial_enabled.SetValue(settings.serial_enabled)
        self.ports = available_ports()
        choices = [device for device, description in self.ports]
        if settings.serial_port and settings.serial_port not in choices:
            choices.insert(0, settings.serial_port)
        self.port = place(self, wx.ComboBox, 21, 80, 150, 92, settings.serial_port, choices=choices, style=wx.CB_DROPDOWN)
        self.port.SetToolTip(_("A serial port, or tcp:HOST:PORT for an emulator's serial port"))
        self.speed = place(self, wx.Choice, 175, 80, 56, 92, choices=[_(label) for label in SPEED_LABELS])
        self.speed.SetSelection(SPEEDS.index(settings.serial_baud) if settings.serial_baud in SPEEDS else 0)
        self.speed.SetToolTip(_("Connection speed. Automatic tries 19200, 57600, 115200 and 38400 in turn."))
        place(self, wx.StaticText, 21, 98, 27, 10, _("Status:"))
        self.port_status = place(self, wx.StaticText, 50, 98, 180, 10, "")

        self.usb_enabled = place(self, wx.CheckBox, 8, 116, 216, 13, _("Allow &USB connection with this desktop computer."))
        self.usb_enabled.SetValue(settings.usb_enabled)
        place(self, wx.StaticText, 21, 130, 27, 10, _("Status:"))
        place(self, wx.StaticText, 50, 130, 155, 10, usb_status())
        network = place(self, wx.CheckBox, 8, 149, 216, 19,
                        _("Allow &network (Ethernet) and Remote Access Service (RAS) server connection with this desktop computer."))
        network.Enable(False)
        place(self, wx.StaticText, 21, 173, 27, 10, _("Status:"))
        place(self, wx.StaticText, 50, 173, 155, 10, _("Network is not available"))

        place(self, wx.StaticBox, 8, 191, 221, 30, _("Status icon"))
        self.show_icon = place(self, wx.CheckBox, 15, 204, 190, 10, _("Show status &icon in Taskbar."))
        self.show_icon.SetValue(settings.show_tray_icon)

        place(self, wx.Button, 93, 230, 52, 15, _("OK"), id=wx.ID_OK).SetDefault()
        place(self, wx.Button, 149, 230, 52, 15, _("Cancel"), id=wx.ID_CANCEL)

        self.serial_enabled.Bind(wx.EVT_CHECKBOX, self.on_serial_toggle)
        self.port.Bind(wx.EVT_TEXT, self.on_port_change)
        self.port.Bind(wx.EVT_COMBOBOX, self.on_port_change)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.on_serial_toggle(None)
        self.update_state(application.service.state)
        self.CentreOnScreen()

    def on_get_connected(self, event):
        from .get_connected import show_get_connected
        if show_get_connected(self, self.application):
            self.port.SetValue(self.application.settings.serial_port)
            self.serial_enabled.SetValue(True)
            self.on_serial_toggle(None)

    def update_state(self, state):
        self.connection_status.SetLabel(_(STATUS_TEXT.get(state, N_("Waiting for device to connect"))))

    def on_serial_toggle(self, event):
        enabled = self.serial_enabled.GetValue()
        self.port.Enable(enabled)
        self.speed.Enable(enabled and port_has_baud(self.port.GetValue()))
        self.on_port_change(None)

    def on_port_change(self, event):
        port = self.port.GetValue().strip()
        self.speed.Enable(self.serial_enabled.GetValue() and port_has_baud(port))
        if not port:
            text = _("No port selected")
        elif port.startswith("tcp:"):
            text = _("Network serial port (emulator)")
        elif port.startswith("usb"):
            attached = any(device == port for device, description in self.ports)
            text = _("USB is available") if attached else _("ActiveSync USB device not attached")
        elif any(device == port for device, description in self.ports):
            description = dict(self.ports)[port]
            text = _("COM port is available") + (f" ({description})" if description else "")
        else:
            text = _("COM port is not available")
        self.port_status.SetLabel(text)

    def on_ok(self, event):
        settings = self.application.settings
        changed = (settings.serial_enabled != self.serial_enabled.GetValue() or settings.serial_port != self.port.GetValue().strip()
                   or settings.serial_baud != SPEEDS[self.speed.GetSelection()] or settings.usb_enabled != self.usb_enabled.GetValue())
        settings.usb_enabled = self.usb_enabled.GetValue()
        settings.serial_enabled = self.serial_enabled.GetValue()
        settings.serial_port = self.port.GetValue().strip()
        settings.serial_baud = SPEEDS[self.speed.GetSelection()]
        settings.show_tray_icon = self.show_icon.GetValue()
        settings.save()
        self.application.application.apply_settings(changed)
        self.EndModal(wx.ID_OK)
