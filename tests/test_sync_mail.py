import asyncio
import email
import email.policy
from datetime import datetime

import pytest
from fake_device import FakeRapiClient

from classicsync.rapi.cedb import CEVT_BLOB, CEVT_FILETIME, CEVT_LPWSTR, CEVT_UI2, CEVT_UI4, PropertyValue
from classicsync.sync import Partnership, SyncOptions, synchronize
from classicsync.sync.mail import records
from classicsync.sync.mail.records import (
    FOLDER_INBOX, FOLDER_OUTBOX, FOLDER_SENT, STATUS_COMPOSED, STATUS_DELETE, STATUS_READ, MailMessage, decode_headers,
    encode_headers, message_from_v1, message_from_v2, split_subject, v1_properties, v2_properties, values_by_key,
)
from classicsync.sync.mail.rfc5322 import (
    content_key, local_datetime_from_filetime, local_filetime_from_datetime, message_from_rfc5322, message_to_rfc5322,
)

CE1_OUTBOX_RECORD = [
    PropertyValue(0x0000, CEVT_UI4, 0x80000001),
    PropertyValue(0x0005, CEVT_LPWSTR, ""),
    PropertyValue(0x0001, CEVT_UI4, 0x004000FD),
    PropertyValue(0x0002, CEVT_UI4, 0x20),
    PropertyValue(0x0003, CEVT_UI2, 0x20),
    PropertyValue(0x0004, CEVT_FILETIME, 0x01BAD840D938E100),
    PropertyValue(0x0006, CEVT_LPWSTR, "Mail"),
    PropertyValue(0x0007, CEVT_BLOB, "To\0bob@example.com\0\0".encode("utf-16-le")),
    PropertyValue(0x0008, CEVT_LPWSTR, "Hello from the Velo\r\nSecond line"),
]
CE2_OUTBOX_RECORD = [
    PropertyValue(0x0004, CEVT_FILETIME, 0x01BBF7DB8C814080),
    PropertyValue(0x0003, CEVT_UI2, 0x20),
    PropertyValue(0x0000, CEVT_UI4, 1),
    PropertyValue(0x0001, CEVT_UI4, 0x005000FD),
    PropertyValue(0x0002, CEVT_UI4, 0x20),
    PropertyValue(0x0005, CEVT_LPWSTR, ""),
    PropertyValue(0x0006, CEVT_LPWSTR, ""),
    PropertyValue(0x0007, CEVT_LPWSTR, ""),
    PropertyValue(0x0008, CEVT_BLOB, "To\0bob@example.com\0\0".encode("utf-16-le")),
    PropertyValue(0x000A, CEVT_LPWSTR, "Hello from the Velo\r\nSecond line"),
    PropertyValue(0x0009, CEVT_UI4, 0x573),
]
CE2_SERVICE_RECORD = [
    PropertyValue(0x0004, CEVT_UI4, 1),
    PropertyValue(0x0002, CEVT_LPWSTR, "Windows CE Inbox Services"),
    PropertyValue(0x0003, CEVT_LPWSTR, ""),
    PropertyValue(0x0005, CEVT_UI4, 0x1000572),
]


class FakeMailClient(FakeRapiClient):
    def __init__(self, store_version, **arguments):
        super().__init__(**arguments)
        self.store_version = store_version
        self.databases[records.MESSAGE_DATABASE] = {}
        if store_version < records.VERSION_2:
            self.add_record(records.MESSAGE_DATABASE, records.v1_head_properties(store_version, 0))
            for folder_id, name in ((FOLDER_INBOX, "Inbox"), (FOLDER_OUTBOX, "Outbox"), (FOLDER_SENT, "Sent Items")):
                self.add_record(records.MESSAGE_DATABASE, records.v1_folder_properties(folder_id, name))
        else:
            self.databases[records.HELPER_DATABASE] = {}
            self.add_record(records.MESSAGE_DATABASE, records.v2_head_properties(store_version, 0))
            for folder_id, name in ((FOLDER_INBOX, "Inbox"), (FOLDER_OUTBOX, "Outbox"), (FOLDER_SENT, "Sent")):
                self.add_record(records.HELPER_DATABASE, records.v2_folder_properties(folder_id, name))

    async def find_all_databases(self, database_type=0, flags=0):
        return [{"name": name} for name in self.databases]

    def message_records(self):
        return {oid: values_by_key(properties) for oid, properties in self.databases[records.MESSAGE_DATABASE].items()
                if records.is_message_v1(values_by_key(properties)) or (
                    self.store_version >= records.VERSION_2 and records.is_message_v2(values_by_key(properties)))}

    def folders(self):
        database = records.MESSAGE_DATABASE if self.store_version < records.VERSION_2 else records.HELPER_DATABASE
        found = {}
        for properties in self.databases[database].values():
            values = values_by_key(properties)
            folder = records.folder_from_v1(values) if self.store_version < records.VERSION_2 else records.folder_from_v2(values)
            if folder:
                found[folder[1]] = folder[0]
        return found

    def add_message(self, folder_id, flags, headers, body, date=0x01BAD840D938E100):
        message = MailMessage(folder_id=folder_id, flags=flags, headers=headers, body=body, date=date, message_id=len(self.message_records()) + 1)
        if self.store_version < records.VERSION_2:
            return self.add_record(records.MESSAGE_DATABASE, v1_properties(message))
        return self.add_record(records.MESSAGE_DATABASE, v2_properties(message))


def test_header_blob_round_trip():
    blob = "To\0bob@example.com\0\0".encode("utf-16-le")
    assert decode_headers(blob) == [("To", "bob@example.com")]
    assert encode_headers([("To", "bob@example.com")]) == blob
    assert decode_headers(encode_headers([])) == []


def test_subject_prefix_split():
    assert split_subject("RE: Lunch") == ("RE: ", "Lunch")
    assert split_subject("fw:Notes") == ("fw:", "Notes")
    assert split_subject("Regarding") == ("", "Regarding")


def test_ce1_record_decodes_and_encodes_back():
    message = message_from_v1(CE1_OUTBOX_RECORD, 0xD5)
    assert message.folder_id == FOLDER_OUTBOX
    assert message.flags == STATUS_COMPOSED
    assert message.message_id == 1
    assert message.service_name == "Mail"
    assert message.headers == [("To", "bob@example.com")]
    encoded = values_by_key(v1_properties(message))
    assert encoded == values_by_key(CE1_OUTBOX_RECORD)


def test_ce2_record_decodes_with_its_service_record():
    message = message_from_v2(CE2_OUTBOX_RECORD, CE2_SERVICE_RECORD, 0x1000572)
    assert message.folder_id == FOLDER_OUTBOX
    assert message.flags == STATUS_COMPOSED | STATUS_READ
    assert message.service_name == "Windows CE Inbox Services"
    assert message.headers == [("To", "bob@example.com")]
    assert message.body == "Hello from the Velo\r\nSecond line"
    assert values_by_key(v2_properties(message, 0x573)) == values_by_key(CE2_OUTBOX_RECORD)


def test_ce2_from_and_subject_move_between_properties_and_headers():
    message = MailMessage(folder_id=FOLDER_INBOX, headers=[("From", "Ann <ann@example.com>"), ("Subject", "RE: Plans"), ("Cc", "c@example.com")])
    values = values_by_key(v2_properties(message))
    assert values[records.V2_FROM] == "Ann <ann@example.com>"
    assert (values[records.V2_PRESUBJECT], values[records.V2_SUBJECT]) == ("RE: ", "Plans")
    assert decode_headers(values[records.V2_HEADERS]) == [("Cc", "c@example.com")]
    decoded = message_from_v2(v2_properties(message))
    assert decoded.headers == [("From", "Ann <ann@example.com>"), ("Subject", "RE: Plans"), ("Cc", "c@example.com")]


def test_rfc5322_round_trip_keeps_content():
    date = local_filetime_from_datetime(datetime(1999, 3, 4, 10, 30))
    message = MailMessage(headers=[("From", "Ann Smith [SMTP:ann@example.com]"), ("To", "bob@example.com; Carl <carl@example.com>"),
                                   ("Subject", "Caf\u00e9 plans")],
                          body="Line one\r\nLine two \u00e9\r\n", date=date)
    data = message_to_rfc5322(message)
    parsed = email.message_from_bytes(data, policy=email.policy.default)
    assert parsed["From"].addresses[0].addr_spec == "ann@example.com"
    assert [address.addr_spec for address in parsed["To"].addresses] == ["bob@example.com", "carl@example.com"]
    assert str(parsed["Subject"]) == "Caf\u00e9 plans"
    assert parsed["Date"].datetime.replace(tzinfo=None) == datetime(1999, 3, 4, 10, 30)
    back = message_from_rfc5322(data)
    assert back.date == date
    assert back.header("To") == "bob@example.com; Carl <carl@example.com>"
    assert content_key(back) == content_key(message)
    assert local_datetime_from_filetime(date).replace(tzinfo=None) == datetime(1999, 3, 4, 10, 30)


def test_html_only_message_becomes_text():
    data = b"Subject: x\nContent-Type: text/html\n\n<p>Hello<br>there &amp; you</p>\n"
    assert message_from_rfc5322(data).body.split() == ["Hello", "there", "&", "you"]


@pytest.fixture(params=[records.VERSION_1, records.VERSION_2])
def mail_sync(request, tmp_path):
    client = FakeMailClient(request.param, name="Velo", os_major=1 if request.param < records.VERSION_2 else 2)
    root = tmp_path / "Velo"
    partnership = Partnership.for_device("Velo", tmp_path / "partnerships")

    def run():
        options = SyncOptions(object_types=["mail"], provider_settings={"folder": str(root)})
        return asyncio.run(synchronize(client, partnership, options))

    return client, root / "Mail", run


def maildir_files(mail_root, folder):
    return sorted(path for subdirectory in ("new", "cur") for path in (mail_root / folder / subdirectory).glob("*"))


def test_device_messages_land_in_maildir_and_flags_flow_back(mail_sync):
    client, mail_root, run = mail_sync
    oid = client.add_message(FOLDER_INBOX, 0, [("From", "Ann [SMTP:ann@example.com]"), ("Subject", "Hello")], "Body text\r\n")
    report = run()
    assert report.counts() == {"add to desktop": 1}
    assert sorted(path.name for path in mail_root.iterdir() if path.is_dir()) == sorted(client.folders())
    [path] = maildir_files(mail_root, "Inbox")
    assert path.parent.name == "new"
    parsed = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
    assert str(parsed["Subject"]) == "Hello"
    assert parsed["From"].addresses[0].addr_spec == "ann@example.com"
    assert run().counts() == {}

    path.rename(mail_root / "Inbox" / "cur" / (path.name + ":2,S"))
    assert run().counts() == {"update to device": 1}
    flags = client.message_records()[oid][records.V1_FLAGS]
    assert flags & STATUS_READ and flags & records.FOLDER_MASK == FOLDER_INBOX
    assert run().counts() == {}


def test_moves_deletes_and_outbox(mail_sync):
    client, mail_root, run = mail_sync
    kept = client.add_message(FOLDER_INBOX, STATUS_READ, [("Subject", "Keep")], "keep")
    gone = client.add_message(FOLDER_INBOX, STATUS_READ, [("Subject", "Gone")], "gone")
    run()
    files = {email.message_from_bytes(path.read_bytes())["Subject"]: path for path in maildir_files(mail_root, "Inbox")}
    (mail_root / "Projects" / "cur").mkdir(parents=True)
    (mail_root / "Projects" / "new").mkdir()
    files["Keep"].rename(mail_root / "Projects" / "cur" / files["Keep"].name)
    files["Gone"].unlink()
    (mail_root / "Outbox" / "new" / "draft.eml").write_bytes(
        b"To: bob@example.com, carl@example.com\nSubject: From the desktop\n\nPlease send this.\n")
    report = run()
    assert report.counts() == {"update to device": 1, "delete to device": 1, "add to device": 1}
    messages = client.message_records()
    assert gone not in messages
    assert messages[kept][records.V1_FLAGS] & records.FOLDER_MASK == client.folders()["Projects"]
    [new_oid] = [oid for oid in messages if oid not in (kept, gone)]
    sent = messages[new_oid]
    assert sent[records.V1_FLAGS] & records.FOLDER_MASK == FOLDER_OUTBOX
    assert sent[records.V1_FLAGS] & STATUS_COMPOSED
    device_message = (message_from_v1 if client.store_version < records.VERSION_2 else message_from_v2)(
        client.databases[records.MESSAGE_DATABASE][new_oid])
    assert device_message.header("To") == "bob@example.com; carl@example.com"
    assert device_message.subject == "From the desktop"
    assert device_message.body.rstrip() == "Please send this."
    assert run().counts() == {}


def test_device_delete_flag_and_folder_removal(mail_sync):
    client, mail_root, run = mail_sync
    oid = client.add_message(FOLDER_INBOX, 0, [("Subject", "Bin me")], "x")
    run()
    properties = client.databases[records.MESSAGE_DATABASE][oid]
    flags = values_by_key(properties)[records.V1_FLAGS]
    client.databases[records.MESSAGE_DATABASE][oid] = [
        PropertyValue(prop.identifier, prop.value_type, flags | STATUS_DELETE if prop.propid == (1 << 16 | CEVT_UI4) else prop.value)
        for prop in properties]
    assert run().counts() == {"update to desktop": 1}
    deleted_folder = "Deleted Items" if client.store_version < records.VERSION_2 else "Deleted"
    assert len(maildir_files(mail_root, deleted_folder)) == 1
    assert maildir_files(mail_root, "Inbox") == []
    (mail_root / "Archive" / "cur").mkdir(parents=True)
    run()
    assert "Archive" in client.folders()
    (mail_root / "Archive" / "cur").rmdir()
    (mail_root / "Archive").rmdir()
    run()
    assert "Archive" not in client.folders()


def test_missing_store_is_empty_and_rejects_writes(tmp_path):
    client = FakeMailClient(records.VERSION_2, name="Velo")
    del client.databases[records.MESSAGE_DATABASE]
    del client.databases[records.HELPER_DATABASE]
    root = tmp_path / "Velo"
    (root / "Mail" / "Outbox" / "new").mkdir(parents=True)
    (root / "Mail" / "Outbox" / "new" / "a.eml").write_bytes(b"Subject: x\n\nbody\n")
    partnership = Partnership.for_device("Velo", tmp_path / "partnerships")
    report = asyncio.run(synchronize(client, partnership, SyncOptions(object_types=["mail"], provider_settings={"folder": str(root)})))
    [action] = report.actions
    assert "Inbox has not been set up" in action.error
