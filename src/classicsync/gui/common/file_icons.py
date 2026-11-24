import os
from dataclasses import dataclass, field

import wx

KIND_FOLDER = "folder"
KIND_FOLDER_OPEN = "folder_open"
KIND_FILE = "file"
KIND_DEVICE = "device"
BASE_KINDS = [KIND_FOLDER, KIND_FOLDER_OPEN, KIND_FILE, KIND_DEVICE]
BASE_FALLBACKS = {KIND_FOLDER: wx.ART_FOLDER, KIND_FOLDER_OPEN: wx.ART_FOLDER_OPEN, KIND_FILE: wx.ART_NORMAL_FILE,
                  KIND_DEVICE: wx.ART_HARDDISK}

SHELL_MODULE = "minshell.dll"


@dataclass
class ShellIconTable:
    first_resource: int
    base: dict
    extensions: dict = field(default_factory=dict)
    applications: dict = field(default_factory=dict)


HPC_EXPLORER_ICONS = ShellIconTable(
    first_resource=1000,
    base={KIND_DEVICE: 0, KIND_FILE: 21, KIND_FOLDER: 22, KIND_FOLDER_OPEN: 23},
    extensions={".pwd": 4, ".pxl": 6, ".2bp": 25},
    applications={"pword.exe": 5, "pxl.exe": 7, "addrbook.exe": 9, "tasks.exe": 10, "calc.exe": 11, "clock.exe": 13,
                  "calendar.exe": 14, "pmail.exe": 15, "pegterm.exe": 16, "webview.exe": 17, "solitare.exe": 18,
                  "welcome.exe": 19, "remnet.exe": 20, "repllog.exe": 24},
)

CE_SERVICES_APPLICATIONS = {
    "pword.exe": 5, "pxl.exe": 7, "addrbook.exe": 9, "tasks.exe": 10, "calc.exe": 11, "iexplore.exe": 17, "clock.exe": 13,
    "calendar.exe": 14, "pmail.exe": 15, "pegterm.exe": 16, "webview.exe": 17, "solitare.exe": 18, "welcome.exe": 19,
    "remnet.exe": 20, "inkwrite.exe": 27, "notetake.exe": 27, "ppviewer.exe": 31, "repllog.exe": 24, "voiceapp.exe": 29,
    "voicstub.exe": 29,
}
CE_SERVICES_EXTENSIONS = {".pwd": 4, ".pwt": 32, ".pdt": 32, ".pxl": 6, ".pxt": 33, ".2bp": 25, ".pwi": 26, ".ppv": 30}

CE_SERVICES_ICONS = ShellIconTable(
    first_resource=2000,
    base={KIND_DEVICE: 0, KIND_FILE: 21, KIND_FOLDER: 22, KIND_FOLDER_OPEN: 23},
    extensions=CE_SERVICES_EXTENSIONS,
    applications=CE_SERVICES_APPLICATIONS,
)

ACTIVESYNC_ICONS = ShellIconTable(
    first_resource=2000,
    base={KIND_DEVICE: 0, KIND_FILE: 21, KIND_FOLDER: 22, KIND_FOLDER_OPEN: 23},
    extensions=CE_SERVICES_EXTENSIONS,
    applications={**CE_SERVICES_APPLICATIONS, "poutlook.exe": 34},
)

PRODUCT_TABLES = {"hpc-explorer-1.1": HPC_EXPLORER_ICONS, "ce-services-2.2": CE_SERVICES_ICONS, "activesync-3.1": ACTIVESYNC_ICONS}


class FileIcons:
    def __init__(self, artwork=None, table=None):
        self.artwork = artwork
        self.table = table if table is not None else PRODUCT_TABLES.get(getattr(artwork, "product", None))
        extra = []
        if self.table:
            for number in list(self.table.extensions.values()) + list(self.table.applications.values()):
                if number not in extra and number not in self.table.base.values():
                    extra.append(number)
        self.extra_numbers = extra
        self.extra_indices = {number: len(BASE_KINDS) + position for position, number in enumerate(extra)}

    def shell_bitmap(self, number, size):
        if self.artwork is None or self.table is None:
            return None
        bitmap = self.artwork.icon_file_bitmap(SHELL_MODULE, self.table.first_resource + number, size)
        return bitmap if bitmap and bitmap.IsOk() else None

    def base_bitmap(self, kind, size):
        number = self.table.base.get(kind) if self.table else None
        bitmap = self.shell_bitmap(number, size) if number is not None else None
        return bitmap or wx.ArtProvider.GetBitmap(BASE_FALLBACKS[kind], wx.ART_OTHER, wx.Size(size, size))

    def image_list(self, size):
        images = wx.ImageList(size, size)
        for kind in BASE_KINDS:
            images.Add(self.base_bitmap(kind, size))
        for number in self.extra_numbers:
            images.Add(self.shell_bitmap(number, size) or self.base_bitmap(KIND_FILE, size))
        return images

    def index_for(self, entry):
        if entry.is_directory:
            return BASE_KINDS.index(KIND_FOLDER)
        if self.table:
            name = entry.name.lower()
            number = self.table.applications.get(name)
            if number is None:
                number = self.table.extensions.get(os.path.splitext(name)[1])
            if number is not None and number in self.extra_indices:
                return self.extra_indices[number]
        return BASE_KINDS.index(KIND_FILE)
