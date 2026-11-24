import wx

from ...convert import FORMATS
from ...convert.rules import DESKTOP_TO_DEVICE, DEVICE_TO_DESKTOP, NO_CONVERSION, rule, sources, targets
from ...i18n import N_, _
from ...rapi.structures import FindData
from .file_icons import FileIcons
from .layout import dialog_size, place

PEGCONV = "pegconv.dll"
GENERAL_ICON = 118
FALLBACK_GENERAL_ICON = 104

PAGE_TEXT = {
    DEVICE_TO_DESKTOP: (N_("You can adjust conversion settings for files moved from your mobile device to the desktop computer."),
                        N_("Mobile device convertible file &types:"), N_("Mobile device files of the type"),
                        N_("Convert to desktop computer files of the type")),
    DESKTOP_TO_DEVICE: (N_("You can adjust conversion settings for files moved from the desktop computer to your mobile device."),
                        N_("Desktop computer convertible file &types:"), N_("Desktop computer files of the type"),
                        N_("Convert to mobile device files of the type")),
}
EDIT_TEXT = {
    DEVICE_TO_DESKTOP: (N_("When converting from mobile device files of the type:"), N_("Convert to desktop computer files of the type:")),
    DESKTOP_TO_DEVICE: (N_("When converting from desktop computer files of the type:"), N_("Convert to mobile device files of the type:")),
}


def type_name(name):
    return _("(No conversion)") if name == NO_CONVERSION else FORMATS[name].description


def type_extension(name):
    return "" if name == NO_CONVERSION else FORMATS[name].extensions[0]


class TypeIcons:
    def __init__(self, artwork):
        self.icons = FileIcons(artwork)
        self.small = self.icons.image_list(16)
        self.large = self.icons.image_list(32)

    def index(self, name):
        return self.icons.index_for(FindData(name="file" + type_extension(name)))

    def bitmap(self, name):
        if name == NO_CONVERSION:
            return wx.NullBitmap
        return self.large.GetBitmap(self.index(name))


class TypeDescription:
    def __init__(self, parent, icons, x, y):
        self.icons = icons
        self.bitmap = wx.StaticBitmap(parent, bitmap=wx.NullBitmap, pos=parent.ConvertDialogToPixels(wx.Point(x, y)),
                                      size=wx.Size(32, 32))
        self.name = place(parent, wx.StaticText, x + 37, y, 129, 18, "")
        self.extension = place(parent, wx.StaticText, x + 175, y, 40, 18, "")

    def show(self, name):
        bitmap = self.icons.bitmap(name)
        if bitmap.IsOk():
            self.bitmap.SetBitmap(bitmap)
        self.bitmap.Show(bitmap.IsOk())
        self.name.SetLabel(type_name(name))
        self.extension.SetLabel(type_extension(name))


class EditConversionDialog(wx.Dialog):
    def __init__(self, parent, icons, direction, source, current):
        super().__init__(parent, title=_("Edit Conversion Settings: ") + type_extension(source))
        self.SetClientSize(dialog_size(self, 237, 139))
        source_label, target_label = EDIT_TEXT[direction]
        place(self, wx.StaticBox, 7, 7, 222, 42, _(source_label))
        source_box = TypeDescription(self, icons, 13, 20)
        source_box.show(source)
        place(self, wx.StaticBox, 7, 55, 222, 58, _(target_label))
        place(self, wx.StaticText, 20, 68, 19, 10, _("&Type:"))
        self.choices = sorted(targets(direction, source), key=lambda name: type_name(name).lower()) + [NO_CONVERSION]
        self.type = place(self, wx.Choice, 45, 67, 168, 12, choices=[type_name(name) for name in self.choices])
        self.type.SetSelection(self.choices.index(current) if current in self.choices else len(self.choices) - 1)
        self.target_box = TypeDescription(self, icons, 13, 87)
        self.target_box.show(self.selected())
        self.type.Bind(wx.EVT_CHOICE, lambda event: self.target_box.show(self.selected()))
        place(self, wx.Button, 123, 118, 50, 14, _("OK"), id=wx.ID_OK).SetDefault()
        place(self, wx.Button, 180, 118, 50, 14, _("Cancel"), id=wx.ID_CANCEL)
        self.CentreOnParent()

    def selected(self):
        return self.choices[self.type.GetSelection()]


class DirectionPage(wx.Panel):
    def __init__(self, parent, icons, direction, chosen, version):
        super().__init__(parent)
        self.icons = icons
        self.direction = direction
        self.chosen = chosen
        self.version = version
        self.SetClientSize(dialog_size(self, 241, 211))
        intro, list_label, source_label, target_label = PAGE_TEXT[direction]
        place(self, wx.StaticText, 7, 7, 223, 21, _(intro))
        place(self, wx.StaticText, 7, 28, 184, 9, _(list_label))
        self.sources = sorted(sources(direction), key=lambda name: type_name(name).lower())
        self.list = place(self, wx.ListCtrl, 7, 38, 162, 77, style=wx.LC_REPORT | wx.LC_NO_HEADER | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN)
        self.list.SetImageList(icons.small, wx.IMAGE_LIST_SMALL)
        self.list.InsertColumn(0, "")
        for index, name in enumerate(self.sources):
            self.list.InsertItem(index, type_name(name), icons.index(name))
        self.list.SetColumnWidth(0, wx.LIST_AUTOSIZE)
        self.edit = place(self, wx.Button, 177, 38, 57, 14, _("&Edit..."))
        place(self, wx.StaticBox, 7, 118, 227, 85, _("File conversion details:"))
        place(self, wx.StaticText, 13, 128, 150, 10, _(source_label))
        self.source_box = TypeDescription(self, icons, 13, 140)
        place(self, wx.StaticText, 13, 166, 150, 10, _(target_label))
        self.target_box = TypeDescription(self, icons, 13, 178)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda event: self.show_details())
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda event: self.edit_selected())
        self.edit.Bind(wx.EVT_BUTTON, lambda event: self.edit_selected())
        if self.sources:
            self.list.Select(0)
        self.show_details()

    def selected(self):
        index = self.list.GetFirstSelected()
        return self.sources[index] if index >= 0 else None

    def current(self, source):
        return rule(self.direction, source, self.chosen, self.version)

    def show_details(self):
        source = self.selected()
        self.edit.Enable(source is not None)
        if source is not None:
            self.source_box.show(source)
            self.target_box.show(self.current(source))

    def edit_selected(self):
        source = self.selected()
        if source is None:
            return
        with EditConversionDialog(self, self.icons, self.direction, source, self.current(source)) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.chosen[source] = dialog.selected()
                self.show_details()


class FileConversionSheet(wx.Dialog):
    def __init__(self, parent, application, artwork, version=2):
        super().__init__(parent, title=_("File Conversion Properties"))
        self.application = application
        settings = application.settings
        icons = TypeIcons(artwork)
        notebook = wx.Notebook(self)
        general = wx.Panel(notebook)
        general.SetClientSize(dialog_size(general, 241, 211))
        icon = artwork.icon_as_bitmap(PEGCONV, GENERAL_ICON, 32, lambda: artwork.icon_as_bitmap(PEGCONV, FALLBACK_GENERAL_ICON, 32))
        wx.StaticBitmap(general, bitmap=icon, pos=general.ConvertDialogToPixels(wx.Point(8, 6)))
        place(general, wx.StaticText, 39, 6, 190, 25, _("During conversion, desktop computer files get transformed into their corresponding "
                                                         "file types on the mobile device, and vice versa."))
        place(general, wx.StaticText, 39, 36, 190, 24, _("Files do not have to be converted. However, you may not be able to open "
                                                          "unconverted files using the programs on your device."))
        self.convert_files = place(general, wx.CheckBox, 39, 69, 190, 16, _("&Convert files when synchronized, copied or moved"))
        self.convert_files.SetValue(settings.convert_files)
        notebook.AddPage(general, _("General"))
        self.device_to_desktop = dict(settings.device_to_desktop or {})
        self.desktop_to_device = dict(settings.desktop_to_device or {})
        notebook.AddPage(DirectionPage(notebook, icons, DEVICE_TO_DESKTOP, self.device_to_desktop, version), _("Device to Desktop"))
        notebook.AddPage(DirectionPage(notebook, icons, DESKTOP_TO_DEVICE, self.desktop_to_device, version), _("Desktop to Device"))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(notebook, 1, wx.EXPAND | wx.ALL, 6)
        sizer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALIGN_RIGHT | wx.ALL, 6)
        self.SetSizerAndFit(sizer)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.CentreOnParent()

    def on_ok(self, event):
        settings = self.application.settings
        settings.convert_files = self.convert_files.GetValue()
        settings.device_to_desktop = self.device_to_desktop
        settings.desktop_to_device = self.desktop_to_device
        settings.save()
        self.EndModal(wx.ID_OK)


def show_file_conversion(parent, application, artwork, version=2):
    with FileConversionSheet(parent, application, artwork, version) as sheet:
        sheet.ShowModal()
