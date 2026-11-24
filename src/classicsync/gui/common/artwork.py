import io
import math
import struct
from pathlib import Path

import wx

from ..settings import data_directory

STATE_COLOURS = {
    "connected": wx.Colour(0, 150, 60),
    "synchronized": wx.Colour(0, 150, 60),
    "waiting": wx.Colour(150, 150, 150),
    "disabled": wx.Colour(150, 150, 150),
    "connecting": wx.Colour(225, 185, 0),
    "error": wx.Colour(200, 30, 30),
}


PACKAGED_ARTWORK = Path(__file__).resolve().parents[1] / "artwork_data"


def artwork_directory():
    return data_directory() / "artwork"


def artwork_directories():
    return [artwork_directory(), PACKAGED_ARTWORK]


def icon_bitmap(icon):
    bitmap = wx.Bitmap()
    bitmap.CopyFromIcon(icon)
    return bitmap


def bitmap_from_icon_bundle(bundle, size):
    return icon_bitmap(bundle.GetIcon(wx.Size(size, size)))


ICON_DIRECTORY_HEADER = "<HHH"
ICON_DIRECTORY_ENTRY = "<BBBBHHII"
ICON_HEADER_SIZE = struct.calcsize(ICON_DIRECTORY_HEADER)
ICON_ENTRY_SIZE = struct.calcsize(ICON_DIRECTORY_ENTRY)
LOADABLE_ICON_DEPTHS = (0, 1, 4, 8, 24, 32)


def icon_entries(data):
    if len(data) < ICON_HEADER_SIZE:
        return []
    reserved, kind, count = struct.unpack_from(ICON_DIRECTORY_HEADER, data)
    entries = []
    for index in range(count):
        offset = ICON_HEADER_SIZE + index * ICON_ENTRY_SIZE
        if offset + ICON_ENTRY_SIZE > len(data):
            break
        width, height, colours, _reserved, planes, depth, size, start = struct.unpack_from(ICON_DIRECTORY_ENTRY, data, offset)
        if start + size > len(data) or depth not in LOADABLE_ICON_DEPTHS:
            continue
        entries.append((width or 256, height or 256, colours, planes, depth, size, start))
    return entries


def single_icon_image(data, entry):
    width, height, colours, planes, depth, size, start = entry
    header = struct.pack(ICON_DIRECTORY_HEADER, 0, 1, 1)
    directory = struct.pack(ICON_DIRECTORY_ENTRY, width % 256, height % 256, colours, 0, planes, depth, size,
                            ICON_HEADER_SIZE + ICON_ENTRY_SIZE)
    with wx.LogNull():
        image = wx.Image(io.BytesIO(header + directory + data[start:start + size]), wx.BITMAP_TYPE_ICO)
    return image if image.IsOk() else None


def icon_file_bitmap(path, size):
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    entries = icon_entries(data)
    exact = sorted((entry for entry in entries if entry[0] == size), key=lambda entry: -entry[4])
    others = sorted((entry for entry in entries if entry[0] != size), key=lambda entry: (entry[0] < size, abs(entry[0] - size), -entry[4]))
    for entry in exact + others:
        image = single_icon_image(data, entry)
        if image is None:
            continue
        if image.GetWidth() != size:
            image = image.Scale(size, size, wx.IMAGE_QUALITY_NORMAL)
        return wx.Bitmap(image)
    return None


def draw_sync_badge(size, colour, mark=None, angle=0.0):
    bitmap = wx.Bitmap(size, size, 32)
    bitmap.UseAlpha()
    memory = wx.MemoryDC(bitmap)
    memory.SetBackground(wx.Brush(wx.Colour(0, 0, 0, 0)))
    memory.Clear()
    context = wx.GraphicsContext.Create(memory)
    centre = size / 2
    radius = size * 0.36
    pen_width = max(2, size // 8)
    context.SetPen(wx.Pen(colour, pen_width))
    for start in (0.15, math.pi + 0.15):
        path = context.CreatePath()
        path.AddArc(centre, centre, radius, start + angle, start + angle + math.pi * 0.7, True)
        context.StrokePath(path)
        end = start + angle + math.pi * 0.7
        tip_x = centre + radius * math.cos(end)
        tip_y = centre + radius * math.sin(end)
        head = context.CreatePath()
        head_size = pen_width * 1.6
        head.MoveToPoint(tip_x + head_size * math.cos(end - math.pi / 2), tip_y + head_size * math.sin(end - math.pi / 2))
        head.AddLineToPoint(tip_x + head_size * math.cos(end) * 1.2, tip_y + head_size * math.sin(end) * 1.2)
        head.AddLineToPoint(tip_x - head_size * math.cos(end) * 1.2, tip_y - head_size * math.sin(end) * 1.2)
        head.CloseSubpath()
        context.SetBrush(wx.Brush(colour))
        context.FillPath(head)
    if mark:
        context.SetFont(wx.Font(wx.FontInfo(int(size * 0.33)).Bold()), wx.Colour(200, 30, 30))
        width, height = context.GetTextExtent(mark)
        context.DrawText(mark, size - width - 1, size - height)
    del context
    memory.SelectObject(wx.NullBitmap)
    return bitmap


def drawn_icon(size, state, mark=None):
    icon = wx.Icon()
    icon.CopyFromBitmap(draw_sync_badge(size, STATE_COLOURS.get(state, STATE_COLOURS["waiting"]), mark))
    return icon


class Artwork:
    def __init__(self, product):
        self.product = product
        self.cache = {}

    def path(self, module, name):
        candidates = [directory / self.product / module / name for directory in artwork_directories()]
        return next((candidate for candidate in candidates if candidate.exists()), candidates[0])

    def cached(self, key, factory):
        if key not in self.cache:
            self.cache[key] = factory()
        return self.cache[key]

    def image(self, module, name, transparent=True):
        def load():
            path = self.path(module, name)
            if not path.exists():
                return None
            image = wx.Image(str(path))
            if not image.IsOk():
                return None
            if transparent and path.suffix.lower() == ".bmp":
                image.SetMaskColour(image.GetRed(0, 0), image.GetGreen(0, 0), image.GetBlue(0, 0))
                image.InitAlpha()
            return image
        return self.cached(("image", module, name, transparent), load)

    def bitmap(self, module, name, fallback=None, transparent=True):
        image = self.image(module, name, transparent)
        if image:
            return wx.Bitmap(image)
        return fallback() if fallback else wx.NullBitmap

    def strip(self, module, name, size, count, fallback=None):
        image = self.image(module, name)
        if image and image.GetWidth() >= size * count:
            return [wx.Bitmap(image.GetSubImage(wx.Rect(index * size, 0, size, image.GetHeight()))) for index in range(count)]
        return fallback() if fallback else []

    def sound_path(self, name):
        path = self.path(".", name)
        return path if path.exists() else None

    def icon_bundle(self, module, number):
        def load():
            path = self.path(module, f"group_icon_{number}.ico")
            if not path.exists():
                return None
            bundle = wx.IconBundle(str(path), wx.BITMAP_TYPE_ICO)
            return bundle if bundle.GetIconCount() else None
        return self.cached(("icon", module, number), load)

    def icon(self, module, number, size, fallback=None):
        bundle = self.icon_bundle(module, number)
        if bundle:
            return bundle.GetIcon(wx.Size(size, size))
        return fallback() if fallback else wx.NullIcon

    def icon_as_bitmap(self, module, number, size, fallback=None):
        bundle = self.icon_bundle(module, number)
        if bundle:
            return bitmap_from_icon_bundle(bundle, size)
        return fallback() if fallback else wx.NullBitmap

    def icon_file_bitmap(self, module, number, size):
        return self.cached(("icon-file", module, number, size), lambda: icon_file_bitmap(self.path(module, f"group_icon_{number}.ico"), size))

    def application_icons(self, module, number):
        bundle = self.icon_bundle(module, number)
        if bundle:
            return bundle
        bundle = wx.IconBundle()
        for size in (16, 32, 48):
            bundle.AddIcon(drawn_icon(size, "connected"))
        return bundle
