import asyncio
import email
import email.policy

import pytest
from test_velo_emu import VELO_EMU, ce1_state, connected_client, emulated_device, wait_until  # noqa: F401

from classicsync.sync import Partnership, SyncOptions, synchronize
from classicsync.sync.mail.device import DeviceMailbox
from classicsync.sync.mail.records import FOLDER_INBOX, FOLDER_OUTBOX, STATUS_COMPOSED, STATUS_READ, MailMessage

pytestmark = [
    pytest.mark.device,
    pytest.mark.skipif(not VELO_EMU, reason="set VELO_EMU to a velo-emu checkout to run against emulated devices"),
]


async def device_messages(client):
    mailbox = DeviceMailbox(client)
    await mailbox.open()
    try:
        await mailbox.list()
        return mailbox.version, {message.subject: message for message in
                                 [mailbox.message(device_id) for device_id in mailbox.messages]}
    finally:
        await mailbox.close()


async def put_device_message(client, message):
    mailbox = DeviceMailbox(client)
    await mailbox.open()
    try:
        await mailbox.list()
        return await mailbox.write(None, message)
    finally:
        await mailbox.close()


def maildir_files(mail_root, folder):
    return sorted(path for subdirectory in ("new", "cur") for path in (mail_root / folder / subdirectory).glob("*"))


def test_mail_round_trip(emulated_device, tmp_path):
    name, port = emulated_device
    root = tmp_path / "folder"
    mail_root = root / "Mail"
    partnership = Partnership.for_device(name, tmp_path / "partnerships")
    options = SyncOptions(object_types=["mail"], provider_settings={"folder": str(root)})

    async def scenario():
        desktop, client = await connected_client(port)
        try:
            await client.create_process("\\Windows\\pmail.exe")

            async def store_created():
                return any(entry.get("name", "").lower() == "\\pmaildb" for entry in await client.find_all_databases())

            assert await wait_until(store_created, 90)
            await asyncio.sleep(5)
            version, _ = await device_messages(client)
            assert version == (0x0102 if name == "ce1" else 0x0200)
            await put_device_message(client, MailMessage(
                folder="Inbox", headers=[("From", "Ann Smith [SMTP:ann@example.com]"), ("To", "velo@example.com"),
                                         ("Subject", "RE: Hello from the device")], body="First line\r\nSecond line"))

            report = await synchronize(client, partnership, options)
            assert report.counts() == {"add to desktop": 1}, report.actions
            [received] = maildir_files(mail_root, "Inbox")
            parsed = email.message_from_bytes(received.read_bytes(), policy=email.policy.default)
            assert str(parsed["Subject"]) == "RE: Hello from the device"
            assert parsed["From"].addresses[0].addr_spec == "ann@example.com"
            assert {"Inbox", "Outbox"} <= {path.name for path in mail_root.iterdir() if path.is_dir()}

            received.rename(mail_root / "Inbox" / "cur" / (received.name + ":2,S"))
            (mail_root / "Outbox" / "new" / "reply.eml").write_bytes(
                b"To: ann@example.com\nSubject: Sent from the desktop\n\nQueued for the device to send.\n")
            report = await synchronize(client, partnership, options)
            assert report.counts() == {"update to device": 1, "add to device": 1}, report.actions
            _, messages = await device_messages(client)
            inbox_message = messages["RE: Hello from the device"]
            assert inbox_message.folder_id == FOLDER_INBOX and inbox_message.flags & STATUS_READ
            outbox_message = messages["Sent from the desktop"]
            assert outbox_message.folder_id == FOLDER_OUTBOX and outbox_message.flags & STATUS_COMPOSED
            assert outbox_message.header("To") == "ann@example.com"
            assert outbox_message.body.startswith("Queued for the device to send.")

            mailbox = DeviceMailbox(client)
            await mailbox.open()
            await mailbox.list()
            await mailbox.delete(f"{inbox_message.oid:08x}")
            await mailbox.close()
            report = await synchronize(client, partnership, options)
            assert report.counts() == {"delete to desktop": 1}, report.actions
            assert maildir_files(mail_root, "Inbox") == []

            assert (await synchronize(client, partnership, options)).counts() == {}
            client.close()
        finally:
            await desktop.close()

    asyncio.run(asyncio.wait_for(scenario(), 400))
