import wx

from ....i18n import _
from ...common.device_browser import (
    COMMAND_COPY, COMMAND_COPY_FROM_COMPUTER, COMMAND_COPY_TO_COMPUTER, COMMAND_CUT, COMMAND_DELETE, COMMAND_NEW_FOLDER, COMMAND_PASTE,
    COMMAND_PROPERTIES, COMMAND_REFRESH, COMMAND_RENAME, COMMAND_UP, DeviceBrowser, root_name,
)
from ...common.file_icons import FileIcons


def art(name):
    return wx.ArtProvider.GetBitmap(name, wx.ART_TOOLBAR, wx.Size(16, 16))


class ExploreWindow(wx.Frame):
    def __init__(self, frontend):
        super().__init__(None, size=wx.Size(720, 460))
        self.frontend = frontend
        self.SetIcons(frontend.artwork.application_icons())
        toolbar = self.CreateToolBar(wx.TB_HORIZONTAL | wx.TB_FLAT | wx.TB_TEXT)
        toolbar.AddTool(COMMAND_UP, _("Up"), art(wx.ART_GO_DIR_UP), _("Up One Level"))
        toolbar.AddTool(COMMAND_REFRESH, _("Refresh"), art(wx.ART_REDO), _("Refresh"))
        toolbar.AddSeparator()
        toolbar.AddTool(COMMAND_CUT, _("Cut"), art(wx.ART_CUT), _("Cut"))
        toolbar.AddTool(COMMAND_COPY, _("Copy"), art(wx.ART_COPY), _("Copy"))
        toolbar.AddTool(COMMAND_PASTE, _("Paste"), art(wx.ART_PASTE), _("Paste"))
        toolbar.AddSeparator()
        toolbar.AddTool(COMMAND_COPY_FROM_COMPUTER, _("Add Files"), art(wx.ART_FILE_OPEN), _("Copy files from this computer"))
        toolbar.AddTool(COMMAND_COPY_TO_COMPUTER, _("Copy Out"), art(wx.ART_FILE_SAVE), _("Copy selected items to this computer"))
        toolbar.AddTool(COMMAND_NEW_FOLDER, _("New Folder"), art(wx.ART_NEW_DIR), _("New Folder"))
        toolbar.AddTool(COMMAND_DELETE, _("Delete"), art(wx.ART_DELETE), _("Delete"))
        toolbar.AddTool(COMMAND_PROPERTIES, _("Properties"), art(wx.ART_INFORMATION), _("Properties"))
        toolbar.Realize()
        self.CreateStatusBar(2)
        self.SetStatusWidths([-1, 220])
        self.browser = DeviceBrowser(self, frontend.application, root_name(frontend.service.announcement),
                                     on_status=self.SetStatusText, on_title=self.SetTitle,
                                     file_icons=FileIcons(frontend.artwork))
        self.Bind(wx.EVT_TOOL, lambda event: self.browser.on_command(event))
        self.SetAcceleratorTable(wx.AcceleratorTable([
            (wx.ACCEL_NORMAL, wx.WXK_F5, COMMAND_REFRESH),
            (wx.ACCEL_CMD, ord("X"), COMMAND_CUT),
            (wx.ACCEL_CMD, ord("C"), COMMAND_COPY),
            (wx.ACCEL_CMD, ord("V"), COMMAND_PASTE),
            (wx.ACCEL_NORMAL, wx.WXK_DELETE, COMMAND_DELETE),
            (wx.ACCEL_NORMAL, wx.WXK_F2, COMMAND_RENAME),
            (wx.ACCEL_NORMAL, wx.WXK_BACK, COMMAND_UP),
            (wx.ACCEL_ALT, wx.WXK_RETURN, COMMAND_PROPERTIES),
        ]))
        self.Bind(wx.EVT_MENU, lambda event: self.browser.on_command(event))
        self.browser.navigate("\\")
        self.Centre()

    def enable_tools(self, enabled):
        toolbar = self.GetToolBar()
        for index in range(toolbar.GetToolsCount()):
            tool = toolbar.GetToolByPos(index)
            if not tool.IsSeparator():
                toolbar.EnableTool(tool.GetId(), enabled)

    def device_disconnected(self):
        self.browser.device_disconnected()
        self.enable_tools(False)

    def device_connected(self):
        self.enable_tools(True)
        self.browser.device_connected(root_name(self.frontend.service.announcement))
