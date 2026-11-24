import wx

from ...common.animation import load_clip
from ...common.artwork import Artwork, bitmap_from_icon_bundle, drawn_icon

PRODUCT = "ce-services-2.2"
VIEWER = "HPCView.dll"
MANAGER = "DccMan.exe"
CHECK_PORT = "ChkPort.exe"
SYNC_MANAGER = "SyncMgr.exe"

MOBILE_DEVICES_ICON = 120
HANDHELD_CONNECTED_ICON = 1023
HANDHELD_DISCONNECTED_ICON = 1025
PALM_CONNECTED_ICON = 116
PALM_DISCONNECTED_ICON = 119
SYNC_ICON = 109
STATE_ICONS = {"connected": 109, "waiting": 110, "connecting": 113, "disabled": 118}
CABLE_ANIMATION = 106
SEARCH_ANIMATION = 107


class CeServicesArtwork(Artwork):
    def __init__(self):
        super().__init__(PRODUCT)

    def application_icons(self):
        return super().application_icons(VIEWER, MOBILE_DEVICES_ICON)

    def mobile_devices_bitmap(self, size):
        def fallback():
            return wx.ArtProvider.GetBitmap(wx.ART_FOLDER, wx.ART_OTHER, wx.Size(size, size))
        return self.cached(("mobile-devices", size), lambda: self.icon_as_bitmap(VIEWER, MOBILE_DEVICES_ICON, size, fallback))

    def device_bitmap(self, palm_size, connected, size):
        if palm_size:
            number = PALM_CONNECTED_ICON if connected else PALM_DISCONNECTED_ICON
        else:
            number = HANDHELD_CONNECTED_ICON if connected else HANDHELD_DISCONNECTED_ICON

        def fallback():
            bitmap = wx.ArtProvider.GetBitmap(wx.ART_HARDDISK, wx.ART_OTHER, wx.Size(size, size))
            if connected or not bitmap.IsOk():
                return bitmap
            return bitmap.ConvertToDisabled()
        return self.cached(("device", number, size), lambda: self.icon_as_bitmap(VIEWER, number, size, fallback))

    def tray_icon(self, state):
        number = STATE_ICONS.get(state, STATE_ICONS["waiting"])
        return self.cached(("tray", state), lambda: self.icon(MANAGER, number, 16,
                                                             lambda: drawn_icon(32, state, "x" if state == "disabled" else None)))

    def status_bitmap(self, state):
        number = STATE_ICONS.get(state, STATE_ICONS["waiting"])

        def fallback():
            return bitmap_from_icon_bundle(wx.IconBundle(drawn_icon(32, state, "x" if state == "disabled" else None)), 32)
        return self.cached(("status", state), lambda: self.icon_as_bitmap(MANAGER, number, 32, fallback))

    def animation(self, module, number):
        return self.cached(("animation", module, number), lambda: load_clip(self, module, number))
