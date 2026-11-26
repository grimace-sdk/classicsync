import wx
import wx.adv

from ....i18n import N_, _, format_original
from ...branding import PRODUCT_NAME
from ...service import STATE_CONNECTED, STATE_CONNECTING, STATE_DISABLED

MENU_ID_OFFSET = 30000
ID_OPEN_MOBILE_DEVICES = 40010 - MENU_ID_OFFSET
ID_COMMUNICATIONS = 40014 - MENU_ID_OFFSET
ID_SYNCHRONIZE_NOW = 42102 - MENU_ID_OFFSET
ID_ACTIVESYNC_OPTIONS = 42103 - MENU_ID_OFFSET
ID_ACTIVESYNC_STATUS = 42104 - MENU_ID_OFFSET
ID_ENABLE_SERIAL = 42107 - MENU_ID_OFFSET
ID_ENABLE_NETWORK = 42108 - MENU_ID_OFFSET
ID_GET_CONNECTED = 42200 - MENU_ID_OFFSET

WAITING_TOOLTIP = N_("Waiting for device to connect")
DISABLED_TOOLTIP = N_("Connection disabled")


def icon_state(state):
    return {STATE_CONNECTED: "connected", STATE_CONNECTING: "connecting", STATE_DISABLED: "disabled"}.get(state, "waiting")


class TrayIcon(wx.adv.TaskBarIcon):
    def __init__(self, frontend):
        super().__init__()
        self.frontend = frontend
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, lambda event: self.open_default())
        self.Bind(wx.EVT_MENU, self.on_command)

    def update_state(self, state):
        if state == STATE_CONNECTED:
            status = self.frontend.device_sync_status()
            name = self.frontend.connected_name()
            if status != _("Guest"):
                tooltip = format_original(_("%s Connected, %s"), name, status)
            else:
                tooltip = format_original(_("%s Connected"), name)
        elif state == STATE_DISABLED:
            tooltip = _(DISABLED_TOOLTIP)
        else:
            tooltip = _(WAITING_TOOLTIP)
        self.SetIcon(self.frontend.artwork.tray_icon(icon_state(state)), tooltip)

    def open_default(self):
        if self.frontend.version_one_connected():
            self.frontend.open_version_one()
        else:
            self.frontend.show_main_window()

    def CreatePopupMenu(self):
        settings = self.frontend.settings
        menu = wx.Menu()
        if self.frontend.version_one_connected():
            menu.Append(ID_OPEN_MOBILE_DEVICES, _("&H/PC Explorer")).Enable(self.frontend.version_one_available())
            menu.AppendSeparator()
            menu.Append(ID_COMMUNICATIONS, _("&Communications..."))
        else:
            connected = self.frontend.service.state == STATE_CONNECTED
            menu.Append(ID_OPEN_MOBILE_DEVICES, _("&Open Mobile Devices"))
            menu.AppendSeparator()
            if connected:
                menu.Append(ID_SYNCHRONIZE_NOW, _("Synchronize &Now")).Enable(self.frontend.can_synchronize())
            menu.Append(ID_ACTIVESYNC_STATUS, _("ActiveSync &Status..."))
            if connected:
                menu.Append(ID_ACTIVESYNC_OPTIONS, _("&ActiveSync Options..."))
            menu.AppendSeparator()
            menu.Append(ID_COMMUNICATIONS, _("&Communications..."))
            menu.AppendCheckItem(ID_ENABLE_SERIAL, _("&Enable Serial Connection")).Check(settings.serial_enabled)
            menu.AppendCheckItem(ID_ENABLE_NETWORK, _("Ena&ble Network Connection")).Check(settings.network_enabled)
        menu.AppendSeparator()
        menu.Append(ID_GET_CONNECTED, _("&Get Connected..."))
        menu.Append(wx.ID_PREFERENCES, _("{product} &Settings...").format(product=PRODUCT_NAME))
        menu.Append(wx.ID_EXIT, _("E&xit"))
        return menu

    def on_command(self, event):
        identifier = event.GetId()
        if identifier == ID_OPEN_MOBILE_DEVICES:
            self.open_default()
        elif identifier == ID_ACTIVESYNC_STATUS:
            self.frontend.show_sync_status()
        elif identifier == ID_SYNCHRONIZE_NOW:
            self.frontend.synchronize_now()
        elif identifier == ID_ACTIVESYNC_OPTIONS:
            self.frontend.show_activesync_options(None)
        elif identifier == ID_COMMUNICATIONS:
            self.frontend.show_connection_settings(None)
        elif identifier == ID_ENABLE_SERIAL:
            self.frontend.toggle_serial_connection()
        elif identifier == ID_ENABLE_NETWORK:
            self.frontend.toggle_network_connection()
        elif identifier == ID_GET_CONNECTED:
            self.frontend.show_get_connected(None)
        elif identifier == wx.ID_PREFERENCES:
            self.frontend.show_preferences(None)
        elif identifier == wx.ID_EXIT:
            self.frontend.quit()
