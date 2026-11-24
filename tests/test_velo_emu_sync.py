import asyncio
import os
from datetime import datetime, timezone

import pytest
from test_velo_emu import VELO_EMU, ce1_state, emulated_device  # noqa: F401

from classicsync.connection.desktop import Desktop
from classicsync.link.transport import TcpSerialTransport
from classicsync.rapi import cedb
from classicsync.rapi.structures import datetime_to_filetime
from classicsync.sync import Partnership, SyncOptions, synchronize
from classicsync.sync.pim.record import property_map

pytestmark = [
    pytest.mark.device,
    pytest.mark.skipif(not VELO_EMU, reason="set VELO_EMU to a velo-emu checkout to run against emulated devices"),
]

DEVICE_FOLDER = "\\My Documents\\classicsync"
GIVEN_NAME = (0x3A06, cedb.CEVT_LPWSTR)
SURNAME = (0x3A11, cedb.CEVT_LPWSTR)


async def read_database(client, name):
    handle, _ = await client.open_database(name)
    try:
        await client.seek_database(handle, cedb.CEDB_SEEK_BEGINNING)
        records = {}
        while (record := await client.read_record(handle)) is not None:
            records[record[0]] = property_map(record[1])
        return records
    finally:
        await client.close_handle(handle)


def test_sync_files_and_contacts(emulated_device, tmp_path):
    name, port = emulated_device
    root = tmp_path / "folder"
    partnership = Partnership.for_device(name, tmp_path / "partnerships")
    options = SyncOptions(object_types=["files", "contacts", "calendar"], file_folders=[DEVICE_FOLDER],
                          provider_settings={"folder": str(root)})

    async def scenario():
        await asyncio.sleep(0.5)
        desktop = Desktop(TcpSerialTransport("127.0.0.1", port))
        await desktop.start()
        try:
            await desktop.wait_for_device(60)
            client = await desktop.open_rapi()
            device_blob = os.urandom(5000)
            await client.create_directory(DEVICE_FOLDER)
            await client.write_file_contents(DEVICE_FOLDER + "\\device.bin", device_blob)
            local_folder = root / "classicsync" / "Sub"
            local_folder.mkdir(parents=True)
            (local_folder / "desktop.txt").write_bytes(b"from the desktop")
            os.utime(local_folder / "desktop.txt", (1_000_000_000, 1_000_000_000))
            handle, _ = await client.open_database("Contacts Database")
            device_oid = await client.write_record(handle, 0, [
                cedb.PropertyValue(*GIVEN_NAME, "Ada"), cedb.PropertyValue(*SURNAME, "Lovelace"),
                cedb.PropertyValue(0x4009, cedb.CEVT_LPWSTR, "pager kept"),
                cedb.PropertyValue(0x0001, cedb.CEVT_LPWSTR, "x" * 6000),
            ])
            await client.close_handle(handle)
            (root / "Contacts").mkdir(parents=True)
            (root / "Contacts" / "grace.vcf").write_text("BEGIN:VCARD\nVERSION:4.0\nN:Hopper;Grace;;;\nEND:VCARD\n")
            (root / "Calendar").mkdir(parents=True)
            (root / "Calendar" / "talk.ics").write_text(
                "BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:20000101T100000Z\nDURATION:PT45M\nSUMMARY:Talk\nEND:VEVENT\nEND:VCALENDAR\n")

            report = await synchronize(client, partnership, options)
            assert not [action for action in report.actions if action.error], report.actions
            assert (root / "classicsync" / "device.bin").read_bytes() == device_blob
            assert await client.read_file_contents(DEVICE_FOLDER + "\\Sub\\desktop.txt") == b"from the desktop"
            written = await client.find_all_files(DEVICE_FOLDER + "\\Sub\\desktop.txt")
            assert written[0].last_write_time == datetime_to_filetime(datetime.fromtimestamp(1_000_000_000, timezone.utc))
            contacts = await read_database(client, "Contacts Database")
            assert sorted(values[SURNAME] for values in contacts.values()) == ["Hopper", "Lovelace"]
            cards = {path.name: path for path in (root / "Contacts").glob("*.vcf")}
            ada = next(path for card_name, path in cards.items() if card_name != "grace.vcf")
            assert "N:Lovelace;Ada;;;" in ada.read_text()
            appointments = await read_database(client, "Appointments Database")
            assert [values[(0x4213, cedb.CEVT_I4)] for values in appointments.values()] == [45]

            ada.write_text(ada.read_text().replace("N:Lovelace;Ada", "N:Byron;Ada"))
            (local_folder / "desktop.txt").unlink()
            await client.write_file_contents(DEVICE_FOLDER + "\\device.bin", b"changed on device")
            report = await synchronize(client, partnership, options)
            assert report.counts() == {"update to device": 1, "update to desktop": 1, "delete to device": 1}
            contacts = await read_database(client, "Contacts Database")
            assert contacts[device_oid][SURNAME] == "Byron"
            assert contacts[device_oid][(0x4009, cedb.CEVT_LPWSTR)] == "pager kept"
            assert contacts[device_oid][(0x0001, cedb.CEVT_LPWSTR)] == "x" * 6000
            assert (root / "classicsync" / "device.bin").read_bytes() == b"changed on device"
            assert not await client.find_all_files(DEVICE_FOLDER + "\\Sub\\desktop.txt")

            report = await synchronize(client, partnership, options)
            assert report.counts() == {}
            client.close()
        finally:
            await desktop.close()

    asyncio.run(asyncio.wait_for(scenario(), 400))
