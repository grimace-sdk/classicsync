import wx

from classicsync.gui.common.new_device import CHOICE_GUEST, CHOICE_PARTNERSHIP, NewDeviceDialog
from classicsync.gui.frontends.activesync31.partnership_wizard import PAGE_COMPLETE, NewPartnershipWizard
from classicsync.gui.frontends.hpcexplorer11.partner_wizard import FINISH_PAGES, PartnerWizard


def answer_wizard(wizard, create):
    (wizard.partnership_yes if create else wizard.partnership_no).SetValue(True)
    while wizard.current != PAGE_COMPLETE:
        wizard.on_next(None)
    wizard.on_next(None)


def answer_partner_wizard(wizard, on_page=None, interval=400):
    wizard.backed_up = True
    wizard.synchronized = True

    def step():
        if not wizard:
            return
        if on_page:
            on_page(wizard)
        if wizard.creating:
            wx.CallLater(interval, step)
            return
        finishing = wizard.current in FINISH_PAGES
        wizard.on_next(None)
        if not finishing:
            wx.CallLater(interval, step)
    wx.CallLater(interval, step)


partner_wizard_page = None


def answer_partnership_prompts(create, interval=250, skip_backup=True):
    answered = []

    def poll():
        for window in wx.GetTopLevelWindows():
            if not window.IsShown() or any(window is seen for seen in answered):
                continue
            answered.append(window)
            if isinstance(window, NewPartnershipWizard):
                answer_wizard(window, create)
            elif isinstance(window, PartnerWizard):
                answer_partner_wizard(window, partner_wizard_page)
            elif isinstance(window, NewDeviceDialog):
                window.choose(CHOICE_PARTNERSHIP if create else CHOICE_GUEST)
            elif skip_backup and type(window).__name__ == "BackupNotCompleteDialog":
                window.EndModal(wx.ID_CANCEL)
        wx.CallLater(interval, poll)
    wx.CallLater(interval, poll)
