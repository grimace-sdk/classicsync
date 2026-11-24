import asyncio
import os

import pytest
from fake_device import FakeRapiClient

from classicsync.rapi.cedb import CEVT_I4, CEVT_LPWSTR, PropertyValue
from classicsync.sync import DeviceRecord, ObjectType, Partnership, Provider, Store, SyncOptions, synchronize
from classicsync.sync.rawjson import properties_hash

NOTES = ObjectType("notes", "Note", "Notes", database="Contacts Database")


def text(value, identifier=0x0037):
    return PropertyValue(identifier, CEVT_LPWSTR, value)


def subject_of(properties):
    return next(prop.value for prop in properties if prop.identifier == 0x0037)


class MemoryStore(Store):
    object_type = NOTES

    def __init__(self, items):
        self.items = items
        self.counter = len(items)

    def list_items(self):
        return {item_id: properties_hash(properties) for item_id, properties in self.items.items()}

    def read_item(self, item_id, device_id):
        return DeviceRecord(list(self.items[item_id]))

    def write_item(self, item_id, device_id, device_object):
        if item_id is None:
            self.counter += 1
            item_id = f"item{self.counter}"
        self.items[item_id] = list(device_object.properties)
        return item_id, properties_hash(self.items[item_id])

    def delete_item(self, item_id, device_id):
        del self.items[item_id]


class MemoryProvider(Provider):
    name = "memory"
    object_types = (NOTES,)
    items = {}

    def open_store(self, object_type):
        return MemoryStore(self.items)


@pytest.fixture
def setup(tmp_path):
    client = FakeRapiClient()
    MemoryProvider.items = {}
    partnership = Partnership.for_device("HPC", tmp_path / "partnerships")

    def run(**option_values):
        options = SyncOptions(provider="memory", **option_values)
        return asyncio.run(synchronize(client, partnership, options, providers={"memory": MemoryProvider}))

    return client, MemoryProvider.items, run


def device_subjects(client):
    return sorted(subject_of(properties) for properties in client.databases["Contacts Database"].values())


def desktop_subjects(items):
    return sorted(subject_of(properties) for properties in items.values())


def test_first_sync_combines_both_sides(setup):
    client, items, run = setup
    client.add_record("Contacts Database", [text("from device"), PropertyValue(0x9999, CEVT_I4, 7)])
    items["mine"] = [text("from desktop")]
    report = run()
    assert device_subjects(client) == desktop_subjects(items) == ["from desktop", "from device"]
    assert report.counts() == {"add to desktop": 1, "add to device": 1}
    assert run().counts() == {}


def test_changes_and_deletes_flow_both_ways(setup):
    client, items, run = setup
    oid = client.add_record("Contacts Database", [text("a"), PropertyValue(0x9999, CEVT_I4, 7)])
    items["b"] = [text("b")]
    run()
    client.databases["Contacts Database"][oid] = [text("a2")]
    desktop_id = next(item_id for item_id, properties in items.items() if subject_of(properties) == "b")
    items[desktop_id] = [text("b2")]
    assert run().counts() == {"update to desktop": 1, "update to device": 1}
    assert device_subjects(client) == desktop_subjects(items) == ["a2", "b2"]
    a_item = next(item_id for item_id, properties in items.items() if subject_of(properties) == "a2")
    assert items[a_item] == [text("a2")]
    del client.databases["Contacts Database"][oid]
    del items[desktop_id]
    assert run().counts() == {"delete to desktop": 1, "delete to device": 1}
    assert device_subjects(client) == desktop_subjects(items) == []


def test_update_removes_properties_dropped_on_desktop(setup):
    client, items, run = setup
    oid = client.add_record("Contacts Database", [text("a"), text("old", 0x4208)])
    run()
    item_id = next(iter(items))
    items[item_id] = [text("a")]
    run()
    assert client.databases["Contacts Database"][oid] == [text("a")]


def make_conflict(setup):
    client, items, run = setup
    oid = client.add_record("Contacts Database", [text("original")])
    run()
    item_id = next(iter(items))
    client.databases["Contacts Database"][oid] = [text("device edit")]
    items[item_id] = [text("desktop edit")]
    return client, items, run


@pytest.mark.parametrize("policy, expected", [
    ("desktop", ["desktop edit"]),
    ("device", ["device edit"]),
    ("keep_both", ["desktop edit", "device edit"]),
])
def test_conflict_policies(setup, policy, expected):
    client, items, run = make_conflict(setup)
    report = run(conflict={"notes": policy})
    assert [action.resolution for action in report.actions] == [policy]
    assert device_subjects(client) == desktop_subjects(items) == expected
    assert run(conflict={"notes": policy}).counts() == {}


def test_unresolved_conflict_stays_until_resolved(setup):
    client, items, run = make_conflict(setup)
    assert len(run(conflict={"notes": "skip"}).unresolved) == 1
    assert device_subjects(client) == ["device edit"]
    assert desktop_subjects(items) == ["desktop edit"]
    assert len(run(conflict={"notes": "skip"}).unresolved) == 1
    run(conflict={"notes": "device"})
    assert desktop_subjects(items) == ["device edit"]


def test_change_beats_delete(setup):
    client, items, run = setup
    oid = client.add_record("Contacts Database", [text("a")])
    run()
    item_id = next(iter(items))
    del client.databases["Contacts Database"][oid]
    items[item_id] = [text("a edited")]
    assert run().counts() == {"add to device": 1}
    assert device_subjects(client) == ["a edited"]


def test_dry_run_changes_nothing(setup, tmp_path):
    client, items, run = setup
    client.add_record("Contacts Database", [text("a")])
    items["x"] = [text("b")]
    report = run(dry_run=True)
    assert report.counts() == {"add to desktop": 1, "add to device": 1}
    assert device_subjects(client) == ["a"]
    assert desktop_subjects(items) == ["b"]
    assert not (tmp_path / "partnerships" / "HPC" / "state.json").exists()


def test_progress_reports_each_action(setup, tmp_path):
    client, items, run = setup
    client.add_record("Contacts Database", [text("a")])
    updates = []
    options = SyncOptions(provider="memory")
    asyncio.run(synchronize(client, Partnership.for_device("HPC", tmp_path / "p2"), options, updates.append,
                            providers={"memory": MemoryProvider}))
    phases = [update.phase for update in updates]
    assert phases[0] == "start" and phases[-1] == "done" and "apply" in phases


def test_plugins_load_from_folder(tmp_path):
    from classicsync.sync.plugins import load_providers
    (tmp_path / "mine.py").write_text(
        "from classicsync.sync import Provider, CONTACTS\n"
        "class Mine(Provider):\n"
        "    name = 'mine'\n"
        "    object_types = (CONTACTS,)\n")
    providers = load_providers(tmp_path)
    assert "mine" in providers and "folder" in providers
    assert os.path.basename(providers["mine"].__module__).startswith("classicsync_sync_plugin_mine")
