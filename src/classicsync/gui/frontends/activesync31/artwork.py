import wx

from ...common.artwork import STATE_COLOURS, Artwork, draw_sync_badge, drawn_icon

PRODUCT = "activesync-3.1"
MANAGER = "WCESMgr.exe"
AGENT = "wcescomm.exe"

TOOLBAR_FALLBACKS = [wx.ART_REDO, wx.ART_CROSS_MARK, wx.ART_REPORT_VIEW, wx.ART_FIND, wx.ART_LIST_VIEW]
STATE_BITMAPS = {"connected": "bitmap_6008.bmp", "synchronized": "bitmap_6008.bmp", "waiting": "bitmap_6017.bmp",
                 "disabled": "bitmap_6029.bmp", "connecting": "bitmap_6019.bmp", "error": "bitmap_6018.bmp"}
TRAY_ICONS = {"connected": 131, "waiting": 132, "disabled": 133, "connecting": 134, "error": 136}


class ActiveSyncArtwork(Artwork):
    def __init__(self):
        super().__init__(PRODUCT)

    def toolbar_bitmaps(self, large=True):
        size = 21 if large else 17

        def fallback():
            art_size = wx.Size(24, 24) if large else wx.Size(16, 16)
            return [wx.ArtProvider.GetBitmap(art, wx.ART_TOOLBAR, art_size) for art in TOOLBAR_FALLBACKS]
        return self.cached(("toolbar", large), lambda: self.strip(MANAGER, "bitmap_6007.bmp" if large else "bitmap_6006.bmp", size, 5, fallback))

    def state_bitmap(self, state):
        def fallback():
            return draw_sync_badge(42, STATE_COLOURS.get(state, STATE_COLOURS["waiting"]), "!" if state == "error" else None)
        return self.cached(("state", state), lambda: self.bitmap(MANAGER, STATE_BITMAPS.get(state, "bitmap_6017.bmp"), fallback))

    def tray_icon(self, state):
        return self.cached(("tray", state), lambda: self.icon(AGENT, TRAY_ICONS.get(state, 132), 16,
                                                             lambda: drawn_icon(32, state, "x" if state == "disabled" else None)))

    def application_icons(self):
        return super().application_icons(MANAGER, 88)

    def connection_icon(self):
        return self.icon_as_bitmap(AGENT, 130, 32, lambda: wx.ArtProvider.GetBitmap(wx.ART_HARDDISK, wx.ART_MESSAGE_BOX, wx.Size(32, 32)))
