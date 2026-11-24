import asyncio
import subprocess
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fake_dav import FakeDavServer
from test_provider_caldav import GRACE, LAUNDRY, RADICALE_PYTHON, STANDUP, radicale_server  # noqa: F401
from test_velo_emu import DEVICES, VELO_EMU, free_port
from test_velo_emu_sync import GIVEN_NAME, SURNAME, read_database

from classicsync.connection.desktop import Desktop
from classicsync.link.transport import TcpSerialTransport
from classicsync.rapi import cedb
from classicsync.rapi.structures import datetime_to_filetime
from classicsync.sync import Partnership, SyncOptions, synchronize

pytestmark = [
    pytest.mark.device,
    pytest.mark.skipif(not VELO_EMU, reason="set VELO_EMU to a velo-emu checkout to run against emulated devices"),
]

AUTHORIZATION = {"Authorization": "Basic YWRhOnNlY3JldA=="}
PAGER = (0x4009, cedb.CEVT_LPWSTR)
SUBJECT = (0x0037, cedb.CEVT_LPWSTR)


@pytest.fixture
def ce2_device():
    rom, state = DEVICES["ce2"]
    port = free_port()
    process = subprocess.Popen(
        ["./headless", rom, f"--load={Path(VELO_EMU) / state}", "--seconds=100000", "--realtime=1", f"--tcp={port}"],
        cwd=VELO_EMU, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    yield port
    process.terminate()
    process.wait(10)


@contextmanager
def fake_dav_server():
    with FakeDavServer() as server:
        yield server.url, server.url + "dav/ada/"


@pytest.fixture
def dav_server(request):
    if RADICALE_PYTHON and Path(RADICALE_PYTHON).exists():
        url = request.getfixturevalue("radicale_server")
        yield url, url + "ada/"
    else:
        with fake_dav_server() as addresses:
            yield addresses


def put_resource(url, text):
    content_type = "text/vcard" if url.endswith(".vcf") else "text/calendar"
    request = urllib.request.Request(url, data=text.encode(), method="PUT", headers={"Content-Type": content_type, **AUTHORIZATION})
    urllib.request.urlopen(request, timeout=10).read()


def get_resource(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=AUTHORIZATION), timeout=10) as reply:
        return reply.read().decode()


def resource_names(url):
    request = urllib.request.Request(url, method="PROPFIND", headers={"Depth": "1", **AUTHORIZATION},
                                     data=b'<d:propfind xmlns:d="DAV:"><d:prop><d:getetag/></d:prop></d:propfind>')
    with urllib.request.urlopen(request, timeout=10) as reply:
        body = reply.read().decode()
    return [part.split("<", 1)[0].rpartition("/")[2] for part in body.split("href>")[1::2] if not part.split("<", 1)[0].endswith("/")]


def test_caldav_sync_with_emulated_ce2(ce2_device, dav_server, tmp_path):
    port = ce2_device
    server_url, collections = dav_server
    partnership = Partnership.for_device("Velo", tmp_path / "partnerships")
    options = SyncOptions(provider="caldav", object_types=["contacts", "calendar", "tasks"],
                          provider_settings={"caldav_url": server_url, "caldav_username": "ada", "caldav_password": "secret"})
    put_resource(collections + "contacts/grace-1.vcf", GRACE)
    put_resource(collections + "calendar/standup-1.ics", STANDUP)
    put_resource(collections + "tasks/laundry-1.ics", LAUNDRY)

    async def scenario():
        await asyncio.sleep(0.5)
        desktop = Desktop(TcpSerialTransport("127.0.0.1", port))
        await desktop.start()
        try:
            await desktop.wait_for_device(60)
            client = await desktop.open_rapi()
            handle, _ = await client.open_database("Contacts Database")
            ada_oid = await client.write_record(handle, 0, [
                cedb.PropertyValue(*GIVEN_NAME, "Ada"), cedb.PropertyValue(*SURNAME, "Lovelace"),
                cedb.PropertyValue(*PAGER, "pager kept"), cedb.PropertyValue(0x0001, cedb.CEVT_LPWSTR, "x" * 3000),
            ])
            await client.close_handle(handle)
            handle, _ = await client.open_database("Appointments Database")
            start = datetime_to_filetime(datetime(2026, 12, 3, 14, 0, tzinfo=timezone.utc))
            await client.write_record(handle, 0, [
                cedb.PropertyValue(*SUBJECT, "Dentist"), cedb.PropertyValue(0x420D, cedb.CEVT_FILETIME, start),
                cedb.PropertyValue(0x4213, cedb.CEVT_I4, 30), cedb.PropertyValue(0x4215, cedb.CEVT_I4, 2),
            ])
            await client.close_handle(handle)

            report = await synchronize(client, partnership, options)
            assert not report.errors and not [action for action in report.actions if action.error], report.actions
            assert report.counts() == {"add to desktop": 2, "add to device": 3}
            contacts = await read_database(client, "Contacts Database")
            assert sorted(values[SURNAME] for values in contacts.values()) == ["Hopper", "Lovelace"]
            appointments = await read_database(client, "Appointments Database")
            assert sorted(values[SUBJECT] for values in appointments.values()) == ["Dentist", "Standup"]
            tasks = await read_database(client, "Tasks Database")
            assert [values[SUBJECT] for values in tasks.values()] == ["Laundry"]
            ada_name = next(name for name in resource_names(collections + "contacts/") if name != "grace-1.vcf")
            assert "N:Lovelace;Ada;;;" in get_resource(collections + "contacts/" + ada_name)
            assert any("SUMMARY:Dentist" in get_resource(collections + "calendar/" + name)
                       for name in resource_names(collections + "calendar/"))

            put_resource(collections + "contacts/" + ada_name,
                         get_resource(collections + "contacts/" + ada_name).replace("N:Lovelace;Ada", "N:Byron;Ada"))
            grace_oid = next(oid for oid, values in contacts.items() if values[SURNAME] == "Hopper")
            handle, _ = await client.open_database("Contacts Database")
            await client.write_record(handle, grace_oid, [cedb.PropertyValue(*SURNAME, "Murray")])
            await client.close_handle(handle)

            report = await synchronize(client, partnership, options)
            assert not report.errors and not [action for action in report.actions if action.error], report.actions
            assert report.counts() == {"update to desktop": 1, "update to device": 1}
            contacts = await read_database(client, "Contacts Database")
            assert contacts[ada_oid][SURNAME] == "Byron"
            assert contacts[ada_oid][PAGER] == "pager kept"
            assert contacts[ada_oid][(0x0001, cedb.CEVT_LPWSTR)] == "x" * 3000
            grace = get_resource(collections + "contacts/grace-1.vcf")
            assert "N:Murray;Grace;;;" in grace and "PHOTO" in grace

            report = await synchronize(client, partnership, options)
            assert report.counts() == {}
            client.close()
        finally:
            await desktop.close()

    asyncio.run(asyncio.wait_for(scenario(), 400))
