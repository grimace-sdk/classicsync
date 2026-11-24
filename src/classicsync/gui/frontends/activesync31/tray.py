import wx
import wx.adv

from ....i18n import N_, _
from ...branding import PRODUCT_NAME, rebrand, title
from ...service import STATE_CONNECTED, STATE_CONNECTING, STATE_DISABLED

FRONTEND_KEY = "activesync31"
TITLE = title(FRONTEND_KEY)

ORIGINAL_ID_OFFSET = 30000
ID_OPEN = 42109 - ORIGINAL_ID_OFFSET
ID_SYNCHRONIZE = 42105 - ORIGINAL_ID_OFFSET
ID_STOP = 50002 - ORIGINAL_ID_OFFSET
ID_RESOLVE = 50004 - ORIGINAL_ID_OFFSET
ID_CONNECTION_SETTINGS = 40014 - ORIGINAL_ID_OFFSET
ID_EXPLORE = 40010 - ORIGINAL_ID_OFFSET

TOOLTIPS = {
    STATE_CONNECTED: N_("Connected"),
    STATE_CONNECTING: N_("Connecting"),
    STATE_DISABLED: N_("Connection disabled"),
}


class TrayIcon(wx.adv.TaskBarIcon):
    def __init__(self, application):
        super().__init__()
        self.application = application
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, lambda event: application.show_main_window())
        self.Bind(wx.EVT_MENU, self.on_command)

    def update_state(self, state, syncing=False):
        icon_state = {STATE_CONNECTED: "connected", STATE_CONNECTING: "connecting", STATE_DISABLED: "disabled"}.get(state, "waiting")
        if syncing:
            icon_state = "connecting"
        tooltip = _("Synchronizing") if syncing else _(TOOLTIPS.get(state, N_("Not connected")))
        self.SetIcon(self.application.artwork.tray_icon(icon_state), f"{TITLE}: {tooltip}")

    def CreatePopupMenu(self):
        connected = self.application.service.state == STATE_CONNECTED
        menu = wx.Menu()
        menu.Append(ID_OPEN, rebrand(_("&Open Microsoft ActiveSync"), FRONTEND_KEY))
        menu.AppendSeparator()
        syncing = self.application.sync.running
        menu.Append(ID_SYNCHRONIZE, _("&Synchronize")).Enable(connected and not syncing)
        menu.Append(ID_STOP, _("Sto&p")).Enable(syncing)
        menu.AppendSeparator()
        sync = self.application.sync
        resolvable = connected and not syncing and sync.partnership() is not None and bool(sync.unresolved_items())
        menu.Append(ID_RESOLVE, _("Resolve &items...")).Enable(resolvable)
        menu.AppendSeparator()
        menu.Append(ID_CONNECTION_SETTINGS, _("Co&nnection Settings..."))
        menu.AppendSeparator()
        menu.Append(ID_EXPLORE, _("E&xplore")).Enable(connected)
        menu.AppendSeparator()
        menu.Append(wx.ID_PREFERENCES, _("{product} &Settings...").format(product=PRODUCT_NAME))
        menu.Append(wx.ID_EXIT, _("E&xit"))
        return menu

    def on_command(self, event):
        identifier = event.GetId()
        if identifier == ID_OPEN:
            self.application.show_main_window()
        elif identifier == ID_SYNCHRONIZE:
            self.application.sync.start()
        elif identifier == ID_STOP:
            self.application.sync.stop()
        elif identifier == ID_RESOLVE:
            self.application.show_resolve_items(None)
        elif identifier == ID_CONNECTION_SETTINGS:
            self.application.show_connection_settings(None)
        elif identifier == ID_EXPLORE:
            self.application.show_explore()
        elif identifier == wx.ID_PREFERENCES:
            self.application.show_preferences(None)
        elif identifier == wx.ID_EXIT:
            self.application.quit()
