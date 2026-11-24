import wx
import wx.adv

from ....i18n import N_, _
from ...branding import PRODUCT_NAME
from ...service import STATE_CONNECTED, STATE_CONNECTING, STATE_DISABLED

ID_EXPLORER = 40010 - 30000
ID_PROPERTIES = 40014 - 30000
ID_CLOSE = 40009 - 30000
ID_SETTINGS = wx.NewIdRef()
ID_EXIT = wx.NewIdRef()

TOOLTIPS = {
    STATE_CONNECTED: N_("Connected to H/PC"),
    STATE_CONNECTING: N_("Establishing connection to H/PC..."),
    STATE_DISABLED: N_("Communications closed"),
}

ICON_STATES = {STATE_CONNECTED: "connected", STATE_CONNECTING: "connecting", STATE_DISABLED: "disabled"}


class TrayIcon(wx.adv.TaskBarIcon):
    def __init__(self, frontend):
        super().__init__()
        self.frontend = frontend
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, lambda event: frontend.show_main_window())
        self.Bind(wx.EVT_MENU, self.on_command)

    def update_state(self, state):
        icon = self.frontend.artwork.state_icon(ICON_STATES.get(state, "waiting"), 16)
        self.SetIcon(icon, _(TOOLTIPS.get(state, N_("Waiting to connect to H/PC..."))))

    def CreatePopupMenu(self):
        menu = wx.Menu()
        menu.Append(ID_EXPLORER, _("&H/PC Explorer"), _("Opens H/PC Explorer"))
        menu.AppendSeparator()
        menu.Append(ID_PROPERTIES, _("P&roperties"))
        menu.Append(ID_CLOSE, _("Close")).Enable(self.frontend.service.state != STATE_DISABLED)
        menu.AppendSeparator()
        menu.Append(ID_SETTINGS, _("{product} &Settings...").format(product=PRODUCT_NAME))
        menu.Append(ID_EXIT, _("E&xit"))
        return menu

    def on_command(self, event):
        identifier = event.GetId()
        if identifier == ID_EXPLORER:
            self.frontend.show_main_window()
        elif identifier == ID_PROPERTIES:
            self.frontend.show_connection_settings(None)
        elif identifier == ID_CLOSE:
            self.frontend.close_communications()
        elif identifier == ID_SETTINGS:
            self.frontend.show_preferences(None)
        elif identifier == ID_EXIT:
            self.frontend.quit()
