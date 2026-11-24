import wx

from ...i18n import _
from .layout import dialog_size, place

PAGE_WIDTH = 276
PAGE_HEIGHT = 140
SIDE_WIDTH = 80
BUTTON_TOP = PAGE_HEIGHT + 12


class ClassicWizard(wx.Dialog):
    page_text = {}
    finish_pages = set()
    first_page = None

    def __init__(self, parent, frontend, title):
        super().__init__(parent, title=title)
        self.frontend = frontend
        self.application = frontend.application
        self.history = []
        self.busy = False
        self.SetClientSize(dialog_size(self, PAGE_WIDTH, BUTTON_TOP + 21))
        self.pages = {}
        for number in self.page_text:
            page = wx.Panel(self, pos=(0, 0), size=dialog_size(self, PAGE_WIDTH, PAGE_HEIGHT))
            self.add_side_bitmap(page, self.side_bitmap(number))
            for text, x, y, width, height in self.page_text[number]:
                place(page, wx.StaticText, x, y, width, height, _(text))
            self.build_page(number, page)
            self.pages[number] = page
        place(self, wx.StaticLine, 0, PAGE_HEIGHT + 5, PAGE_WIDTH, 1)
        self.back = place(self, wx.Button, 113, BUTTON_TOP, 50, 14, _("< &Back"))
        self.next = place(self, wx.Button, 163, BUTTON_TOP, 50, 14, _("&Next >"))
        self.cancel = place(self, wx.Button, 219, BUTTON_TOP, 50, 14, _("Cancel"))
        self.back.Bind(wx.EVT_BUTTON, self.on_back)
        self.next.Bind(wx.EVT_BUTTON, self.on_next)
        self.cancel.Bind(wx.EVT_BUTTON, self.on_cancel)
        self.Bind(wx.EVT_CLOSE, self.on_cancel)
        self.show_page(self.first_page)
        self.CentreOnScreen()

    def side_bitmap(self, number):
        return wx.NullBitmap

    def add_side_bitmap(self, page, bitmap):
        if not bitmap.IsOk():
            return
        size = dialog_size(self, SIDE_WIDTH, PAGE_HEIGHT)
        image = bitmap.ConvertToImage().Scale(size.width, size.height, wx.IMAGE_QUALITY_HIGH)
        wx.StaticBitmap(page, bitmap=wx.Bitmap(image), pos=(0, 0))

    def build_page(self, number, page):
        pass

    def page_shown(self, number):
        pass

    def can_go_next(self):
        return True

    def can_go_back(self):
        return bool(self.history)

    def show_page(self, number):
        for page_number, page in self.pages.items():
            page.Show(page_number == number)
        self.current = number
        self.page_shown(number)
        self.update_buttons()
        self.Layout()

    def update_buttons(self):
        finishing = self.current in self.finish_pages
        self.next.SetLabel(_("Finish") if finishing else _("&Next >"))
        self.back.Enable(not self.busy and not finishing and self.can_go_back())
        self.next.Enable(not self.busy and self.can_go_next())
        self.cancel.Enable(not self.busy and not finishing)

    def go(self, number):
        self.history.append(self.current)
        self.show_page(number)

    def set_busy(self, busy):
        self.busy = busy
        self.update_buttons()

    def on_back(self, event):
        if self.history:
            self.show_page(self.history.pop())

    def on_next(self, event):
        raise NotImplementedError

    def confirm_cancel(self):
        return True

    def on_cancel(self, event):
        if self.busy:
            return
        if self.current in self.finish_pages or self.confirm_cancel():
            self.EndModal(wx.ID_CANCEL)
