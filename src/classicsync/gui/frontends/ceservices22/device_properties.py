import wx

from ....i18n import _, format_original
from ...common.layout import bold, dialog_size, place
from .sheet import lay_out_property_sheet

PALM_PLATFORMS = ("Palm PC", "Palm PC2")


def is_palm_size(announcement):
    return bool(announcement and announcement.info and announcement.info.platform in PALM_PLATFORMS)


def total_memory_kb(details):
    memory = details.get("memory")
    store = details.get("store")
    total = (memory.total_physical if memory else 0) + (store.store_size if store else 0)
    return total // 1024 if total else None


def memory_text(details):
    kilobytes = total_memory_kb(details)
    return format_original(_("%d KB RAM"), kilobytes) if kilobytes else _("Unknown")


def operating_system_text(announcement, details):
    version = details.get("version")
    info = announcement.info if announcement else None
    if version:
        build = version.build or (info.os_build if info else 0)
        return _("Windows CE Version {major}.{minor:02d} (Build {build})").format(major=version.major, minor=version.minor,
                                                                                  build=build)
    if info:
        return _("Windows CE Version {major}.{minor:02d} (Build {build})").format(major=info.os_major, minor=info.os_minor,
                                                                                  build=info.os_build)
    return "Windows CE"


def processor_text(announcement, details):
    system = details.get("system")
    if system:
        return system.processor_name
    info = announcement.info if announcement else None
    return info.processor_name if info else _("Unknown")


class DevicePropertiesPage(wx.Panel):
    def __init__(self, parent, frontend, announcement):
        super().__init__(parent)
        application = frontend.application
        details = application.device_details
        info = announcement.info if announcement else None
        self.SetMinSize(dialog_size(self, 224, 220))
        icon = frontend.artwork.device_bitmap(is_palm_size(announcement), True, 32)
        wx.StaticBitmap(self, bitmap=icon, pos=self.ConvertDialogToPixels(wx.Point(11, 10)))
        bold(place(self, wx.StaticText, 58, 15, 150, 9, _("Device Properties")))

        place(self, wx.StaticBox, 7, 34, 210, 44, _("Identification"))
        place(self, wx.StaticText, 13, 46, 55, 9, _("Device Name:"), style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
        place(self, wx.StaticText, 13, 63, 55, 9, _("Description:"), style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
        name = application.device_name(announcement)
        place(self, wx.TextCtrl, 73, 44, 141, 12, name, style=wx.TE_READONLY | wx.BORDER_NONE)
        place(self, wx.TextCtrl, 73, 61, 141, 12, details.get("description", ""), style=wx.TE_READONLY | wx.BORDER_NONE)

        place(self, wx.StaticBox, 7, 82, 210, 61, _("Computer"))
        place(self, wx.StaticText, 13, 94, 193, 9, operating_system_text(announcement, details))
        place(self, wx.StaticText, 13, 116, 198, 18, info.oem_info if info and info.oem_info else "")

        place(self, wx.StaticBox, 7, 147, 210, 64, _("System"))
        rows = [
            (_("Device Type:"), info.platform if info and info.platform else _("Unknown")),
            (_("Model:"), info.oem_info if info and info.oem_info else _("Unknown")),
            (_("Processor Type:"), processor_text(announcement, details)),
            (_("Memory:"), memory_text(details)),
        ]
        for (label, value), top in zip(rows, (158, 171, 183, 196)):
            place(self, wx.StaticText, 13, top, 60, 9, label, style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
            place(self, wx.StaticText, 77, top, 129, 9, value, style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)


class DevicePropertiesSheet(wx.Dialog):
    def __init__(self, parent, frontend, announcement, name):
        super().__init__(parent, title=format_original(_("%1 Properties"), name))
        notebook = wx.Notebook(self)
        notebook.AddPage(DevicePropertiesPage(notebook, frontend, announcement), _("Mobile Device Properties"))
        lay_out_property_sheet(self, notebook, apply_enabled=False)
        self.CentreOnParent()
