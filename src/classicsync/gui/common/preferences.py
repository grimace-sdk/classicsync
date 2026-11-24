import wx

from ...i18n import _, available_languages
from ..branding import disclaimer, NAMING_AUTHENTIC, NAMING_CLASSICSYNC, PRODUCT_NAME, set_naming
from ..frontends import AUTOMATIC, FRONTENDS, frontend_label
from .layout import dialog_size, place


def language_label(code):
    info = wx.Locale.FindLanguageInfo(code)
    return f"{info.Description} ({code})" if info else code


class PreferencesDialog(wx.Dialog):
    def __init__(self, parent, application):
        super().__init__(parent, title=_("{product} Settings").format(product=PRODUCT_NAME))
        self.application = application
        settings = application.settings
        self.SetClientSize(dialog_size(self, 240, 196))
        place(self, wx.StaticText, 8, 8, 224, 18,
              _("Choose which desktop software to recreate. Automatic matches the software to the device's version of Windows CE."))
        place(self, wx.StaticText, 8, 34, 62, 9, _("&Desktop software:"))
        self.keys = [AUTOMATIC] + [key for key in FRONTENDS if key in application.frontend_classes]
        self.frontend = place(self, wx.Choice, 72, 32, 160, 12, choices=[frontend_label(key) for key in self.keys])
        self.frontend.SetSelection(self.keys.index(settings.frontend) if settings.frontend in self.keys else 0)
        place(self, wx.StaticText, 8, 52, 62, 9, _("&Naming:"))
        self.namings = [NAMING_CLASSICSYNC, NAMING_AUTHENTIC]
        self.naming = place(self, wx.Choice, 72, 50, 160, 12,
                            choices=[PRODUCT_NAME, _("Authentic (original product names)")])
        self.naming.SetSelection(self.namings.index(settings.naming) if settings.naming in self.namings else 0)
        place(self, wx.StaticText, 8, 70, 62, 9, _("&Language:"))
        self.languages = [""] + available_languages()
        self.language = place(self, wx.Choice, 72, 68, 160, 12,
                              choices=[_("System default")] + [language_label(code) for code in self.languages[1:]])
        self.language.SetSelection(self.languages.index(settings.language) if settings.language in self.languages else 0)
        place(self, wx.StaticText, 8, 88, 62, 9, _("&Local RAPI address:"))
        self.proxy = place(self, wx.TextCtrl, 72, 86, 90, 12, settings.rapi_proxy)
        place(self, wx.StaticText, 72, 101, 160, 18, _("Command-line tools reach the connected device here."))
        place(self, wx.StaticLine, 8, 124, 224, 1)
        place(self, wx.StaticText, 8, 130, 224, 36, disclaimer())
        place(self, wx.Button, 128, 176, 50, 14, _("OK"), id=wx.ID_OK).SetDefault()
        place(self, wx.Button, 182, 176, 50, 14, _("Cancel"), id=wx.ID_CANCEL)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.CentreOnScreen()

    def on_ok(self, event):
        settings = self.application.settings
        proxy_changed = settings.rapi_proxy != self.proxy.GetValue().strip()
        language = self.languages[self.language.GetSelection()]
        naming = self.namings[self.naming.GetSelection()]
        presentation_changed = language != settings.language or naming != settings.naming
        settings.frontend = self.keys[self.frontend.GetSelection()]
        settings.naming = naming
        settings.language = language
        settings.rapi_proxy = self.proxy.GetValue().strip()
        settings.save()
        set_naming(naming)
        self.EndModal(wx.ID_OK)
        if presentation_changed:
            wx.MessageBox(_("Naming and language changes take effect the next time {product} starts.").format(product=PRODUCT_NAME),
                          PRODUCT_NAME, wx.OK | wx.ICON_INFORMATION)
        self.application.apply_settings(proxy_changed)


def show_preferences(parent, application):
    with PreferencesDialog(parent, application) as dialog:
        dialog.ShowModal()
