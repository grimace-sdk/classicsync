import wx

from ...common.artwork import Artwork, drawn_icon, icon_bitmap

PRODUCT = "hpc-explorer-1.1"
EXPLORER = "hpcexpl.exe"
MANAGER = "DccMan.exe"
SHELL = "minshell.dll"

APPLICATION_ICON = 108
CUSTOM_TOOLBAR_BITMAP = "bitmap_171.bmp"
CUSTOM_TOOLBAR_FALLBACKS = [wx.ART_REDO, wx.ART_FILE_SAVE, wx.ART_HELP_SIDE_PANEL]

STATE_ICONS = {"waiting": 110, "connecting": 109, "connected": 113, "disabled": 118, "error": 118}
SHELL_ICONS = {"device": 1000, "folder": 1022, "folder_open": 1023, "file": 1021}
SHELL_FALLBACKS = {"device": wx.ART_HARDDISK, "folder": wx.ART_FOLDER, "folder_open": wx.ART_FOLDER_OPEN, "file": wx.ART_NORMAL_FILE}
IMAGE_LIST_ORDER = ["folder", "folder_open", "file", "device"]

ANIMATION_TO_DEVICE = 147
ANIMATION_FROM_DEVICE = 148
ANIMATION_DEVICE_COPY = 303
ANIMATION_DEVICE_MOVE = 304


VIEW_GLYPHS = ["large", "small", "list", "details"]


def nearest_icon(bundle, size):
    candidates = [bundle.GetIconByIndex(index) for index in range(bundle.GetIconCount())]
    candidates = [icon for icon in candidates if icon.IsOk()]
    if not candidates:
        return None
    exact = [icon for icon in candidates if icon.GetWidth() == size]
    if exact:
        return icon_bitmap(exact[0])
    best = min(candidates, key=lambda icon: (icon.GetWidth() < size, abs(icon.GetWidth() - size)))
    image = icon_bitmap(best).ConvertToImage()
    return wx.Bitmap(image.Scale(size, size, wx.IMAGE_QUALITY_NORMAL))


def draw_view_glyph(mode):
    bitmap = wx.Bitmap(16, 16, 32)
    bitmap.UseAlpha()
    memory = wx.MemoryDC(bitmap)
    memory.SetBackground(wx.Brush(wx.Colour(0, 0, 0, 0)))
    memory.Clear()
    context = wx.GraphicsContext.Create(memory)
    ink = wx.Colour(0, 0, 128)
    line = wx.Colour(0, 0, 0)
    context.SetPen(wx.NullPen)
    if mode == "large":
        for x, y in ((1, 1), (9, 1), (1, 9), (9, 9)):
            context.SetBrush(wx.Brush(ink))
            context.DrawRectangle(x, y, 6, 6)
    elif mode == "small":
        for column in (0, 8):
            for row in (2, 7, 12):
                context.SetBrush(wx.Brush(ink))
                context.DrawRectangle(column + 1, row, 3, 3)
                context.SetBrush(wx.Brush(line))
                context.DrawRectangle(column + 5, row + 1, 2, 1)
    elif mode == "list":
        for column in (0, 8):
            for row in (1, 5, 9, 13):
                context.SetBrush(wx.Brush(ink))
                context.DrawRectangle(column + 1, row, 2, 2)
                context.SetBrush(wx.Brush(line))
                context.DrawRectangle(column + 4, row + 1, 3, 1)
    else:
        for row in (2, 6, 10, 14):
            context.SetBrush(wx.Brush(ink))
            context.DrawRectangle(1, row - 1, 2, 2)
            context.SetBrush(wx.Brush(line))
            context.DrawRectangle(4, row, 11, 1)
    del context
    memory.SelectObject(wx.NullBitmap)
    return bitmap


class HpcExplorerArtwork(Artwork):
    def __init__(self):
        super().__init__(PRODUCT)

    def application_icons(self):
        return super().application_icons(EXPLORER, APPLICATION_ICON)

    def about_icon(self):
        return self.icon_as_bitmap(EXPLORER, APPLICATION_ICON, 32,
                                   lambda: wx.ArtProvider.GetBitmap(wx.ART_INFORMATION, wx.ART_MESSAGE_BOX, wx.Size(32, 32)))

    def art(self, name, size):
        return wx.ArtProvider.GetBitmap(name, wx.ART_TOOLBAR, wx.Size(size, size))

    def custom_toolbar_bitmaps(self):
        def fallback():
            return [self.art(name, 16) for name in CUSTOM_TOOLBAR_FALLBACKS]
        return self.cached("custom_toolbar", lambda: self.strip(EXPLORER, CUSTOM_TOOLBAR_BITMAP, 16, 3, fallback))

    def view_bitmap(self, mode):
        return self.cached(("view", mode), lambda: draw_view_glyph(mode))

    def shell_bitmap(self, kind, size):
        def load():
            bundle = self.icon_bundle(SHELL, SHELL_ICONS[kind])
            bitmap = nearest_icon(bundle, size) if bundle else None
            if bitmap and bitmap.IsOk():
                return bitmap
            return wx.ArtProvider.GetBitmap(SHELL_FALLBACKS[kind], wx.ART_OTHER, wx.Size(size, size))
        return self.cached(("shell", kind, size), load)

    def image_list(self, size):
        images = wx.ImageList(size, size)
        for kind in IMAGE_LIST_ORDER:
            images.Add(self.shell_bitmap(kind, size))
        return images

    def state_icon(self, state, size):
        def load():
            bundle = self.icon_bundle(MANAGER, STATE_ICONS.get(state, STATE_ICONS["waiting"]))
            bitmap = nearest_icon(bundle, size) if bundle else None
            if bitmap and bitmap.IsOk():
                icon = wx.Icon()
                icon.CopyFromBitmap(bitmap)
                return icon
            return drawn_icon(size, state, "x" if state in ("disabled", "error") else None)
        return self.cached(("state", state, size), load)

    def state_bitmap(self, state, size=32):
        return icon_bitmap(self.state_icon(state, size))

