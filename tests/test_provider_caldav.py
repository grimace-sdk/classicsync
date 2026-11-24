import asyncio
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest
from fake_dav import FakeDavServer
from fake_device import FakeRapiClient

from classicsync.cli_plugins import use_for_types
from classicsync.rapi import cedb
from classicsync.sync import CONTACTS, Partnership, ProviderError, SyncOptions, synchronize
from classicsync.sync import secrets
from classicsync.sync.engine import type_assignments
from classicsync.sync.folder import FolderProvider
from classicsync.sync.pim.merge import merge_component
from classicsync.sync.pim.record import property_map
from classicsync.sync.pim.vcard3 import vcard_to_version3, vcard_to_version4
from classicsync.sync.providers.caldav.dav import (
    C, D, KIND_ADDRESS_BOOK, KIND_CALENDAR, Collection, DavClient, parse_multistatus,
)
from classicsync.sync.providers.caldav.provider import CalDavProvider, DavStore
from classicsync.sync.settings_schema import effective_settings, protect_secrets, provider_schema

PROVIDERS = {"folder": FolderProvider, "caldav": CalDavProvider}
GIVEN_NAME = (0x3A06, cedb.CEVT_LPWSTR)
SURNAME = (0x3A11, cedb.CEVT_LPWSTR)
PAGER = (0x4009, cedb.CEVT_LPWSTR)
SUBJECT = (0x0037, cedb.CEVT_LPWSTR)
DURATION = (0x4213, cedb.CEVT_I4)
RADICALE_PYTHON = os.environ.get("CLASSICSYNC_RADICALE_PYTHON", "")

GRACE = ("BEGIN:VCARD\r\nVERSION:3.0\r\nUID:grace-1\r\nN:Hopper;Grace;;;\r\nFN:Grace Hopper\r\n"
         "PHOTO;ENCODING=b;TYPE=JPEG:AAAA\r\nitem1.EMAIL;type=INTERNET;type=pref:grace@example.com\r\n"
         "item1.X-ABLabel:_$!<Work>!$_\r\nEND:VCARD\r\n")
STANDUP = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\nBEGIN:VEVENT\r\nUID:standup-1\r\nDTSTAMP:20260101T000000Z\r\n"
           "DTSTART:20261201T100000Z\r\nDTEND:20261201T103000Z\r\nRRULE:FREQ=WEEKLY\r\nSUMMARY:Standup\r\n"
           "ATTENDEE:mailto:team@example.com\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
LAUNDRY = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\nBEGIN:VTODO\r\nUID:laundry-1\r\nDTSTAMP:20260101T000000Z\r\n"
           "SUMMARY:Laundry\r\nDUE:20261202T170000Z\r\nX-APPLE-SORT-ORDER:5\r\nEND:VTODO\r\nEND:VCALENDAR\r\n")


def test_multistatus_parsing_keeps_found_and_missing_properties():
    body = b"""<?xml version="1.0"?>
<x:multistatus xmlns:x="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
 <x:response><x:href>/cal/work/</x:href>
  <x:propstat><x:prop><x:displayname>Work</x:displayname><x:resourcetype><x:collection/><cal:calendar/></x:resourcetype>
   <cal:supported-calendar-component-set><cal:comp name="VTODO"/></cal:supported-calendar-component-set>
   <x:supported-report-set><x:supported-report><x:report><x:sync-collection/></x:report></x:supported-report></x:supported-report-set>
  </x:prop><x:status>HTTP/1.1 200 OK</x:status></x:propstat>
  <x:propstat><x:prop><x:getctag/></x:prop><x:status>HTTP/1.1 404 Not Found</x:status></x:propstat>
 </x:response>
 <x:response><x:href>/cal/work/gone.ics</x:href><x:status>HTTP/1.1 404 Not Found</x:status></x:response>
 <x:sync-token>token-7</x:sync-token>
</x:multistatus>"""
    entries, token = parse_multistatus(body)
    assert token == "token-7"
    work, gone = entries
    assert work.text(D + "displayname") == "Work"
    assert C + "calendar" in work.resource_types()
    assert work.components() == {"VTODO"}
    assert D + "sync-collection" in work.reports()
    assert "{http://calendarserver.org/ns/}getctag" not in work.properties
    assert gone.status == 404


def test_collection_holds_components():
    assert Collection("u", KIND_CALENDAR, components=frozenset({"VEVENT"})).holds("VEVENT")
    assert not Collection("u", KIND_CALENDAR, components=frozenset({"VEVENT"})).holds("VTODO")
    assert Collection("u", KIND_CALENDAR).holds("VTODO")
    assert Collection("u", KIND_ADDRESS_BOOK).holds("VCARD")


def test_vcard_version_conversion():
    version4 = ("BEGIN:VCARD\r\nVERSION:4.0\r\nFN:Ada\r\nN:Lovelace;Ada;;;\r\nEMAIL;PREF=1:ada@example.com\r\n"
                "RELATED;TYPE=spouse;VALUE=text:William\r\nANNIVERSARY:18350708\r\nEND:VCARD\r\n")
    version3 = vcard_to_version3(version4)
    assert "VERSION:3.0" in version3
    assert "EMAIL;TYPE=INTERNET,pref:ada@example.com" in version3
    assert "X-SPOUSE:William" in version3 and "X-ANNIVERSARY:1835-07-08" in version3
    back = vcard_to_version4(version3)
    assert "RELATED;TYPE=spouse;VALUE=text:William" in back and "ANNIVERSARY:1835-07-08" in back


def test_merge_keeps_remote_only_lines_and_equal_times():
    generated = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:other\r\nDTSTAMP:20261124T000000Z\r\n"
                 "DTSTART:20261201T100000Z\r\nDTEND:20261201T110000Z\r\nSUMMARY:Standup moved\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    existing = STANDUP.replace("DTSTART:20261201T100000Z", "DTSTART;TZID=UTC:20261201T100000")
    merged = merge_component(existing, generated, "VEVENT", {"DTSTAMP", "DTSTART", "DTEND", "SUMMARY"})
    assert "UID:standup-1" in merged and "UID:other" not in merged
    assert "RRULE:FREQ=WEEKLY" in merged and "ATTENDEE:mailto:team@example.com" in merged
    assert "DTSTART;TZID=UTC:20261201T100000" in merged
    assert "DTEND:20261201T110000Z" in merged
    assert "SUMMARY:Standup moved" in merged


def test_merge_drops_orphaned_apple_labels():
    generated = "BEGIN:VCARD\r\nVERSION:4.0\r\nFN:Grace Hopper\r\nN:Hopper;Grace;;;\r\nEND:VCARD\r\n"
    merged = merge_component(GRACE, generated, "VCARD", {"FN", "N", "EMAIL"})
    assert "X-ABLabel" not in merged and "EMAIL" not in merged
    assert "PHOTO;ENCODING=b;TYPE=JPEG:AAAA" in merged and "VERSION:3.0" in merged


class FakeKeyring:
    def __init__(self):
        self.saved = {}

    def set_password(self, service, account, value):
        self.saved[(service, account)] = value

    def get_password(self, service, account):
        return self.saved.get((service, account))

    def delete_password(self, service, account):
        self.saved.pop((service, account), None)


def test_secret_settings_go_to_the_keyring(monkeypatch, tmp_path):
    keyring = FakeKeyring()
    monkeypatch.setattr(secrets, "keyring_backend", lambda: keyring)
    schema = provider_schema(CalDavProvider)
    changes = protect_secrets(schema, {"caldav_password": "app-password", "caldav_username": "ada"}, "caldav", "Velo")
    assert changes["caldav_username"] == "ada"
    assert changes["caldav_password"] == {"keyring": "caldav/Velo/caldav_password"}
    options = SyncOptions(provider="caldav", provider_settings=changes)
    assert effective_settings(CalDavProvider, options, tmp_path)["caldav_password"] == "app-password"
    password_setting = next(setting for setting in schema if setting.key == "caldav_password")
    assert "app-password" not in password_setting.format(changes["caldav_password"])
    protect_secrets(schema, {"caldav_password": None}, "caldav", "Velo")
    assert not keyring.saved


def test_secret_settings_stay_in_the_file_without_keyring(monkeypatch):
    monkeypatch.setattr(secrets, "keyring_backend", lambda: None)
    changes = protect_secrets(provider_schema(CalDavProvider), {"caldav_password": "app-password"}, "caldav", "all")
    assert changes["caldav_password"] == "app-password"


def test_discovery_finds_collections_through_well_known():
    with FakeDavServer() as server:
        client = DavClient(server.url + ".well-known/caldav", "ada", "secret")
        calendars = client.collections(KIND_CALENDAR)
        assert {collection.name for collection in calendars} == {"Personal", "Tasks"}
        assert all(collection.sync_supported for collection in calendars)
        address_books = DavClient(server.url, "ada", "secret").collections(KIND_ADDRESS_BOOK)
        assert [collection.name for collection in address_books] == ["Contacts"]


def caldav_options(url, **settings):
    return SyncOptions(provider="caldav", object_types=["contacts", "calendar", "tasks"],
                       provider_settings={"caldav_url": url, "caldav_username": "ada", "caldav_password": "secret", **settings})


def run_sync(client, partnership, options):
    report = asyncio.run(synchronize(client, partnership, options, providers=PROVIDERS))
    assert not [action for action in report.actions if action.error], report.actions
    assert not report.errors, report.errors
    return report


def device_records(client, database):
    return {oid: property_map(properties) for oid, properties in client.databases[database].items()}


def add_device_contact(client, given, surname, extra=()):
    return client.add_record("Contacts Database", [cedb.PropertyValue(*GIVEN_NAME, given), cedb.PropertyValue(*SURNAME, surname),
                                                   *extra])


@pytest.mark.parametrize("sync_collection", [True, False])
def test_two_way_sync_with_dav_server(tmp_path, sync_collection):
    client = FakeRapiClient()
    partnership = Partnership.for_device("HPC", tmp_path / "partnerships")
    ada_oid = add_device_contact(client, "Ada", "Lovelace", [cedb.PropertyValue(*PAGER, "pager kept"),
                                                            cedb.PropertyValue(0x0001, cedb.CEVT_LPWSTR, "unknown kept")])
    with FakeDavServer(sync_collection=sync_collection) as server:
        server.collection("contacts").put("grace-1.vcf", GRACE)
        server.collection("calendar").put("standup-1.ics", STANDUP)
        server.collection("tasks").put("laundry-1.ics", LAUNDRY)
        options = caldav_options(server.url)

        report = run_sync(client, partnership, options)
        assert report.counts() == {"add to desktop": 1, "add to device": 3}
        contacts = device_records(client, "Contacts Database")
        assert sorted(values[SURNAME] for values in contacts.values()) == ["Hopper", "Lovelace"]
        assert [values[SUBJECT] for values in device_records(client, "Appointments Database").values()] == ["Standup"]
        assert [values[SUBJECT] for values in device_records(client, "Tasks Database").values()] == ["Laundry"]
        cards = server.collection("contacts").items
        ada_name = next(name for name in cards if name != "grace-1.vcf")
        assert "N:Lovelace;Ada;;;" in cards[ada_name][0] and "VERSION:3.0" in cards[ada_name][0]

        assert run_sync(client, partnership, options).counts() == {}

        grace_oid = next(oid for oid, values in contacts.items() if values[SURNAME] == "Hopper")
        client.databases["Contacts Database"][grace_oid] = [
            prop if (prop.identifier, prop.value_type) != SURNAME else cedb.PropertyValue(*SURNAME, "Murray")
            for prop in client.databases["Contacts Database"][grace_oid]]
        server.collection("contacts").put(ada_name, cards[ada_name][0].replace("N:Lovelace;Ada", "N:Byron;Ada"))
        event = server.collection("calendar").items["standup-1.ics"][0]
        server.collection("calendar").put("standup-1.ics", event.replace("DTEND:20261201T103000Z", "DTEND:20261201T104500Z"))
        server.collection("tasks").delete("laundry-1.ics")

        report = run_sync(client, partnership, options)
        assert report.counts() == {"update to desktop": 1, "update to device": 2, "delete to device": 1}
        contacts = device_records(client, "Contacts Database")
        assert contacts[ada_oid][SURNAME] == "Byron"
        assert contacts[ada_oid][PAGER] == "pager kept"
        assert contacts[ada_oid][(0x0001, cedb.CEVT_LPWSTR)] == "unknown kept"
        grace = server.collection("contacts").items["grace-1.vcf"][0]
        assert "N:Murray;Grace;;;" in grace and "PHOTO;ENCODING=b;TYPE=JPEG:AAAA" in grace and "UID:grace-1" in grace
        assert [values[DURATION] for values in device_records(client, "Appointments Database").values()] == [45]
        assert not client.databases["Tasks Database"]

        appointment_oid = next(iter(client.databases["Appointments Database"]))
        client.databases["Appointments Database"][appointment_oid] = [
            prop if (prop.identifier, prop.value_type) != SUBJECT else cedb.PropertyValue(*SUBJECT, "Standup (room 2)")
            for prop in client.databases["Appointments Database"][appointment_oid]]
        report = run_sync(client, partnership, options)
        assert report.counts() == {"update to desktop": 1}
        event = server.collection("calendar").items["standup-1.ics"][0]
        assert "SUMMARY:Standup (room 2)" in event and "RRULE:FREQ=WEEKLY" in event and "ATTENDEE:mailto:team@example.com" in event
        updates = [request for request in server.requests if request[0] == "PUT" and "standup-1" in request[1]]
        assert updates[-1][2].get("If-Match")

        del client.databases["Contacts Database"][ada_oid]
        report = run_sync(client, partnership, options)
        assert report.counts() == {"delete to desktop": 1}
        assert ada_name not in server.collection("contacts").items
        assert run_sync(client, partnership, options).counts() == {}


def test_update_is_refused_when_the_server_copy_changed_meanwhile(tmp_path):
    with FakeDavServer() as server:
        server.collection("contacts").put("grace-1.vcf", GRACE)
        client = DavClient(server.url, "ada", "secret")
        collection = client.collections(KIND_ADDRESS_BOOK)[0]
        store = DavStore(CONTACTS, client, collection, tmp_path, 2)
        (href,) = store.list_items()
        record = store.read_item(href, None)
        server.collection("contacts").put("grace-1.vcf", GRACE.replace("Grace Hopper", "Grace B. Hopper"))
        with pytest.raises(ProviderError):
            store.write_item(href, "00001001", record)
        assert "Grace B. Hopper" in server.collection("contacts").items["grace-1.vcf"][0]


def test_server_rewriting_cards_without_etag(tmp_path):
    client = FakeRapiClient()
    partnership = Partnership.for_device("HPC", tmp_path / "partnerships")
    add_device_contact(client, "Ada", "Lovelace")
    with FakeDavServer(rewrite_on_put=True) as server:
        options = caldav_options(server.url)
        options.object_types = ["contacts"]
        assert run_sync(client, partnership, options).counts() == {"add to desktop": 1}
        assert "X-SERVER-ADDED:yes" in next(iter(server.collection("contacts").items.values()))[0]
        assert run_sync(client, partnership, options).counts() == {}


def test_bad_password_is_reported_per_type(tmp_path):
    client = FakeRapiClient()
    partnership = Partnership.for_device("HPC", tmp_path / "partnerships")
    with FakeDavServer() as server:
        options = caldav_options(server.url, caldav_password="wrong")
        report = asyncio.run(synchronize(client, partnership, options, providers=PROVIDERS))
        assert len(report.errors) == 3 and "caldav_password" in report.errors[0]
        assert sorted(report.skipped_types) == ["calendar", "contacts", "tasks"]


def test_unknown_collection_name_lists_the_choices(tmp_path):
    client = FakeRapiClient()
    partnership = Partnership.for_device("HPC", tmp_path / "partnerships")
    with FakeDavServer() as server:
        options = caldav_options(server.url, caldav_calendar="Work")
        options.object_types = ["calendar"]
        report = asyncio.run(synchronize(client, partnership, options, providers=PROVIDERS))
        assert "Personal" in report.errors[0]


def test_type_providers_mix_folder_files_with_caldav_contacts(tmp_path):
    client = FakeRapiClient()
    client.put_file("\\My Documents\\note.txt", b"hello")
    partnership = Partnership.for_device("HPC", tmp_path / "partnerships")
    add_device_contact(client, "Ada", "Lovelace")
    with FakeDavServer() as server:
        options = SyncOptions(object_types=["files", "contacts"], type_providers={"contacts": "caldav"},
                              provider_settings={"folder": str(tmp_path / "folder"), "caldav_url": server.url,
                                                 "caldav_username": "ada", "caldav_password": "secret"})
        report = run_sync(client, partnership, options)
        assert report.counts() == {"add to desktop": 2}
        assert (tmp_path / "folder" / "My Documents" / "note.txt").read_bytes() == b"hello"
        assert not (tmp_path / "folder" / "Contacts").exists() or not list((tmp_path / "folder" / "Contacts").glob("*.vcf"))
        assert len(server.collection("contacts").items) == 1


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def create_collection(url, method, body):
    request = urllib.request.Request(url, data=body.encode(), method=method,
                                     headers={"Content-Type": "application/xml", "Authorization": "Basic YWRhOnNlY3JldA=="})
    urllib.request.urlopen(request, timeout=10).read()


@pytest.fixture
def radicale_server(tmp_path):
    port = free_port()
    process = subprocess.Popen(
        [RADICALE_PYTHON, "-m", "radicale", "--storage-filesystem-folder", str(tmp_path / "radicale"), "--auth-type", "none",
         "--server-hosts", f"127.0.0.1:{port}", "--logging-level", "warning"],
        cwd=str(tmp_path), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}/"
    try:
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        create_collection(url + "ada/contacts/", "MKCOL",
                          '<?xml version="1.0"?><d:mkcol xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav"><d:set><d:prop>'
                          "<d:resourcetype><d:collection/><card:addressbook/></d:resourcetype><d:displayname>Contacts</d:displayname>"
                          "</d:prop></d:set></d:mkcol>")
        for name, component in (("calendar", "VEVENT"), ("tasks", "VTODO")):
            create_collection(url + f"ada/{name}/", "MKCALENDAR",
                              '<?xml version="1.0"?><c:mkcalendar xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:set><d:prop>'
                              f"<d:displayname>{name.title()}</d:displayname><c:supported-calendar-component-set>"
                              f'<c:comp name="{component}"/></c:supported-calendar-component-set></d:prop></d:set></c:mkcalendar>')
        yield url
    finally:
        process.terminate()
        process.wait(10)


@pytest.mark.skipif(not RADICALE_PYTHON or not Path(RADICALE_PYTHON).exists(),
                    reason="set CLASSICSYNC_RADICALE_PYTHON to a Python with radicale installed")
def test_two_way_sync_with_radicale(tmp_path, radicale_server):
    client = FakeRapiClient()
    partnership = Partnership.for_device("HPC", tmp_path / "partnerships")
    add_device_contact(client, "Ada", "Lovelace", [cedb.PropertyValue(*PAGER, "pager kept")])
    for path, text in (("contacts/grace-1.vcf", GRACE), ("calendar/standup-1.ics", STANDUP), ("tasks/laundry-1.ics", LAUNDRY)):
        request = urllib.request.Request(radicale_server + "ada/" + path, data=text.encode(), method="PUT",
                                         headers={"Content-Type": "text/vcard" if path.endswith(".vcf") else "text/calendar",
                                                  "Authorization": "Basic YWRhOnNlY3JldA=="})
        urllib.request.urlopen(request, timeout=10).read()
    options = caldav_options(radicale_server)
    assert run_sync(client, partnership, options).counts() == {"add to desktop": 1, "add to device": 3}
    assert run_sync(client, partnership, options).counts() == {}
    oid = next(oid for oid, values in device_records(client, "Contacts Database").items() if values[SURNAME] == "Hopper")
    client.databases["Contacts Database"][oid] = [
        prop if (prop.identifier, prop.value_type) != SURNAME else cedb.PropertyValue(*SURNAME, "Murray")
        for prop in client.databases["Contacts Database"][oid]]
    assert run_sync(client, partnership, options).counts() == {"update to desktop": 1}
    with urllib.request.urlopen(urllib.request.Request(radicale_server + "ada/contacts/grace-1.vcf",
                                                       headers={"Authorization": "Basic YWRhOnNlY3JldA=="}), timeout=10) as reply:
        card = reply.read().decode()
    assert "Murray" in card and "PHOTO" in card
    assert run_sync(client, partnership, options).counts() == {}


def test_use_for_types_sets_and_clears_type_providers():
    options = SyncOptions(object_types=["files", "contacts"])
    use_for_types(options, CalDavProvider, ["contacts", "calendar"], FolderProvider)
    assert options.type_providers == {"contacts": "caldav", "calendar": "caldav"}
    assert options.object_types == ["files", "contacts", "calendar"]
    use_for_types(options, FolderProvider, ["contacts"], FolderProvider)
    assert options.type_providers == {"calendar": "caldav"}
    with pytest.raises(ValueError):
        use_for_types(options, CalDavProvider, ["files"], FolderProvider)


def test_type_assignments():
    options = SyncOptions(type_providers={"tasks": "caldav"})
    assignments = {object_type.key: provider.name for provider, object_type in type_assignments(PROVIDERS, options)}
    assert assignments["tasks"] == "caldav"
    assert {key: name for key, name in assignments.items() if key != "tasks"} == {
        object_type.key: "folder" for object_type in FolderProvider.object_types if object_type.key != "tasks"}
    with pytest.raises(ValueError):
        type_assignments(PROVIDERS, SyncOptions(type_providers={"files": "caldav"}))
    with pytest.raises(ValueError):
        type_assignments(PROVIDERS, SyncOptions(type_providers={"tasks": "missing"}))
