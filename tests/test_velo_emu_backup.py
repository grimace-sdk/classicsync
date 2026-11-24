import asyncio
import shutil
import socket
import subprocess
from pathlib import Path

import pytest
from test_velo_emu import DEVICES, VELO_EMU, ce1_state  # noqa: F401

from classicsync.backup import backup, inspect, restore
from classicsync.connection.desktop import Desktop
from classicsync.link.transport import TcpSerialTransport
from classicsync.rapi import cedb
from classicsync.rapi.client import HKEY_CURRENT_USER, REG_SZ

pytestmark = [
    pytest.mark.device,
    pytest.mark.skipif(not VELO_EMU, reason="set VELO_EMU to a velo-emu checkout to run against emulated devices"),
]

TEST_FILE = "\\My Documents\\backup-test.txt"
NEW_FILE = "\\My Documents\\after-backup.txt"
REGISTRY_KEY = "Software\\classicsync backup test"
SURNAME = (0x3A11, cedb.CEVT_LPWSTR)
CONTACT_SURNAME = "Backupson"


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def start_emulator(rom, state, save, extra=()):
    port = free_port()
    process = subprocess.Popen(
        ["./headless", rom, f"--load={state}", "--seconds=100000", "--realtime=1", f"--tcp={port}", f"--save={save}", *extra],
        cwd=VELO_EMU, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return process, port


def stop_emulator(process):
    process.terminate()
    process.wait(30)


async def with_client(port, work, delay=0.5):
    await asyncio.sleep(delay)
    desktop = Desktop(TcpSerialTransport("127.0.0.1", port))
    await desktop.start()
    try:
        await desktop.wait_for_device(90)
        client = await desktop.open_rapi()
        try:
            return await work(client)
        finally:
            client.close()
    finally:
        await desktop.close()


async def set_registry_value(client, value):
    key, _ = await client.reg_create_key(HKEY_CURRENT_USER, REGISTRY_KEY)
    await client.reg_set_value(key, "Value", REG_SZ, value)
    await client.reg_close_key(key)


async def registry_value(client):
    key = await client.reg_open_key(HKEY_CURRENT_USER, REGISTRY_KEY)
    try:
        return (await client.reg_query_value(key, "Value"))[1]
    finally:
        await client.reg_close_key(key)


async def contact_oids(client):
    handle, _ = await client.open_database("Contacts Database")
    try:
        await client.seek_database(handle, cedb.CEDB_SEEK_BEGINNING)
        oids = []
        while (record := await client.read_record(handle)) is not None:
            if any(prop.propid == cedb.make_propid(*SURNAME) and prop.value == CONTACT_SURNAME for prop in record[1]):
                oids.append(record[0])
        return oids
    finally:
        await client.close_handle(handle)


@pytest.mark.parametrize("name", sorted(DEVICES))
def test_backup_and_restore(name, ce1_state, tmp_path):  # noqa: F811
    rom, state = DEVICES[name]
    start_state = tmp_path / "start.state"
    shutil.copy(ce1_state if state is None else Path(VELO_EMU) / state, start_state)
    restored_state = tmp_path / "restored.state"
    backup_path = tmp_path / "Backup.stg"

    async def back_up_change_and_restore(client):
        await client.write_file_contents(TEST_FILE, b"original\r\n")
        await set_registry_value(client, "original")
        handle, _ = await client.open_database("Contacts Database")
        await client.write_record(handle, 0, [cedb.PropertyValue(*SURNAME, CONTACT_SURNAME)])
        await client.close_handle(handle)

        full = await backup(client, backup_path)
        assert not full.skipped and full.files > 0 and full.databases > 0
        incremental = await backup(client, backup_path, full=False)
        assert incremental.incremental and incremental.unchanged >= full.files - 1 + full.databases - 1

        await client.write_file_contents(TEST_FILE, b"changed\r\n")
        await client.write_file_contents(NEW_FILE, b"made after the backup\r\n")
        await set_registry_value(client, "changed")
        handle, _ = await client.open_database("Contacts Database")
        for oid in await contact_oids(client):
            await client.delete_record(handle, oid)
        await client.close_handle(handle)
        assert await contact_oids(client) == []

        result = await restore(client, backup_path)
        assert result.registry_restored and not result.data_only
        assert NEW_FILE in result.deleted
        assert await client.read_file_contents(TEST_FILE) == b"original\r\n"
        assert not await client.find_all_files(NEW_FILE)
        assert len(await contact_oids(client)) == 1

    process, port = start_emulator(rom, start_state, restored_state)
    try:
        asyncio.run(asyncio.wait_for(with_client(port, back_up_change_and_restore), 1500))
    finally:
        stop_emulator(process)

    contents = inspect(backup_path)
    assert contents.information.version == 6
    assert contents.information.os_major == (1 if name == "ce1" else 2)
    assert contents.registry_size > 0
    assert TEST_FILE in {entry.path for entry in contents.files}
    assert any(database.name == "Contacts Database" and database.records >= 1 for database in contents.databases)

    async def after_reset(client):
        assert await registry_value(client) == "original"
        assert await client.read_file_contents(TEST_FILE) == b"original\r\n"
        assert len(await contact_oids(client)) == 1

    process, port = start_emulator(rom, restored_state, tmp_path / "after-reset.state", ["--soft-reset=1"])
    try:
        asyncio.run(asyncio.wait_for(with_client(port, after_reset, delay=30), 300))
    finally:
        stop_emulator(process)
