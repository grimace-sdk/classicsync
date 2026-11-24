from datetime import date, datetime, timedelta, timezone

from classicsync.sync.providers.macos.mapping import (
    LABEL_ANNIVERSARY, LABEL_HOME, LABEL_MOBILE, LABEL_SPOUSE, LABEL_WORK, AVAILABILITY_FREE, ContactSlots,
    apply_contact_changes, apply_event_changes, apply_reminder_changes, contact_slots, event_fields, reminder_fields,
)
from classicsync.sync.providers.native_pim import (
    TaskFields, changed_fields, changed_values, contact_fields_from_text, contact_text, empty_contact_fields,
    event_fields_from_text, event_text, normalized_contact_fields, normalized_event, normalized_task, task_fields_from_text,
    task_text,
)

UNDEFINED = 9223372036854775807


class FakeObjC:
    def __init__(self, **values):
        self.__dict__["values"] = dict(values)

    def __getattr__(self, name):
        values = self.__dict__["values"]
        if name.startswith("set") and name.endswith("_"):
            key = name[3].lower() + name[4:-1]

            def setter(value):
                values[key] = value
                values["is" + key[0].upper() + key[1:]] = value
            return setter
        if name in values:
            return lambda: values[name]
        raise AttributeError(name)


class FakeDate:
    def __init__(self, moment):
        self.moment = moment

    def timeIntervalSince1970(self):
        return self.moment.timestamp()


class FakeFactory:
    def labeled(self, label, value):
        return FakeObjC(label=label, value=value)

    def phone(self, text):
        return FakeObjC(stringValue=text)

    def postal_address(self, parts):
        return FakeObjC(street=parts["street"], city=parts["city"], state=parts["state"], postalCode=parts["postal_code"],
                        country=parts["country"])

    def relation(self, name):
        return FakeObjC(name=name)

    def date_components(self, day):
        return FakeObjC(year=day.year, month=day.month, day=day.day)

    def date(self, moment):
        return FakeDate(moment)

    def alarm(self, minutes):
        return FakeObjC(relativeOffset=-60.0 * minutes)


def labeled(label, value):
    return FakeObjC(label=label, value=value)


def mac_contact():
    return FakeObjC(
        identifier="ABC:ABPerson", givenName="Grace", familyName="Hopper", middleName="", namePrefix="", nameSuffix="",
        organizationName="Navy", departmentName="", jobTitle="", note="",
        phoneNumbers=[labeled(LABEL_MOBILE, FakeObjC(stringValue="+1 555 0101")),
                      labeled(LABEL_MOBILE, FakeObjC(stringValue="+1 555 0199")),
                      labeled(LABEL_WORK, FakeObjC(stringValue="+1 555 0100"))],
        emailAddresses=[labeled(LABEL_WORK, "grace@example.com")],
        postalAddresses=[labeled(LABEL_HOME, FakeObjC(street="1 Main St", city="Arlington", state="VA", postalCode="22201",
                                                      country="USA"))],
        urlAddresses=[], birthday=FakeObjC(year=1906, month=12, day=9),
        dates=[labeled(LABEL_ANNIVERSARY, FakeObjC(year=UNDEFINED, month=6, day=1))],
        contactRelations=[labeled(LABEL_SPOUSE, FakeObjC(name="Vincent"))],
    )


def test_contact_slots_and_text():
    slots = contact_slots(mac_contact())
    assert slots.values["mobile_phone"] == "+1 555 0101"
    assert slots.values["work_phone"] == "+1 555 0100"
    assert slots.values["home_city"] == "Arlington"
    assert slots.values["birthday"] == date(1906, 12, 9)
    assert slots.values["anniversary"] is None
    assert slots.values["spouse"] == "Vincent"
    text = contact_text(slots.values, "ABC:ABPerson")
    assert "TEL;TYPE=cell:+1 555 0101" in text and "UID:ABC:ABPerson" in text


def test_contact_changes_keep_entries_the_device_cannot_hold():
    contact = mac_contact()
    slots = contact_slots(contact)
    before = normalized_contact_fields(slots.values)
    text = contact_text(slots.values).replace("TEL;TYPE=cell:+1 555 0101", "TEL;TYPE=cell:+1 555 0102")
    text = text.replace("Arlington", "Washington")
    changes = changed_values(before, contact_fields_from_text(text))
    assert set(changes) == {"mobile_phone", "home_city"}
    apply_contact_changes(contact, slots, changes, FakeFactory())
    phones = [(entry.label(), entry.value().stringValue()) for entry in contact.phoneNumbers()]
    assert phones == [(LABEL_MOBILE, "+1 555 0102"), (LABEL_MOBILE, "+1 555 0199"), (LABEL_WORK, "+1 555 0100")]
    address = contact.postalAddresses()[0]
    assert address.label() == LABEL_HOME and address.value().city() == "Washington" and address.value().postalCode() == "22201"
    assert contact.contactRelations()[0].value().name() == "Vincent"


def test_contact_field_removal_and_addition():
    contact = mac_contact()
    slots = contact_slots(contact)
    changes = {"work_phone": "", "email2": "second@example.com", "given_name": "Amazing Grace", "anniversary": date(1930, 6, 15)}
    apply_contact_changes(contact, slots, changes, FakeFactory())
    assert [entry.value().stringValue() for entry in contact.phoneNumbers()] == ["+1 555 0101", "+1 555 0199"]
    assert [entry.value() for entry in contact.emailAddresses()] == ["grace@example.com", "second@example.com"]
    assert contact.givenName() == "Amazing Grace"
    assert contact.dates()[0].value().year() == 1930


def test_new_contact():
    contact = FakeObjC(phoneNumbers=[], emailAddresses=[], postalAddresses=[])
    text = "BEGIN:VCARD\r\nVERSION:4.0\r\nN:Lovelace;Ada;;;\r\nTEL;TYPE=cell:123\r\nADR;TYPE=work:;;1 Lab;London;;;UK\r\nEND:VCARD\r\n"
    changes = changed_values(empty_contact_fields(), contact_fields_from_text(text))
    apply_contact_changes(contact, ContactSlots(), changes, FakeFactory())
    assert contact.familyName() == "Lovelace" and contact.givenName() == "Ada"
    assert contact.phoneNumbers()[0].label() == LABEL_MOBILE
    assert contact.postalAddresses()[0].label() == LABEL_WORK
    assert contact.postalAddresses()[0].value().country() == "UK"


def test_notes_not_written_without_access():
    contact = mac_contact()
    slots = contact_slots(contact, notes_available=False)
    apply_contact_changes(contact, slots, {"notes": "secret"}, FakeFactory())
    assert contact.note() == ""


def mac_event(**overrides):
    values = dict(
        title="Review", location="Room 1", notes=None, startDate=FakeDate(datetime(2026, 12, 1, 10, tzinfo=timezone.utc)),
        endDate=FakeDate(datetime(2026, 12, 1, 11, tzinfo=timezone.utc)), isAllDay=False,
        alarms=[FakeObjC(relativeOffset=-900.0)], availability=0, hasRecurrenceRules=False,
        calendarItemIdentifier="EV1", calendarItemExternalIdentifier="ext-1",
    )
    values.update(overrides)
    return FakeObjC(**values)


def test_event_mapping_round_trip():
    event = mac_event()
    fields = event_fields(event)
    assert fields.reminder_minutes == 15 and fields.busy == 2
    text = event_text(fields, "ext-1")
    assert "DTSTART:20261201T100000Z" in text and "TRIGGER:-PT15M" in text
    incoming = event_fields_from_text(text.replace("SUMMARY:Review", "SUMMARY:Design review").replace("TRANSP:OPAQUE", "TRANSP:TRANSPARENT")
                                      .replace("X-MICROSOFT-CDO-BUSYSTATUS:BUSY", "X-MICROSOFT-CDO-BUSYSTATUS:FREE"))
    changes = changed_fields(normalized_event(fields), incoming, ignored=("recurring",))
    assert set(changes) == {"summary", "busy"}
    apply_event_changes(event, incoming, changes, FakeFactory())
    assert event.title() == "Design review" and event.availability() == AVAILABILITY_FREE
    assert event.startDate().moment == datetime(2026, 12, 1, 10, tzinfo=timezone.utc)


def test_all_day_event_mapping():
    start = datetime(2026, 12, 24).astimezone()
    event = mac_event(isAllDay=True, startDate=FakeDate(start), endDate=FakeDate(start + timedelta(days=1, hours=23, minutes=59, seconds=59)))
    fields = event_fields(event)
    assert (fields.start, fields.end) == (date(2026, 12, 24), date(2026, 12, 26))
    incoming = event_fields_from_text(event_text(fields, "x").replace("DTEND;VALUE=DATE:20261226", "DTEND;VALUE=DATE:20261227"))
    apply_event_changes(event, incoming, changed_fields(normalized_event(fields), incoming), FakeFactory())
    assert event.isAllDay() is True
    assert event.endDate().moment == datetime(2026, 12, 27).astimezone() - timedelta(seconds=1)


def test_reminder_mapping():
    reminder = FakeObjC(title="Write report", notes=None, isCompleted=False, completionDate=None,
                        startDateComponents=None, dueDateComponents=FakeObjC(year=2026, month=12, day=5), priority=1)
    fields = reminder_fields(reminder)
    text = task_text(fields, "R1")
    assert "DUE;VALUE=DATE:20261205" in text and "PRIORITY:1" in text
    incoming = task_fields_from_text(text.replace("STATUS:NEEDS-ACTION", "STATUS:COMPLETED\r\nCOMPLETED:20261203T120000Z"))
    changes = changed_fields(normalized_task(fields), incoming)
    assert set(changes) == {"completed", "completed_at"}
    apply_reminder_changes(reminder, incoming, changes, FakeFactory())
    assert reminder.isCompleted() is True
    assert reminder.completionDate().moment == datetime(2026, 12, 3, 12, tzinfo=timezone.utc)
    assert reminder.dueDateComponents().day() == 5


def test_new_reminder():
    reminder = FakeObjC()
    incoming = task_fields_from_text(task_text(TaskFields(summary="Call", due=date(2027, 1, 2)), "new"))
    apply_reminder_changes(reminder, incoming, changed_fields(TaskFields(), incoming), FakeFactory())
    assert reminder.title() == "Call" and reminder.dueDateComponents().year() == 2027

