import os

import wx

from ...convert.fonts import CHARACTER_SETS, RASTER_EXTENSIONS, FontConversionError, available_sizes, converted_fonts, font_files
from ...formats.fnt import write_fnt
from ...i18n import _, format_original
from .layout import dialog_size, place

DEFAULT_POINT_SIZES = (8, 10, 12)
SAMPLE_TEXT = "AaBbYyZz"


def sample_bitmap(font, text=SAMPLE_TEXT):
    glyphs = [font.glyph(ord(character)) or font.glyphs[-1] for character in text]
    width = max(1, sum(glyph.width for glyph in glyphs))
    image = wx.Image(width, font.pixel_height)
    image.SetRGB(wx.Rect(0, 0, width, font.pixel_height), 255, 255, 255)
    x = 0
    for glyph in glyphs:
        for row, value in enumerate(glyph.rows):
            for column in range(glyph.width):
                if value & (1 << (glyph.width - 1 - column)):
                    image.SetRGB(x + column, row, 0, 0, 0)
        x += glyph.width
    return wx.Bitmap(image)


class FontConversionDialog(wx.Dialog):
    def __init__(self, parent, path):
        super().__init__(parent, title=_("Convert Font to Mobile Device Format"))
        self.path = path
        self.raster = os.path.splitext(path)[1].lower() in RASTER_EXTENSIONS
        self.SetClientSize(dialog_size(self, 223, 199))
        self.group = place(self, wx.StaticBox, 7, 7, 148, 34, os.path.basename(path))
        self.sample = wx.StaticBitmap(self, bitmap=wx.NullBitmap, pos=self.ConvertDialogToPixels(wx.Point(18, 20)),
                                      size=dialog_size(self, 127, 16))
        place(self, wx.Button, 166, 10, 50, 14, _("OK"), id=wx.ID_OK).SetDefault()
        place(self, wx.Button, 166, 27, 50, 14, _("Cancel"), id=wx.ID_CANCEL)
        place(self, wx.StaticText, 7, 45, 80, 8, _("Character set to convert:"))
        self.charset = place(self, wx.Choice, 7, 54, 110, 12, choices=[_(character_set.name) for character_set in CHARACTER_SETS])
        self.charset.SetSelection(0)
        self.charset.Enable(not self.raster)
        place(self, wx.StaticText, 7, 73, 134, 8, _("&Choose the point sizes to convert:"))
        self.sizes = place(self, wx.ListBox, 7, 85, 181, 89, style=wx.LB_MULTIPLE)
        self.total = place(self, wx.StaticText, 7, 184, 171, 8, "")
        self.points = available_sizes(path)
        self.fonts = {}
        self.fill_sizes()
        for index, points in enumerate(self.points):
            if points in DEFAULT_POINT_SIZES or len(self.points) == 1:
                self.sizes.SetSelection(index)
        self.charset.Bind(wx.EVT_CHOICE, lambda event: self.fill_sizes())
        self.sizes.Bind(wx.EVT_LISTBOX, lambda event: self.update_total())
        self.update_total()
        self.CentreOnParent()

    def character_set(self):
        return CHARACTER_SETS[self.charset.GetSelection()]

    def fill_sizes(self):
        selected = set(self.sizes.GetSelections())
        fonts = converted_fonts(self.path, self.points, self.character_set())
        self.fonts = {font.points: font for font in fonts}
        self.sizes.Set([format_original(_("%d points (%d KB)"), points, (len(write_fnt(self.fonts[points])) + 1023) // 1024)
                        for points in self.points])
        for index in selected:
            self.sizes.SetSelection(index)
        self.update_total()

    def chosen_points(self):
        return [self.points[index] for index in self.sizes.GetSelections()]

    def update_total(self):
        chosen = self.chosen_points()
        kilobytes = sum((len(write_fnt(self.fonts[points])) + 1023) // 1024 for points in chosen)
        self.total.SetLabel(format_original(_("%d point sizes selected for a total of %d KB."), len(chosen), kilobytes))
        self.FindWindow(wx.ID_OK).Enable(bool(chosen))
        preview = self.fonts.get(chosen[0] if chosen else (self.points[0] if self.points else None))
        if preview:
            self.sample.SetBitmap(sample_bitmap(preview))
            self.group.SetLabel(preview.face)


def ask_font_conversion(parent, path):
    try:
        with FontConversionDialog(parent, path) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return None
            return font_files(path, dialog.chosen_points(), dialog.character_set())
    except FontConversionError as error:
        wx.MessageBox(str(error), _("Convert Font to Mobile Device Format"), wx.OK | wx.ICON_ERROR, parent)
        return None
