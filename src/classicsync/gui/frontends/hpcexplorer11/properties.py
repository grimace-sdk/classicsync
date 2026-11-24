from datetime import timezone

import wx

from ....i18n import N_, _, format_original
from ....rapi.structures import (
    FILE_ATTRIBUTE_ARCHIVE, FILE_ATTRIBUTE_HIDDEN, FILE_ATTRIBUTE_INROM, FILE_ATTRIBUTE_READONLY, FILE_ATTRIBUTE_SYSTEM,
    filetime_to_datetime,
)
from ...common.device_browser import describe_type
from ...common.layout import place
from .sheet import PropertySheet

ATTRIBUTES = [(N_("Read-only"), FILE_ATTRIBUTE_READONLY, 72, 139, 13), (N_("Hidden"), FILE_ATTRIBUTE_HIDDEN, 136, 139, 13),
              (N_("Archive"), FILE_ATTRIBUTE_ARCHIVE, 72, 151, 13), (N_("System"), FILE_ATTRIBUTE_SYSTEM, 136, 152, 12)]

ATTRIBUTE_RIGHT_EDGES = {72: 136, 136: 217}
LABEL_STYLE = wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END


def format_property_size(size):
    if size < 1024:
        return format_original(_("%d bytes (%d bytes)"), size, size)
    tenths = size * 10 // 1024
    return format_original(_("%d.%dKB (%d bytes)"), f"{tenths // 10:,}", tenths % 10, f"{size:,}")


def format_long_time(filetime):
    moment = filetime_to_datetime(filetime)
    if not moment:
        return ""
    local = moment.replace(tzinfo=timezone.utc).astimezone()
    hour = local.hour % 12 or 12
    return f"{local:%A, %B} {local.day}, {local.year} {hour}:{local:%M:%S %p}"


def widen_to_label(page, control, x, right_edge):
    available = page.ConvertDialogToPixels(wx.Size(right_edge - x, 0)).width
    size = control.GetSize()
    best_width = control.GetBestSize().width
    if best_width > size.width:
        control.SetSize(wx.Size(min(best_width, available), size.height))
    if best_width > available:
        control.SetToolTip(control.GetLabelText())


def value_field(page, x, y, width, value):
    return place(page, wx.StaticText, x, y, width, 10, value, style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_MIDDLE)


class EntryPropertiesSheet(PropertySheet):
    def __init__(self, parent, entry, location, artwork, on_attributes=None):
        super().__init__(parent, format_original(_("%s Properties"), entry.name))
        self.entry = entry
        self.on_attributes = on_attributes
        self.attribute_boxes = []
        if entry.is_directory:
            page = self.add_page(_("General"), 224, 103)
            self._folder_page(page, location, artwork)
            self.finish(with_apply=False)
        else:
            page = self.add_page(_("General"), 224, 185)
            self._file_page(page, location, artwork)
            self.finish()

    def _header(self, page, artwork, kind):
        wx.StaticBitmap(page, bitmap=artwork.shell_bitmap(kind, 32), pos=page.ConvertDialogToPixels(wx.Point(7, 9)))
        value_field(page, 57, 15, 151, self.entry.name)

    def _folder_page(self, page, location, artwork):
        self._header(page, artwork, "folder")
        place(page, wx.StaticLine, 6, 39, 210, 1)
        place(page, wx.StaticText, 7, 48, 46, 10, _("Type:"), style=LABEL_STYLE)
        place(page, wx.StaticText, 7, 62, 46, 10, _("Location:"), style=LABEL_STYLE)
        place(page, wx.StaticLine, 7, 82, 210, 1)
        value_field(page, 57, 48, 151, describe_type(self.entry))
        value_field(page, 57, 62, 151, location)

    def _file_page(self, page, location, artwork):
        self._header(page, artwork, "file")
        place(page, wx.StaticLine, 6, 39, 211, 1)
        place(page, wx.StaticText, 7, 48, 46, 10, _("Type:"), style=LABEL_STYLE)
        place(page, wx.StaticText, 7, 62, 46, 10, _("Location:"), style=LABEL_STYLE)
        place(page, wx.StaticText, 7, 77, 52, 10, _("Size:"), style=LABEL_STYLE)
        value_field(page, 61, 49, 151, describe_type(self.entry))
        value_field(page, 61, 63, 151, location)
        place(page, wx.StaticText, 61, 78, 151, 10, format_property_size(self.entry.size))
        place(page, wx.StaticLine, 6, 96, 211, 1)
        place(page, wx.StaticText, 7, 108, 58, 10, _("Modified:"), style=LABEL_STYLE)
        place(page, wx.StaticLine, 6, 128, 211, 1)
        place(page, wx.StaticText, 72, 109, 135, 10, format_long_time(self.entry.last_write_time))
        place(page, wx.StaticText, 7, 139, 46, 10, _("Attributes:"), style=LABEL_STYLE)
        in_rom = bool(self.entry.attributes & FILE_ATTRIBUTE_INROM)
        for label, bit, x, y, height in ATTRIBUTES:
            box = place(page, wx.CheckBox, x, y, 54, height, _(label))
            widen_to_label(page, box, x, ATTRIBUTE_RIGHT_EDGES[x])
            box.SetValue(bool(self.entry.attributes & bit))
            box.Enable(not in_rom and self.on_attributes is not None)
            box.Bind(wx.EVT_CHECKBOX, self.changed)
            self.attribute_boxes.append((box, bit))

    def attributes(self):
        attributes = self.entry.attributes
        for box, bit in self.attribute_boxes:
            attributes = attributes | bit if box.GetValue() else attributes & ~bit
        return attributes

    def apply(self):
        attributes = self.attributes()
        if self.on_attributes and attributes != self.entry.attributes:
            self.on_attributes(self.entry, attributes)
            self.entry.attributes = attributes
