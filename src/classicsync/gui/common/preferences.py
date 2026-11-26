import wx

from ...i18n import _, available_languages
from ..branding import disclaimer, NAMING_AUTHENTIC, NAMING_CLASSICSYNC, PRODUCT_NAME, palm_disclaimer, set_naming
from ..frontends import AUTOMATIC, FRONTENDS, frontend_label
from .layout import dialog_size, place

PAGE_GENERAL = "general"
PAGE_WINDOWS_CE = "windows-ce"
PAGE_PALM = "palm"
PAGE_ORDER = [PAGE_GENERAL, PAGE_WINDOWS_CE, PAGE_PALM]


def language_label(code):
    info = wx.Locale.FindLanguageInfo(code)
    return f"{info.Description} ({code})" if info else code


class GeneralPage(wx.Panel):
    def __init__(self, parent, settings):
        super().__init__(parent)
        place(self, wx.StaticText, 8, 10, 62, 9, _("&Naming:"))
        self.namings = [NAMING_CLASSICSYNC, NAMING_AUTHENTIC]
        self.naming = place(self, wx.Choice, 72, 8, 150, 12, choices=[PRODUCT_NAME, _("Authentic (original product names)")])
        self.naming.SetSelection(self.namings.index(settings.naming) if settings.naming in self.namings else 0)
        place(self, wx.StaticText, 8, 28, 62, 9, _("&Language:"))
        self.languages = [""] + available_languages()
        self.language = place(self, wx.Choice, 72, 26, 150, 12,
                              choices=[_("System default")] + [language_label(code) for code in self.languages[1:]])
        self.language.SetSelection(self.languages.index(settings.language) if settings.language in self.languages else 0)
        place(self, wx.StaticLine, 8, 48, 214, 1)
        place(self, wx.StaticText, 8, 54, 214, 36, disclaimer())
        place(self, wx.StaticText, 8, 92, 214, 27, palm_disclaimer())


class WindowsCePage(wx.Panel):
    def __init__(self, parent, application):
        super().__init__(parent)
        settings = application.settings
        place(self, wx.StaticText, 8, 8, 214, 18,
              _("Choose which desktop software to recreate. Automatic matches the software to the device's version of Windows CE."))
        place(self, wx.StaticText, 8, 34, 62, 9, _("&Desktop software:"))
        self.keys = [AUTOMATIC] + [key for key in FRONTENDS if key in application.frontend_classes]
        self.frontend = place(self, wx.Choice, 72, 32, 150, 12, choices=[frontend_label(key) for key in self.keys])
        self.frontend.SetSelection(self.keys.index(settings.frontend) if settings.frontend in self.keys else 0)
        place(self, wx.StaticText, 8, 54, 62, 9, _("&Local RAPI address:"))
        self.proxy = place(self, wx.TextCtrl, 72, 52, 90, 12, settings.rapi_proxy)
        place(self, wx.StaticText, 72, 67, 150, 18, _("Command-line tools reach the connected device here."))
        place(self, wx.StaticText, 8, 88, 62, 9, _("D&evice RAPI:"))
        self.device_rapi = place(self, wx.TextCtrl, 72, 86, 90, 12, settings.network_device_rapi)
        place(self, wx.StaticText, 72, 101, 150, 18, _("For network devices reached through a tunnel. Leave empty to use the device's own address."))


class PalmPage(wx.Panel):
    def __init__(self, parent, settings):
        super().__init__(parent)
        place(self, wx.StaticText, 8, 8, 214, 18,
              _("Synchronize Palm OS handhelds with HotSync. Press the HotSync button on the cradle to start."))
        self.usb = place(self, wx.CheckBox, 8, 32, 214, 10, _("Allow HotSync over &USB"))
        self.usb.SetValue(settings.palm_usb_enabled)
        self.tray = place(self, wx.CheckBox, 8, 48, 214, 10, _("Show the HotSync Manager &icon in the taskbar"))
        self.tray.SetValue(settings.show_hotsync_tray)


class PreferencesDialog(wx.Dialog):
    def __init__(self, parent, application, page=PAGE_GENERAL):
        super().__init__(parent, title=_("{product} Settings").format(product=PRODUCT_NAME))
        self.application = application
        settings = application.settings
        self.SetClientSize(dialog_size(self, 250, 180))
        self.notebook = wx.Notebook(self, pos=self.ConvertDialogToPixels(wx.Point(5, 5)), size=dialog_size(self, 240, 150))
        self.general = GeneralPage(self.notebook, settings)
        self.windows_ce = WindowsCePage(self.notebook, application)
        self.palm = PalmPage(self.notebook, settings)
        self.notebook.AddPage(self.general, _("General"))
        self.notebook.AddPage(self.windows_ce, _("Windows CE"))
        self.notebook.AddPage(self.palm, _("Palm"))
        self.notebook.SetSelection(PAGE_ORDER.index(page) if page in PAGE_ORDER else 0)
        place(self, wx.Button, 138, 160, 50, 14, _("OK"), id=wx.ID_OK).SetDefault()
        place(self, wx.Button, 192, 160, 50, 14, _("Cancel"), id=wx.ID_CANCEL)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.CentreOnScreen()

    def on_ok(self, event):
        settings = self.application.settings
        general, windows_ce, palm = self.general, self.windows_ce, self.palm
        device_rapi = windows_ce.device_rapi.GetValue().strip()
        connection_changed = settings.rapi_proxy != windows_ce.proxy.GetValue().strip() or settings.network_device_rapi != device_rapi
        palm_changed = settings.palm_usb_enabled != palm.usb.GetValue() or settings.show_hotsync_tray != palm.tray.GetValue()
        language = general.languages[general.language.GetSelection()]
        naming = general.namings[general.naming.GetSelection()]
        presentation_changed = language != settings.language or naming != settings.naming
        settings.frontend = windows_ce.keys[windows_ce.frontend.GetSelection()]
        settings.naming = naming
        settings.language = language
        settings.rapi_proxy = windows_ce.proxy.GetValue().strip()
        settings.network_device_rapi = device_rapi
        settings.palm_usb_enabled = palm.usb.GetValue()
        settings.show_hotsync_tray = palm.tray.GetValue()
        settings.save()
        set_naming(naming)
        self.EndModal(wx.ID_OK)
        if presentation_changed:
            wx.MessageBox(_("Naming and language changes take effect the next time {product} starts.").format(product=PRODUCT_NAME),
                          PRODUCT_NAME, wx.OK | wx.ICON_INFORMATION)
        self.application.apply_settings(connection_changed)
        if palm_changed:
            self.application.apply_palm_settings()


def show_preferences(parent, application, page=PAGE_GENERAL):
    with PreferencesDialog(parent, application, page) as dialog:
        dialog.ShowModal()
