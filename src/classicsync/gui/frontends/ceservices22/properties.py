import wx

from ....i18n import N_, _, format_original
from ....link.transport import port_has_baud
from ...branding import title
from ...common.layout import dialog_size, place
from ...service import STATE_CONNECTED, STATE_CONNECTING, STATE_DISABLED
from ..activesync31.connection_settings import available_ports
from .sheet import lay_out_property_sheet
from .tray import icon_state

TITLE = title("ceservices22")

SPEEDS = [0, 19200, 38400, 57600, 115200]
SPEED_LABELS = [N_("Automatic"), "19200", "38400", "57600", "115200"]

CONNECTION_STATUS = {
    STATE_CONNECTED: N_("Device connected"),
    STATE_CONNECTING: N_("Establishing connection to device..."),
    STATE_DISABLED: N_("Connection disabled"),
}
WAITING_STATUS = N_("Waiting for connection")
SERIAL_READY = N_("Serial port is ready")
SERIAL_UNAVAILABLE = N_("Port resources are not available")
SERIAL_DISABLED = N_("Connection disabled")
NETWORK_DISABLED = N_("Network connections are disabled")
NETWORK_READY = N_("Network communication is ready")
NETWORK_UNAVAILABLE = N_("Network resources are not available")

PAGE_WIDTH = 238
PAGE_HEIGHT = 226


class AutoConnectDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Auto Connect Options"))
        self.SetClientSize(dialog_size(self, 290, 167))
        place(self, wx.StaticText, 10, 10, 270, 27,
              _("Auto Connect establishes communications with your device when you connect the serial cable. You can enable Auto "
                "Connect at all times or only while a Mobile Devices window is open."))
        place(self, wx.StaticText, 10, 40, 270, 18,
              _("While Auto Connect is enabled, your COM port cannot be used for another purpose (such as an external modem or "
                "digital camera)."))
        place(self, wx.StaticText, 10, 63, 270, 10, _("When would you like Auto Connect enabled?"))
        always = place(self, wx.RadioButton, 10, 77, 264, 18,
                       _("&At all times (I plan to use my COM port only for connecting to my mobile device)."), style=wx.RB_GROUP)
        always.SetValue(True)
        window_only = place(self, wx.RadioButton, 10, 97, 267, 18,
                            _("&Only while the Mobile Devices window is open (I may need to use my COM port for another purpose)."))
        window_only.Enable(False)
        place(self, wx.Button, 160, 141, 50, 14, _("OK"), id=wx.ID_OK).SetDefault()
        place(self, wx.Button, 220, 141, 50, 14, _("Cancel"), id=wx.ID_CANCEL)
        self.CentreOnParent()


class CommunicationsPage(wx.Panel):
    def __init__(self, parent, frontend):
        super().__init__(parent)
        self.frontend = frontend
        settings = frontend.settings
        self.SetMinSize(dialog_size(self, PAGE_WIDTH, PAGE_HEIGHT))
        self.status_icon = wx.StaticBitmap(self, bitmap=frontend.artwork.status_bitmap("waiting"),
                                           pos=self.ConvertDialogToPixels(wx.Point(15, 10)))
        self.status = place(self, wx.StaticText, 52, 15, 150, 8, _("Status"))
        self.connection_enabled = place(self, wx.CheckBox, 15, 42, 202, 10, _("&Enable mobile device connection"))
        self.connection_enabled.SetValue(settings.serial_enabled or settings.network_enabled)

        place(self, wx.StaticBox, 10, 60, 220, 90, _("Device Connections via Serial Port"))
        self.serial_enabled = place(self, wx.CheckBox, 15, 76, 55, 10, _("E&nabled"))
        self.serial_enabled.SetValue(settings.serial_enabled)
        self.auto_connect = place(self, wx.Button, 145, 76, 80, 14, _("Auto &Connect..."))
        place(self, wx.StaticText, 15, 95, 36, 10, _("Status:"), style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
        self.serial_status = place(self, wx.StaticText, 60, 95, 145, 10, "")
        place(self, wx.StaticText, 15, 110, 40, 8, _("&Port:"), style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
        self.ports = available_ports()
        choices = [device for device, _ in self.ports]
        if settings.serial_port and settings.serial_port not in choices:
            choices.insert(0, settings.serial_port)
        self.port = place(self, wx.ComboBox, 60, 108, 165, 92, settings.serial_port, choices=choices, style=wx.CB_DROPDOWN)
        self.port.SetToolTip(_("A serial port, or tcp:HOST:PORT for an emulator's serial port"))
        place(self, wx.StaticText, 15, 131, 40, 8, _("Baud Rate:"), style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
        self.speed = place(self, wx.Choice, 60, 129, 80, 92, choices=[_(label) for label in SPEED_LABELS])
        self.speed.SetSelection(SPEEDS.index(settings.serial_baud) if settings.serial_baud in SPEEDS else 0)
        self.speed.SetToolTip(_("Connection speed. Make sure your mobile device is set to communicate at the same baud rate. "
                                "Automatic tries 19200, 57600, 115200 and 38400 in turn."))
        place(self, wx.Button, 145, 129, 80, 14, _("&Install New Port")).Enable(False)

        place(self, wx.StaticBox, 10, 158, 220, 55, _("Device Connections via Network"))
        self.network_enabled = place(self, wx.CheckBox, 15, 174, 55, 10, _("Ena&bled"))
        self.network_enabled.SetValue(settings.network_enabled)
        place(self, wx.StaticText, 15, 192, 36, 10, _("Status:"), style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
        self.network_status = place(self, wx.StaticText, 55, 192, 155, 10, "")

        self.connection_enabled.Bind(wx.EVT_CHECKBOX, self.on_toggle)
        self.serial_enabled.Bind(wx.EVT_CHECKBOX, self.on_toggle)
        self.network_enabled.Bind(wx.EVT_CHECKBOX, self.on_toggle)
        self.port.Bind(wx.EVT_TEXT, self.on_toggle)
        self.port.Bind(wx.EVT_COMBOBOX, self.on_toggle)
        self.auto_connect.Bind(wx.EVT_BUTTON, self.on_auto_connect)
        self.on_toggle(None)
        self.update_state(frontend.service.state)

    def update_state(self, state):
        self.status.SetLabel(_(CONNECTION_STATUS.get(state, WAITING_STATUS)))
        self.status_icon.SetBitmap(self.frontend.artwork.status_bitmap(icon_state(state)))

    def serial_wanted(self):
        return self.connection_enabled.GetValue() and self.serial_enabled.GetValue()

    def network_wanted(self):
        return self.connection_enabled.GetValue() and self.network_enabled.GetValue()

    def on_toggle(self, event):
        master = self.connection_enabled.GetValue()
        serial = self.serial_wanted()
        self.serial_enabled.Enable(master)
        self.network_enabled.Enable(master)
        if not self.network_wanted():
            network_text = NETWORK_DISABLED
        elif self.frontend.service.network_available is False:
            network_text = NETWORK_UNAVAILABLE
        else:
            network_text = NETWORK_READY
        self.network_status.SetLabel(_(network_text))
        for control in (self.auto_connect, self.port):
            control.Enable(serial)
        port = self.port.GetValue().strip()
        self.speed.Enable(serial and port_has_baud(port))
        if not serial:
            text = SERIAL_DISABLED
        elif port.startswith("tcp:") or any(device == port for device, _ in self.ports):
            text = SERIAL_READY
        else:
            text = SERIAL_UNAVAILABLE
        self.serial_status.SetLabel(_(text))

    def on_auto_connect(self, event):
        with AutoConnectDialog(self) as dialog:
            dialog.ShowModal()

    def apply(self, settings):
        baud = SPEEDS[self.speed.GetSelection()]
        port = self.port.GetValue().strip()
        changed = (settings.serial_enabled != self.serial_wanted() or settings.serial_port != port or settings.serial_baud != baud
                   or settings.network_enabled != self.network_wanted())
        settings.serial_enabled = self.serial_wanted()
        settings.network_enabled = self.network_wanted()
        settings.serial_port = port
        settings.serial_baud = baud
        return changed


class PreferencesPage(wx.Panel):
    def __init__(self, parent, frontend):
        super().__init__(parent)
        settings = frontend.settings
        self.SetMinSize(dialog_size(self, PAGE_WIDTH, PAGE_HEIGHT))
        place(self, wx.StaticBox, 10, 15, 220, 40, _("Tray Icon"))
        self.show_icon = place(self, wx.CheckBox, 15, 30, 206, 10, _("&Display the tray icon in the taskbar"))
        self.show_icon.SetValue(settings.show_tray_icon)
        place(self, wx.StaticBox, 10, 65, 220, 40, _("Explorer Window"))
        self.open_on_connect = place(self, wx.CheckBox, 15, 80, 206, 10, _("&Open Explorer window upon connection"))
        self.open_on_connect.SetValue(settings.open_on_connect)

    def apply(self, settings):
        settings.show_tray_icon = self.show_icon.GetValue()
        settings.open_on_connect = self.open_on_connect.GetValue()
        return False


class PropertiesSheet(wx.Dialog):
    def __init__(self, parent, frontend):
        super().__init__(parent, title=format_original(_("%s Properties"), TITLE))
        self.frontend = frontend
        self.SetIcons(frontend.artwork.application_icons())
        self.notebook = wx.Notebook(self)
        self.communications = CommunicationsPage(self.notebook, frontend)
        self.preferences = PreferencesPage(self.notebook, frontend)
        self.notebook.AddPage(self.communications, _("Communications"))
        self.notebook.AddPage(self.preferences, _("Preferences"))
        lay_out_property_sheet(self, self.notebook)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.Bind(wx.EVT_BUTTON, self.on_apply, id=wx.ID_APPLY)
        self.CentreOnScreen()

    def select_page(self, index):
        self.notebook.SetSelection(index)

    def update_state(self, state):
        self.communications.update_state(state)

    def apply(self):
        settings = self.frontend.settings
        restart_needed = self.communications.apply(settings)
        self.preferences.apply(settings)
        settings.save()
        self.frontend.application.apply_settings(restart_needed)
        if restart_needed:
            self.frontend.apply_tray_setting()

    def on_apply(self, event):
        self.apply()

    def on_ok(self, event):
        self.apply()
        self.EndModal(wx.ID_OK)
