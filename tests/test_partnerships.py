import asyncio
import json

import pytest
from fake_device import FakeRapiClient
from test_sync_engine import MemoryProvider, desktop_subjects, device_subjects, text

from classicsync.sync import (
    FIRST_SYNC_COMBINE, FIRST_SYNC_REPLACE, FIRST_SYNC_SKIP, NoPartnership, Partnership, PartnershipError, SyncOptions,
    create_partnership, delete_partnership, find_partnership, read_device_partners, set_resolutions, synchronize,
    unresolved_items,
)
from classicsync.sync.partners import PARTNERS_KEY, valid_device_name

P1 = PARTNERS_KEY + "\\P1"
P2 = PARTNERS_KEY + "\\P2"


def run(coroutine):
    return asyncio.run(coroutine)


def test_partnership_is_written_to_the_device_and_recognised(tmp_path):
    client = FakeRapiClient(name="Velo")
    base = tmp_path / "partnerships"
    assert run(find_partnership(client, base=base)).partnership is None
    partnership = run(create_partnership(client, base=base))
    assert partnership.explicit and partnership.name == "Velo"
    assert client.registry_value(P1, "PId") == partnership.partner_id
    assert client.registry_value(P1, "PName") == partnership.desktop_name
    assert client.registry_value(PARTNERS_KEY, "PCur") == 1
    info = json.loads((partnership.directory / "partnership.json").read_text())
    assert info["partner_id"] == partnership.partner_id
    found = run(find_partnership(client, base=base)).partnership
    assert found.directory == partnership.directory and found.partner_id == partnership.partner_id
    client.name = "Renamed"
    assert run(find_partnership(client, base=base)).partnership.partner_id == partnership.partner_id
    other_desktop = run(find_partnership(FakeRapiClient(name="Velo"), base=base))
    assert other_desktop.partnership is None


def test_announced_partner_ids_match_without_the_registry(tmp_path):
    client = FakeRapiClient(name="Velo")
    base = tmp_path / "partnerships"
    partnership = run(create_partnership(client, base=base))
    stranger = FakeRapiClient(name="Other")
    assert run(find_partnership(stranger, announced_ids=(0, partnership.partner_id), base=base)).partnership is not None


def test_two_partnerships_per_device(tmp_path):
    client = FakeRapiClient(name="Velo")
    first = run(create_partnership(client, base=tmp_path / "first"))
    second = run(create_partnership(client, base=tmp_path / "second"))
    partners = run(read_device_partners(client))
    assert partners.partner_ids == [first.partner_id, second.partner_id] and partners.full
    with pytest.raises(PartnershipError):
        run(create_partnership(client, base=tmp_path / "third"))
    third = run(create_partnership(client, base=tmp_path / "third", exclusive=True))
    assert run(read_device_partners(client)).partner_ids == [third.partner_id]
    assert run(find_partnership(client, base=tmp_path / "first")).partnership is None


def test_version_one_device_keeps_one_partner_in_ident(tmp_path):
    client = FakeRapiClient(name="HPC", os_major=1)
    partnership = run(create_partnership(client, base=tmp_path / "a"))
    assert client.registry_value("Ident", "PartnerId") == partnership.partner_id
    partners = run(read_device_partners(client))
    assert partners.legacy and partners.full and not partners.services_supported
    assert run(find_partnership(client, base=tmp_path / "a")).partnership.partner_id == partnership.partner_id
    with pytest.raises(PartnershipError):
        run(create_partnership(client, base=tmp_path / "b"))


def test_delete_clears_the_device_slot(tmp_path):
    client = FakeRapiClient(name="Velo")
    base = tmp_path / "partnerships"
    partnership = run(create_partnership(client, base=base))
    (partnership.directory / "backup.stg").write_bytes(b"kept")
    run(delete_partnership(partnership, client))
    assert run(read_device_partners(client)).partner_ids == []
    assert Partnership.list_all(base)[0].explicit is False
    assert not partnership.info_path.exists() and (partnership.directory / "backup.stg").exists()
    assert valid_device_name("Velo_500") and not valid_device_name("5Velo") and not valid_device_name("My Velo")


def test_implicit_partnership_is_migrated(tmp_path, monkeypatch):
    monkeypatch.setenv("CLASSICSYNC_HOME", str(tmp_path))
    client = FakeRapiClient(name="HPC")
    base = tmp_path / "partnerships"
    MemoryProvider.items = {}
    client.add_record("Contacts Database", [text("kept")])
    implicit = Partnership.for_device("HPC", base)
    run(synchronize(client, implicit, SyncOptions(provider="memory"), providers={"memory": MemoryProvider}))
    lookup = run(find_partnership(client, base=base))
    assert lookup.migrated and lookup.partnership.directory == implicit.directory
    assert client.registry_value(P1, "PId") == lookup.partnership.partner_id
    report = run(synchronize(client, None, SyncOptions(provider="memory"), providers={"memory": MemoryProvider}))
    assert report.counts() == {}


def test_guests_do_not_synchronize(tmp_path, monkeypatch):
    monkeypatch.setenv("CLASSICSYNC_HOME", str(tmp_path))
    with pytest.raises(NoPartnership):
        run(synchronize(FakeRapiClient(), None, SyncOptions(provider="memory"), providers={"memory": MemoryProvider}))


@pytest.fixture
def both_sides(tmp_path):
    client = FakeRapiClient()
    MemoryProvider.items = {"shared": [text("shared desktop")], "desktop": [text("desktop only")]}
    client.add_record("Contacts Database", [text("device only")])
    client.add_record("Contacts Database", [text("shared device")])
    partnership = Partnership.for_device("HPC", tmp_path / "partnerships")
    questions = []

    def sync(choice, **option_values):
        def first_sync(question):
            questions.append((question.object_type.key, question.device_count, question.desktop_count))
            return choice
        options = SyncOptions(provider="memory", **option_values)
        return run(synchronize(client, partnership, options, providers={"memory": MemoryProvider}, first_sync=first_sync))

    return client, MemoryProvider.items, sync, questions, partnership


def matching_store(monkeypatch):
    from test_sync_engine import MemoryStore, subject_of

    def find_match(self, device_id, device_object, unmatched_item_ids):
        wanted = subject_of(device_object.properties).split()[0]
        return next((item_id for item_id in unmatched_item_ids if subject_of(self.items[item_id]).split()[0] == wanted), None)

    monkeypatch.setattr(MemoryStore, "find_match", find_match, raising=False)


def test_first_sync_combine(both_sides, monkeypatch):
    matching_store(monkeypatch)
    client, items, sync, questions, _ = both_sides
    report = sync(FIRST_SYNC_COMBINE, conflict={"notes": "desktop"})
    assert questions == [("notes", 2, 2)] and report.first_sync == {"notes": "combine"}
    assert device_subjects(client) == desktop_subjects(items) == ["desktop only", "device only", "shared desktop"]
    sync(FIRST_SYNC_COMBINE)
    assert len(questions) == 1


def test_first_sync_replace(both_sides, monkeypatch):
    matching_store(monkeypatch)
    client, items, sync, questions, _ = both_sides
    report = sync(FIRST_SYNC_REPLACE)
    assert report.counts() == {"add to device": 1, "delete to device": 1, "update to device": 1}
    assert device_subjects(client) == desktop_subjects(items) == ["desktop only", "shared desktop"]
    assert sync(FIRST_SYNC_REPLACE).counts() == {}


def test_first_sync_skip_asks_again(both_sides):
    client, items, sync, questions, partnership = both_sides
    report = sync(FIRST_SYNC_SKIP)
    assert report.skipped_types == ["notes"] and report.counts() == {}
    assert device_subjects(client) == ["device only", "shared device"]
    assert "notes" not in partnership.load_state()["types"]
    sync(FIRST_SYNC_COMBINE)
    assert len(questions) == 2


def test_first_sync_not_asked_when_one_side_is_empty(tmp_path):
    client = FakeRapiClient()
    MemoryProvider.items = {}
    client.add_record("Contacts Database", [text("device only")])
    asked = []
    run(synchronize(client, Partnership.for_device("HPC", tmp_path), SyncOptions(provider="memory"),
                    providers={"memory": MemoryProvider}, first_sync=asked.append))
    assert asked == [] and desktop_subjects(MemoryProvider.items) == ["device only"]


def test_unresolved_items_persist_until_resolved(tmp_path):
    client = FakeRapiClient()
    MemoryProvider.items = {}
    partnership = Partnership.for_device("HPC", tmp_path / "partnerships")
    oid = client.add_record("Contacts Database", [text("original")])

    def sync():
        options = SyncOptions(provider="memory", conflict={"notes": "skip"})
        return run(synchronize(client, partnership, options, providers={"memory": MemoryProvider}))

    sync()
    item_id = next(iter(MemoryProvider.items))
    client.databases["Contacts Database"][oid] = [text("device edit")]
    MemoryProvider.items[item_id] = [text("desktop edit")]
    assert len(sync().unresolved) == 1
    pending = unresolved_items(partnership)
    assert [(item.object_type, item.device_id, item.desktop_id) for item in pending] == [("notes", f"{oid:08x}", item_id)]
    assert pending[0].desktop == [item_id] and pending[0].resolution == "skip"
    assert len(sync().unresolved) == 1
    pending[0].resolution = "device"
    set_resolutions(partnership, pending)
    assert unresolved_items(partnership)[0].resolution == "device"
    report = sync()
    assert [action.resolution for action in report.actions] == ["device"] and not report.unresolved
    assert report.counts() == {"update to desktop": 1}
    assert desktop_subjects(MemoryProvider.items) == ["device edit"]
    assert unresolved_items(partnership) == []
    with pytest.raises(ValueError):
        pending[0].resolution = "keep_both"
        set_resolutions(partnership, pending)
