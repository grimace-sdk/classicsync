import asyncio
import struct
from datetime import date, time

from classicsync.link.transport import Transport
from classicsync.palm import DlpClient, NetSyncLink
from classicsync.palm import convert, records
from classicsync.palm.netsync import HEADER
from classicsync.palm.sync import create_palm_partnership, synchronize_handheld
from classicsync.sync.pim.icalendar import appointment_to_ical, ical_to_appointment

M500_ADDRESS = bytes.fromhex(
    "00533355000004b5000546656c6c6f7773004a616e65004d6f6f7365204c6f646765000207 30313233000a"
    "6a616e65406578616d706c652e636f6d00".replace(" ", ""))
HELLO = bytes.fromhex("90010000000000000020000000080000010000000000")
OPTIONS = bytes.fromhex("9201000000000000002000000024ffffffff003c003c40000000010000000000040000000400003c003c0000000000000000")


def category_block(names):
    categories = records.Categories(names + [""] * (16 - len(names)), list(range(16)), 0, 15)
    return records.build_categories(categories, b"")


def test_address_round_trips_through_contact_properties():
    address = records.Address()
    address.fields[records.ADDRESS_LAST_NAME] = "Fellows"
    address.fields[records.ADDRESS_FIRST_NAME] = "Jane"
    address.fields[records.ADDRESS_CITY] = "Sheffield"
    address.fields[records.ADDRESS_CUSTOM_FIRST] = "kept on the handheld"
    address.phone_labels = [records.PHONE_MOBILE, records.PHONE_EMAIL, records.PHONE_OTHER, records.PHONE_WORK, records.PHONE_HOME]
    address.fields[records.ADDRESS_PHONE_FIRST] = "07700 900123"
    address.fields[records.ADDRESS_PHONE_FIRST + 1] = "jane@example.com"
    address.fields[records.ADDRESS_PHONE_FIRST + 2] = "0114 496 0000"
    address.display_phone = 1
    properties = convert.address_to_properties(address, "Business", secret=True)
    back = convert.properties_to_address(properties, address)
    assert records.build_address(back) == records.build_address(address)
    fresh = convert.properties_to_address(properties)
    assert fresh.fields[records.ADDRESS_CUSTOM_FIRST] is None
    assert sorted(value for _label, value in fresh.phones()) == sorted(value for _label, value in address.phones())
    assert convert.category_and_secret(properties) == ("Business", True)


def test_weekly_repeat_with_exceptions_becomes_rrule_and_back():
    appointment = records.Appointment(date(2026, 11, 23), time(9, 30), time(10, 15), "Stand-up", alarm=(10, records.ALARM_MINUTES),
                                      repeat=records.Repeat(records.REPEAT_WEEKLY, date(2026, 12, 31), 1, 0b0101010, 1),
                                      exceptions=[date(2026, 12, 2)])
    properties = convert.appointment_to_properties(appointment)
    text = appointment_to_ical(properties, "uid-1")
    assert "RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR;WKST=MO;UNTIL=" in text and "EXDATE:20261202T" in text
    back = convert.properties_to_appointment(ical_to_appointment(text, properties, 4), appointment)
    assert records.build_appointment(back) == records.build_appointment(appointment)


def test_untimed_monthly_repeat_and_count_rules():
    appointment = records.Appointment(date(2026, 11, 26), description="Bins",
                                      repeat=records.Repeat(records.REPEAT_MONTHLY_BY_DAY, repeat_on=4 * 7 + 4))
    rule = convert.repeat_to_rule(appointment.repeat, appointment.day, True)
    assert rule == "FREQ=MONTHLY;BYDAY=-1TH"
    text = appointment_to_ical(convert.appointment_to_properties(appointment), "uid-2")
    assert "DTSTART;VALUE=DATE:20261126" in text
    repeat = convert.rule_to_repeat("FREQ=DAILY;INTERVAL=2;COUNT=3", date(2026, 1, 1))
    assert (repeat.kind, repeat.frequency, repeat.end) == (records.REPEAT_DAILY, 2, date(2026, 1, 5))
    assert convert.rule_to_repeat("FREQ=MONTHLY;BYDAY=2TU", date(2026, 1, 13)).repeat_on == 1 * 7 + 2
    assert convert.rule_to_repeat("FREQ=HOURLY", date(2026, 1, 1)) is None


def test_todo_keeps_palm_priority():
    todo = records.ToDo("Register", "online", date(2026, 12, 1), 4, True)
    back = convert.properties_to_todo(convert.todo_to_properties(todo, "Personal"))
    assert back == todo


class FakePalm(Transport):
    def __init__(self, databases, user_name="Phil Howard", user_id=0x1234):
        self.databases = databases
        self.user = {"id": user_id, "name": user_name, "pc": 0}
        self.handles = {}
        self.incoming = asyncio.Queue()
        self.pending = b""
        self.incoming.put_nowait(HEADER.pack(1, 0xFF, len(HELLO)) + HELLO)
        self.next_id = 0x500000

    async def read(self):
        return await self.incoming.get()

    def write(self, data):
        self.pending += data

    async def drain(self):
        while len(self.pending) >= HEADER.size:
            _kind, xid, length = HEADER.unpack(self.pending[:HEADER.size])
            if len(self.pending) < HEADER.size + length:
                return
            payload = self.pending[HEADER.size:HEADER.size + length]
            self.pending = self.pending[HEADER.size + length:]
            reply = self.answer(payload)
            self.incoming.put_nowait(HEADER.pack(1, xid, len(reply)) + reply)

    def arguments(self, payload):
        offset = 2
        found = []
        for _ in range(payload[1]):
            identifier = payload[offset]
            if identifier & 0x80:
                length = struct.unpack_from(">H", payload, offset + 2)[0]
                offset += 4
            else:
                length = payload[offset + 1]
                offset += 2
            found.append(payload[offset:offset + length])
            offset += length
        return found

    def reply(self, command, *arguments, status=0):
        body = b"".join(bytes([0x20 + index | 0x80, 0]) + struct.pack(">H", len(data)) + data for index, data in enumerate(arguments))
        return struct.pack(">BBH", command | 0x80, len(arguments), status) + body

    def answer(self, payload):
        command = payload[0]
        if command == 0x12 and payload[1] == 1 and payload[2] == 0x20 and len(payload) == 8:
            return self.reply(0x12, bytes.fromhex("0400000000010000000400030000"), bytes.fromhex("00010002000300000000ffe1"))
        if command == 0x12:
            return OPTIONS
        if command == 0x13:
            return bytes.fromhex("9300000000000000")
        arguments = self.arguments(payload)
        if command == 0x10:
            name = self.user["name"].encode() + b"\0"
            return self.reply(0x10, struct.pack(">III", self.user["id"], 0, self.user["pc"]) + bytes(16)
                              + bytes([len(name), 0]) + name)
        if command == 0x11:
            data = arguments[0]
            self.user["id"], _viewer, self.user["pc"] = struct.unpack_from(">III", data)
            self.user["name"] = data[22:].split(b"\0")[0].decode()
            return self.reply(0x11)
        if command == 0x17:
            name = arguments[0][2:-1].decode()
            handle = len(self.handles) + 1
            self.handles[handle] = name
            return self.reply(0x17, bytes([handle]))
        database = self.databases.get(self.handles.get(arguments[0][0])) if arguments and arguments[0] else None
        if command == 0x19:
            return self.reply(0x19)
        if command == 0x1B:
            return self.reply(0x1B, struct.pack(">H", len(database["app_info"])) + database["app_info"])
        if command == 0x1C:
            database["app_info"] = arguments[0][4:]
            return self.reply(0x1C)
        if command == 0x2B:
            return self.reply(0x2B, struct.pack(">H", len(database["records"])))
        if command == 0x20:
            index = struct.unpack_from(">H", arguments[0], 2)[0]
            record_id, attributes, category, data = database["records"][index]
            return self.reply(0x20, struct.pack(">IHHBB", record_id, index, len(data), attributes, category) + data)
        if command == 0x21:
            record_id, attributes, category = struct.unpack_from(">IBB", arguments[0], 2)
            data = arguments[0][8:]
            if not record_id:
                self.next_id += 1
                record_id = self.next_id
            existing = [entry for entry in database["records"] if entry[0] != record_id]
            database["records"] = existing + [(record_id, attributes, category, data)]
            return self.reply(0x21, struct.pack(">I", record_id))
        if command == 0x22:
            record_id = struct.unpack_from(">I", arguments[0], 2)[0]
            database["records"] = [entry for entry in database["records"] if entry[0] != record_id]
            return self.reply(0x22)
        if command == 0x27:
            database["records"] = [(record_id, attributes & ~0x40, category, data)
                                   for record_id, attributes, category, data in database["records"]]
            return self.reply(command)
        if command in (0x26, 0x2F):
            return self.reply(command)
        raise AssertionError(f"unexpected command {command:#x}")


def handheld_databases():
    appointment = records.build_appointment(records.Appointment(date(2026, 11, 27), time(14, 0), time(15, 0), "Dentist"))
    return {
        "AddressDB": {"app_info": category_block(["Unfiled", "Business", "Personal"]),
                      "records": [(0x400001, 0x40, 1, M500_ADDRESS)]},
        "DatebookDB": {"app_info": category_block(["Unfiled"]), "records": [(0x400002, 0x40, 0, appointment)]},
        "ToDoDB": {"app_info": category_block(["Unfiled", "Business", "Personal"]),
                   "records": [(0x400003, 0x40, 2, records.build_todo(records.ToDo("Buy batteries", priority=2)))]},
    }


async def sync_once(palm, partnership, folder):
    link = NetSyncLink(palm)
    await link.accept()
    options = partnership.load_options()
    options.provider = "folder"
    options.provider_settings["folder"] = str(folder)
    return await synchronize_handheld(DlpClient(link), partnership, 0x0BEE, options)


def test_palm_sync_copies_handheld_records_and_back(run, tmp_path):
    databases = handheld_databases()
    partnership = create_palm_partnership("Phil Howard", 0x1234, base=tmp_path / "partnerships")
    folder = tmp_path / "desktop"
    report = run(lambda: sync_once(FakePalm(databases), partnership, folder))
    assert not report.errors and report.device == "Phil Howard"
    contact = next((folder / "contacts").glob("*.vcf")).read_text()
    assert "Fellows" in contact and "jane@example.com" in contact and "CATEGORIES:Business" in contact
    event = next((folder / "calendar").glob("*.ics")).read_text()
    assert "SUMMARY:Dentist" in event
    task_path = next((folder / "tasks").glob("*.ics"))
    assert "PRIORITY:3" in task_path.read_text() and "CATEGORIES:Personal" in task_path.read_text()
    assert all(attributes & 0x40 == 0 for database in databases.values() for _id, attributes, _c, _d in database["records"])

    task_path.write_text(task_path.read_text().replace("Buy batteries", "Buy AA batteries").replace("CATEGORIES:Personal",
                                                                                                   "CATEGORIES:Errands"))
    palm = FakePalm(databases)
    report = run(lambda: sync_once(palm, partnership, folder))
    assert not report.errors
    record_id, _attributes, category, data = databases["ToDoDB"]["records"][0]
    assert record_id == 0x400003 and records.parse_todo(data).description == "Buy AA batteries"
    assert records.parse_categories(databases["ToDoDB"]["app_info"]).name_of(category) == "Errands"
    assert palm.user["pc"] == 0x0BEE and palm.user["id"] == 0x1234
