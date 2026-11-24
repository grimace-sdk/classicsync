from datetime import date, datetime, timezone

from classicsync.rapi import cedb
from classicsync.sync.objects import CALENDAR, CONTACTS, TASKS, DeviceRecord
from classicsync.sync.pim.record import property_map
from classicsync.sync.providers.outlook.mapping import (
    NO_DATE, apply_text, item_in_range, item_text, resolve_folder,
)
from classicsync.sync.providers.pim_store import RemotePimStore

GIVEN_NAME = (0x3A06, cedb.CEVT_LPWSTR)
SURNAME = (0x3A11, cedb.CEVT_LPWSTR)
MOBILE = (0x3A1C, cedb.CEVT_LPWSTR)
SUBJECT = (0x0037, cedb.CEVT_LPWSTR)
START = (0x420D, cedb.CEVT_FILETIME)
DURATION = (0x4213, cedb.CEVT_I4)


class FakeComItem:
    def __init__(self, **values):
        self.__dict__.update(values)
        self.saved = 0
        self.deleted = False

    def Save(self):
        self.saved += 1
        self.LastModificationTime = datetime(2026, 11, 24, 12, 0, self.saved)

    def Delete(self):
        self.deleted = True

    def GetRecurrencePattern(self):
        return self.pattern


def outlook_contact(**overrides):
    values = dict(
        Class=40, EntryID="C1", LastModificationTime=datetime(2026, 1, 1), FirstName="Grace", LastName="Hopper",
        MiddleName="", Title="", Suffix="", CompanyName="Navy", Department="", JobTitle="Rear Admiral", OfficeLocation="",
        BusinessTelephoneNumber="+1 555 0100", Business2TelephoneNumber="", HomeTelephoneNumber="",
        Home2TelephoneNumber="", MobileTelephoneNumber="+1 555 0101", CarTelephoneNumber="", PagerNumber="",
        BusinessFaxNumber="", HomeFaxNumber="", AssistantName="", AssistantTelephoneNumber="", Spouse="", Children="",
        WebPage="", Categories="", Email1Address="grace@example.com", Email2Address="", Email3Address="",
        HomeAddressStreet="", HomeAddressCity="Arlington", HomeAddressState="VA", HomeAddressPostalCode="",
        HomeAddressCountry="", BusinessAddressStreet="", BusinessAddressCity="", BusinessAddressState="",
        BusinessAddressPostalCode="", BusinessAddressCountry="", OtherAddressStreet="", OtherAddressCity="",
        OtherAddressState="", OtherAddressPostalCode="", OtherAddressCountry="", Body="Line one\r\nLine two",
        Birthday=datetime(1906, 12, 9), Anniversary=NO_DATE, IMAddress="grace@im", User1="kept",
    )
    values.update(overrides)
    return FakeComItem(**values)


def outlook_appointment(**overrides):
    values = dict(
        Class=26, EntryID="A1", GlobalAppointmentID="GLOBAL1", LastModificationTime=datetime(2026, 1, 1), Subject="Review",
        Location="Room 1", Body="", Start=datetime(2026, 12, 1, 10, 0), End=datetime(2026, 12, 1, 11, 0),
        StartUTC=datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc), EndUTC=datetime(2026, 12, 1, 11, 0, tzinfo=timezone.utc),
        AllDayEvent=False, ReminderSet=True, ReminderMinutesBeforeStart=15, BusyStatus=2, Sensitivity=0, Categories="Work",
        IsRecurring=False, RequiredAttendees="ada@example.com",
    )
    values.update(overrides)
    return FakeComItem(**values)


def outlook_task(**overrides):
    values = dict(
        Class=48, EntryID="T1", LastModificationTime=datetime(2026, 1, 1), Subject="Write report", Body="", StartDate=NO_DATE,
        DueDate=datetime(2026, 12, 5), Complete=False, DateCompleted=NO_DATE, Importance=2, Sensitivity=0, Categories="",
        TotalWork=90,
    )
    values.update(overrides)
    return FakeComItem(**values)


def test_contact_text_maps_outlook_fields():
    text = item_text(CONTACTS.key, outlook_contact())
    assert "N:Hopper;Grace;;;" in text
    assert "TEL;TYPE=cell:+1 555 0101" in text
    assert "EMAIL;PREF=1:grace@example.com" in text
    assert "BDAY:19061209" in text
    assert "NOTE:Line one\\nLine two" in text


def test_contact_update_only_writes_changed_fields():
    item = outlook_contact()
    text = item_text(CONTACTS.key, item).replace("N:Hopper;Grace", "N:Murray;Grace").replace("TEL;TYPE=cell:+1 555 0101\r\n", "")
    apply_text(CONTACTS.key, item, text)
    assert item.LastName == "Murray"
    assert item.MobileTelephoneNumber == ""
    assert item.BusinessTelephoneNumber == "+1 555 0100"
    assert item.Body == "Line one\r\nLine two"
    assert item.IMAddress == "grace@im" and item.User1 == "kept"
    assert item.Anniversary == NO_DATE


def test_new_contact_gets_all_fields():
    item = FakeComItem(LastName="", FirstName="", Birthday=NO_DATE)
    apply_text(CONTACTS.key, item, "BEGIN:VCARD\r\nVERSION:4.0\r\nN:Lovelace;Ada;;;\r\nBDAY:18151210\r\nEND:VCARD\r\n", new=True)
    assert (item.FirstName, item.LastName) == ("Ada", "Lovelace")
    assert item.Birthday == datetime(1815, 12, 10)
    assert not hasattr(item, "MobileTelephoneNumber")


def test_appointment_round_trip_keeps_untouched_fields():
    item = outlook_appointment()
    text = item_text(CALENDAR.key, item)
    assert "UID:GLOBAL1" in text and "DTSTART:20261201T100000Z" in text and "CATEGORIES:Work" in text
    apply_text(CALENDAR.key, item, text.replace("SUMMARY:Review", "SUMMARY:Design review"))
    assert item.Subject == "Design review"
    assert item.StartUTC == datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc)
    assert item.RequiredAttendees == "ada@example.com"


def test_appointment_time_change_writes_utc():
    item = outlook_appointment()
    text = item_text(CALENDAR.key, item).replace("DTSTART:20261201T100000Z", "DTSTART:20261201T090000Z")
    apply_text(CALENDAR.key, item, text)
    assert item.StartUTC == datetime(2026, 12, 1, 9, 0)
    assert item.EndUTC == datetime(2026, 12, 1, 11, 0)


def test_recurring_appointment_times_are_not_written():
    item = outlook_appointment(IsRecurring=True)
    text = item_text(CALENDAR.key, item).replace("DTSTART:20261201T100000Z", "DTSTART:20261201T090000Z")
    text = text.replace("SUMMARY:Review", "SUMMARY:Weekly review")
    apply_text(CALENDAR.key, item, text)
    assert item.Subject == "Weekly review"
    assert item.StartUTC == datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc)


def test_all_day_appointment():
    item = outlook_appointment(AllDayEvent=True, Start=datetime(2026, 12, 24), End=datetime(2026, 12, 26))
    text = item_text(CALENDAR.key, item)
    assert "DTSTART;VALUE=DATE:20261224" in text and "DTEND;VALUE=DATE:20261226" in text


def test_task_mapping():
    item = outlook_task()
    text = item_text(TASKS.key, item)
    assert "DUE;VALUE=DATE:20261205" in text and "PRIORITY:1" in text and "STATUS:NEEDS-ACTION" in text
    completed = text.replace("STATUS:NEEDS-ACTION", "STATUS:COMPLETED\r\nCOMPLETED:20261203T120000Z")
    apply_text(TASKS.key, item, completed)
    assert item.Complete is True
    assert item.DateCompleted == datetime(2026, 12, 3, 12, 0)
    assert item.TotalWork == 90 and item.Importance == 2


def test_calendar_range():
    earliest, latest = date(2026, 11, 1), date(2027, 11, 1)
    assert item_in_range(CALENDAR.key, outlook_appointment(), earliest, latest)
    old = outlook_appointment(Start=datetime(2020, 1, 1), End=datetime(2020, 1, 1, 1))
    assert not item_in_range(CALENDAR.key, old, earliest, latest)
    endless = outlook_appointment(Start=datetime(2020, 1, 1), End=datetime(2020, 1, 1, 1), IsRecurring=True,
                                  pattern=FakeComItem(NoEndDate=True, PatternEndDate=NO_DATE))
    assert item_in_range(CALENDAR.key, endless, earliest, latest)


class FakeFolder:
    def __init__(self, name, children=()):
        self.Name = name
        self.Folders = list(children)


def test_resolve_folder():
    handheld = FakeFolder("Handheld")
    contacts = FakeFolder("Contacts", [handheld])
    archive_contacts = FakeFolder("Contacts")
    namespace = FakeFolder("MAPI", [FakeFolder("Mailbox", [contacts]), FakeFolder("Archive", [archive_contacts])])
    assert resolve_folder(namespace, contacts, "") is contacts
    assert resolve_folder(namespace, contacts, "Handheld") is handheld
    assert resolve_folder(namespace, contacts, "Archive\\Contacts") is archive_contacts


class FakeOutlookStore(RemotePimStore):
    vcard_version = "4.0"

    def __init__(self, object_type, cache_directory, items):
        super().__init__(object_type, cache_directory, 2)
        self.items = {item.EntryID: item for item in items}

    def list_remote(self):
        return {item_id: str(item.LastModificationTime) for item_id, item in self.items.items()}

    def fetch_text(self, item_id):
        return item_text(self.object_type.key, self.items[item_id])

    def put_text(self, item_id, text, uid):
        item = self.items[item_id] if item_id else FakeComItem(EntryID=f"new{len(self.items)}", FirstName="", LastName="")
        apply_text(self.object_type.key, item, text, new=item_id is None)
        item.Save()
        self.items[item.EntryID] = item
        return item.EntryID, str(item.LastModificationTime)

    def delete_remote(self, item_id):
        self.items.pop(item_id).Delete()


def test_store_round_trip_through_device_record(tmp_path):
    contact = outlook_contact()
    store = FakeOutlookStore(CONTACTS, tmp_path, [contact])
    assert list(store.list_items()) == ["C1"]
    record = store.read_item("C1", None)
    values = property_map(record.properties)
    assert values[GIVEN_NAME] == "Grace" and values[MOBILE] == "+1 555 0101"
    changed = [prop if (prop.identifier, prop.value_type) != SURNAME else cedb.PropertyValue(*SURNAME, "Murray")
               for prop in record.properties]
    store.write_item("C1", "00000001", DeviceRecord(changed, 1))
    assert contact.LastName == "Murray" and contact.User1 == "kept" and contact.saved == 1
    new_id, _ = store.write_item(None, "00000002", DeviceRecord([cedb.PropertyValue(*GIVEN_NAME, "Ada")], 2))
    assert store.items[new_id].FirstName == "Ada"


def test_store_writes_device_appointment(tmp_path):
    store = FakeOutlookStore(CALENDAR, tmp_path, [])
    start = 134090892000000000
    item_id, _ = store.write_item(None, "00000003", DeviceRecord([
        cedb.PropertyValue(*SUBJECT, "Lunch"), cedb.PropertyValue(*START, start), cedb.PropertyValue(*DURATION, 60)], 3))
    item = store.items[item_id]
    assert item.Subject == "Lunch" and item.AllDayEvent is False
    assert (item.EndUTC - item.StartUTC).total_seconds() == 3600
