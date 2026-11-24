import wx

from classicsync.gui.common.new_device import CHOICE_GUEST, CHOICE_PARTNERSHIP, NewDeviceDialog
from classicsync.gui.frontends.activesync31.partnership_wizard import PAGE_COMPLETE, NewPartnershipWizard


def answer_wizard(wizard, create):
    (wizard.partnership_yes if create else wizard.partnership_no).SetValue(True)
    while wizard.current != PAGE_COMPLETE:
        wizard.on_next(None)
    wizard.on_next(None)


def answer_partnership_prompts(create, interval=250, skip_backup=True):
    answered = []

    def poll():
        for window in wx.GetTopLevelWindows():
            if not window.IsShown() or any(window is seen for seen in answered):
                continue
            answered.append(window)
            if isinstance(window, NewPartnershipWizard):
                answer_wizard(window, create)
            elif isinstance(window, NewDeviceDialog):
                window.choose(CHOICE_PARTNERSHIP if create else CHOICE_GUEST)
            elif skip_backup and type(window).__name__ == "BackupNotCompleteDialog":
                window.EndModal(wx.ID_CANCEL)
        wx.CallLater(interval, poll)
    wx.CallLater(interval, poll)
