import asyncio
import os

import pytest
from fake_device import FakeRapiClient

from classicsync.rapi.cedb import CEVT_LPWSTR, CEVT_UI2, PropertyValue
from classicsync.rapi.structures import filetime_to_datetime
from classicsync.sync import Partnership, SyncOptions, synchronize, unresolved_items
from classicsync.sync.pim.record import property_map


@pytest.fixture
def folder_sync(tmp_path):
    client = FakeRapiClient(name="Velo")
    root = tmp_path / "Velo"
    partnership = Partnership.for_device("Velo", tmp_path / "partnerships")

    def run(**option_values):
        options = SyncOptions(provider_settings={"folder": str(root)}, **option_values)
        return asyncio.run(synchronize(client, partnership, options))

    run.partnership = partnership
    return client, root, run


def test_files_mirror_both_ways_with_timestamps(folder_sync):
    client, root, run = folder_sync
    client.put_file("\\My Documents\\notes.txt", b"from device", modified=125000000000000000)
    (root / "My Documents" / "Letters").mkdir(parents=True)
    (root / "My Documents" / "Letters" / "letter.txt").write_bytes(b"from desktop")
    run(object_types=["files"])
    local = root / "My Documents" / "notes.txt"
    assert local.read_bytes() == b"from device"
    assert local.stat().st_mtime == filetime_to_datetime(125000000000000000).timestamp()
    assert client.file("\\My Documents\\Letters\\letter.txt") == b"from desktop"
    assert run(object_types=["files"]).counts() == {}


def test_file_conflict_keeps_both_copies(folder_sync):
    client, root, run = folder_sync
    client.put_file("\\My Documents\\a.txt", b"one")
    run(object_types=["files"])
    client.put_file("\\My Documents\\a.txt", b"device edit")
    local = root / "My Documents" / "a.txt"
    local.write_bytes(b"desktop edit")
    os.utime(local, (1, 1))
    run(object_types=["files"])
    assert local.read_bytes() == b"desktop edit"
    assert (root / "My Documents" / "a (Velo).txt").read_bytes() == b"device edit"
    assert client.file("\\My Documents\\a.txt") == b"desktop edit"
    assert client.file("\\My Documents\\a (Velo).txt") == b"device edit"
    assert run(object_types=["files"]).counts() == {}


def test_file_deletes_go_to_trash_and_device(folder_sync):
    client, root, run = folder_sync
    client.put_file("\\My Documents\\gone.txt", b"x")
    client.put_file("\\My Documents\\kept.txt", b"y")
    run(object_types=["files"])
    del client.files["\\my documents\\gone.txt"]
    (root / "My Documents" / "kept.txt").unlink()
    run(object_types=["files"])
    assert not (root / "My Documents" / "gone.txt").exists()
    assert list((root / ".trash").rglob("gone.txt"))
    assert "\\my documents\\kept.txt" not in client.files


def test_same_file_on_both_sides_at_first_sync_is_matched(folder_sync):
    client, root, run = folder_sync
    client.put_file("\\My Documents\\same.txt", b"same")
    (root / "My Documents").mkdir(parents=True)
    (root / "My Documents" / "same.txt").write_bytes(b"same")
    report = run(object_types=["files"])
    assert report.counts() == {}
    assert [action.action for action in report.actions] == ["match"]


def test_contacts_round_trip_through_vcard(folder_sync):
    client, root, run = folder_sync
    oid = client.add_record("Contacts Database", [
        PropertyValue(0x3A06, CEVT_LPWSTR, "Ada"), PropertyValue(0x3A11, CEVT_LPWSTR, "Lovelace"),
        PropertyValue(0x7777, CEVT_UI2, 5),
    ])
    run(object_types=["contacts"])
    cards = list((root / "Contacts").glob("*.vcf"))
    assert len(cards) == 1
    assert (root / "Contacts" / "raw" / f"{oid:08x}.json").exists()
    cards[0].write_text(cards[0].read_text().replace("N:Lovelace;Ada", "N:Byron;Ada").replace(
        "END:VCARD", "EMAIL:ada@example.org\r\nEND:VCARD"))
    (root / "Contacts" / "grace.vcf").write_text("BEGIN:VCARD\nVERSION:4.0\nN:Hopper;Grace;;;\nEND:VCARD\n")
    report = run(object_types=["contacts"])
    assert report.counts() == {"update to device": 1, "add to device": 1}
    values = property_map(client.databases["Contacts Database"][oid])
    assert values[(0x3A11, CEVT_LPWSTR)] == "Byron"
    assert values[(0x4083, CEVT_LPWSTR)] == "ada@example.org"
    assert values[(0x7777, CEVT_UI2)] == 5
    surnames = sorted(property_map(record)[(0x3A11, CEVT_LPWSTR)] for record in client.databases["Contacts Database"].values())
    assert surnames == ["Byron", "Hopper"]
    assert run(object_types=["contacts"]).counts() == {}
    del client.databases["Contacts Database"][oid]
    run(object_types=["contacts"])
    assert sorted(path.name for path in (root / "Contacts").glob("*.vcf")) == ["grace.vcf"]


def test_missing_database_is_skipped(folder_sync):
    client, root, run = folder_sync
    del client.databases["Tasks Database"]
    report = run(object_types=["tasks", "contacts"])
    assert report.skipped_types == ["tasks"]


def test_unresolved_contact_describes_both_sides(folder_sync):
    client, root, run = folder_sync
    oid = client.add_record("Contacts Database", [PropertyValue(0x3A06, CEVT_LPWSTR, "Ada"),
                                                  PropertyValue(0x3A11, CEVT_LPWSTR, "Lovelace")])
    run(object_types=["contacts"])
    card = next((root / "Contacts").glob("*.vcf"))
    card.write_text(card.read_text().replace("Lovelace", "King"))
    client.databases["Contacts Database"][oid] = [PropertyValue(0x3A06, CEVT_LPWSTR, "Ada"),
                                                  PropertyValue(0x3A11, CEVT_LPWSTR, "Byron")]
    assert len(run(object_types=["contacts"], conflict={"contacts": "skip"}).unresolved) == 1
    item = unresolved_items(run.partnership)[0]
    assert item.desktop == [card.name, "Name: Ada King"]
    assert item.device == ["Ada Byron", "Name: Ada Byron"]


def contact(given, surname):
    return [PropertyValue(0x3A06, CEVT_LPWSTR, given), PropertyValue(0x3A11, CEVT_LPWSTR, surname)]


def test_duplicates_found_after_first_sync_are_removed_on_both_sides(folder_sync):
    client, root, run = folder_sync
    first = client.add_record("Contacts Database", contact("Ada", "Lovelace"))
    second = client.add_record("Contacts Database", contact("Ada", "Lovelace"))
    client.add_record("Contacts Database", contact("Grace", "Hopper"))
    found = []

    def remove_all(duplicates):
        found.append(duplicates)
        return [item_id for group in duplicates.groups for item_id, _ in group.extras]

    options = SyncOptions(provider_settings={"folder": str(root)}, object_types=["contacts"])
    report = asyncio.run(synchronize(client, run.partnership, options, duplicates=remove_all))
    [duplicates] = found
    assert len(duplicates.groups) == 1 and len(duplicates.groups[0].extras) == 1
    assert len(list((root / "Contacts").glob("*.vcf"))) == 2
    assert len(client.databases["Contacts Database"]) == 2
    assert first in client.databases["Contacts Database"] or second in client.databases["Contacts Database"]
    assert report.counts().get("delete to device") == 1
    assert run(object_types=["contacts"]).counts() == {}


def test_duplicates_are_only_searched_on_request_after_the_first_sync(folder_sync):
    client, root, run = folder_sync
    client.add_record("Contacts Database", contact("Ada", "Lovelace"))
    run(object_types=["contacts"])
    client.add_record("Contacts Database", contact("Ada", "Lovelace"))
    asked = []
    options = SyncOptions(provider_settings={"folder": str(root)}, object_types=["contacts"])
    asyncio.run(synchronize(client, run.partnership, options, duplicates=lambda found: asked.append(found) or []))
    assert asked == []
    asyncio.run(synchronize(client, run.partnership, options, duplicates=lambda found: asked.append(found) or [], find_duplicates=True))
    assert len(asked) == 1
    assert len(client.databases["Contacts Database"]) == 2
