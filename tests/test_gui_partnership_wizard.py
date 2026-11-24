from types import SimpleNamespace

import pytest

wx = pytest.importorskip("wx")

from classicsync.gui.frontends.ceservices22 import partnership_wizard  # noqa: E402
from classicsync.gui.frontends.ceservices22.artwork import CeServicesArtwork  # noqa: E402
from classicsync.gui.frontends.ceservices22.partnership_wizard import (  # noqa: E402
    PAGE_COMPLETE, PAGE_LIMIT, PAGE_NAME, PAGE_SUCCESS, NewPartnershipWizard,
)
from classicsync.sync.partners import DevicePartner, DevicePartners  # noqa: E402


@pytest.fixture(scope="module")
def app():
    application = wx.App(False)
    yield application
    application.Destroy()


class FakeApplication:
    def __init__(self, partners):
        self.device_details = {"name": "Handheld_PC", "description": ""}
        self.device_partners = DevicePartners(partners=partners)
        self.partnership = None
        self.settings = SimpleNamespace(sync_mode="manual", save=lambda: None)
        self.created = []
        self.removed = []

    def partnerships(self):
        return [SimpleNamespace(name="Taken")]

    def remove_device_partner(self, slot, finished):
        self.removed.append(slot)
        self.device_partners.partners = [partner for partner in self.device_partners.partners if partner.slot != slot]
        finished(self.device_partners, None)

    def create_partnership(self, finished, name=None, exclusive=False, description=None):
        self.created.append((name, exclusive, description))
        self.partnership = SimpleNamespace(load_options=lambda: SimpleNamespace(object_types=None), save_options=lambda options: None)
        finished(self.partnership, None)


def make_wizard(partners):
    application = FakeApplication(partners)
    frontend = SimpleNamespace(application=application, artwork=CeServicesArtwork(), sync=SimpleNamespace(object_types=lambda: []))
    return NewPartnershipWizard(None, frontend), application


def test_full_device_must_lose_a_partner_before_continuing(app):
    wizard, application = make_wizard([DevicePartner(1, 11, "OLDPC1"), DevicePartner(2, 22, "OLDPC2")])
    wizard.on_next(None)
    assert wizard.current == PAGE_NAME
    wizard.description.SetValue("Velo 500")
    wizard.on_next(None)
    assert wizard.current == PAGE_LIMIT
    assert not wizard.next.IsEnabled()
    wizard.existing.SetSelection(0)
    wizard.on_delete(None)
    assert len(application.removed) == 1 and wizard.next.IsEnabled()
    wizard.on_next(None)
    assert wizard.current == PAGE_SUCCESS
    assert application.created == [("Handheld_PC", False, "Velo 500")]
    wizard.Destroy()


def test_one_other_partner_asks_single_or_multiple(app, monkeypatch):
    class ChooseSingle:
        def __init__(self, parent):
            self.choice = partnership_wizard.CHOICE_SINGLE

        def __enter__(self):
            return self

        def __exit__(self, *exception):
            return False

        def ShowModal(self):
            return wx.ID_OK

    monkeypatch.setattr(partnership_wizard, "MultiplePartnershipDialog", ChooseSingle)
    wizard, application = make_wizard([DevicePartner(1, 11, "OLDPC1")])
    wizard.on_next(None)
    wizard.on_next(None)
    assert application.created == [("Handheld_PC", True, "")]
    for _step in range(3):
        wizard.on_next(None)
    assert wizard.current == PAGE_COMPLETE
    wizard.Destroy()


def test_taken_and_invalid_names_are_refused(app, monkeypatch):
    shown = []
    monkeypatch.setattr(wx, "MessageBox", lambda text, title, *args: shown.append(title))
    wizard, application = make_wizard([])
    wizard.on_next(None)
    for name in ("Taken", "has space"):
        wizard.name.SetValue(name)
        wizard.on_next(None)
        assert wizard.current == PAGE_NAME
    assert shown == ["Device Name In Use", "Invalid Character in Mobile Device Name"]
    assert application.created == []
    wizard.Destroy()
