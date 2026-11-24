from datetime import date

from classicsync.rapi.cedb import CEVT_BLOB, CEVT_FILETIME, CEVT_I2, CEVT_I4, CEVT_LPWSTR, CEVT_UI2, PropertyValue
from classicsync.sync.pim.icalendar import appointment_to_ical, ical_to_appointment, ical_to_task, task_to_ical
from classicsync.sync.pim.properties import NO_DATE
from classicsync.sync.pim.record import filetime_for_local_date, property_map
from classicsync.sync.pim.text import fold_line, unfold
from classicsync.sync.pim.vcard import contact_to_vcard, vcard_to_contact
from classicsync.sync.rawjson import properties_from_json, properties_to_json, record_from_json, record_to_json


def prop(identifier, value_type, value):
    return PropertyValue(identifier, value_type, value)


CE2_APPOINTMENT = [
    prop(0x420D, CEVT_FILETIME, 124966224000000000), prop(0x4223, CEVT_I2, 0), prop(0x4213, CEVT_I4, 60),
    prop(0x4215, CEVT_I4, 2), prop(0x4501, CEVT_I4, 15), prop(0x4503, CEVT_I2, 1), prop(0x450A, CEVT_I4, 13),
    prop(0x0002, CEVT_I4, 0), prop(0x000F, CEVT_I2, 2), prop(0x0004, CEVT_I2, 0), prop(0x0037, CEVT_LPWSTR, "Lunch meeting"),
    prop(0x4208, CEVT_LPWSTR, ""), prop(0x0017, CEVT_BLOB, b""), prop(0x4509, CEVT_LPWSTR, "Alarm1.wav"),
    prop(0x0016, CEVT_BLOB, b""), prop(0x0067, CEVT_BLOB, bytes.fromhex("040000008200e00074c5b7101a82e008")),
]

CE1_TASK = [
    prop(0x4104, CEVT_FILETIME, NO_DATE), prop(0x4028, CEVT_LPWSTR, ""), prop(0x4126, CEVT_I2, 0),
    prop(0x0037, CEVT_LPWSTR, "Buy milk"), prop(0x1000, CEVT_LPWSTR, ""), prop(0x0026, CEVT_I4, 0x2033),
    prop(0x4105, CEVT_FILETIME, NO_DATE), prop(0x410F, CEVT_FILETIME, 124649280000000000), prop(0x410F, CEVT_I2, 1),
    prop(0x4509, CEVT_LPWSTR, "Alarm1.wav"), prop(0x4501, CEVT_I4, 0), prop(0x0003, CEVT_I2, 0), prop(0x4503, CEVT_I2, 0),
    prop(0x450A, CEVT_I4, 13), prop(0x0002, CEVT_I4, 0),
]

CONTACT = [
    prop(0x3A06, CEVT_LPWSTR, "Ada"), prop(0x3A11, CEVT_LPWSTR, "Lovelace"), prop(0x4013, CEVT_LPWSTR, "Lovelace, Ada"),
    prop(0x3A16, CEVT_LPWSTR, "Analytical; Engines"),
    prop(0x3A08, CEVT_LPWSTR, "+44 20 1234"), prop(0x3A1C, CEVT_LPWSTR, "07700 900000"), prop(0x3A24, CEVT_LPWSTR, "fax 1"),
    prop(0x4083, CEVT_LPWSTR, "ada@example.org"), prop(0x4093, CEVT_LPWSTR, "ada2@example.org"),
    prop(0x4040, CEVT_LPWSTR, "1 Street"), prop(0x4041, CEVT_LPWSTR, "London"), prop(0x4044, CEVT_LPWSTR, "UK"),
    prop(0x4045, CEVT_LPWSTR, "Work Rd"), prop(0x404B, CEVT_LPWSTR, "Elsewhere"),
    prop(0x1000, CEVT_LPWSTR, "Line one\nLine, two; three"), prop(0x4005, CEVT_LPWSTR, "Business, VIP"),
    prop(0x4001, CEVT_FILETIME, filetime_for_local_date(date(1815, 12, 10))), prop(0x400A, CEVT_LPWSTR, "William"),
    prop(0x4317, CEVT_LPWSTR, "unknown kept"), prop(0x7777, CEVT_UI2, 5),
]


def sorted_props(properties):
    return sorted(((p.identifier, p.value_type, p.value) for p in properties), key=lambda item: (item[0], item[1]))


def test_raw_json_is_lossless():
    properties = CE2_APPOINTMENT + CE1_TASK + [prop(0x1234, CEVT_UI2, 65535)]
    assert properties_from_json(properties_to_json(properties)) == properties
    oid, decoded = record_from_json(record_to_json(0x556, properties, "Appointments Database"))
    assert oid == 0x556 and decoded == properties


def test_vcard_round_trip_keeps_every_property():
    card = contact_to_vcard(CONTACT, "ada")
    assert "N:Lovelace;Ada;;;" in card
    assert "ORG:Analytical\\; Engines" in card
    assert "BDAY:18151210" in card
    assert "TEL;TYPE=cell:07700 900000" in card
    assert sorted_props(vcard_to_contact(card, CONTACT)) == sorted_props(CONTACT)


def test_vcard_edit_updates_only_owned_properties():
    card = contact_to_vcard(CONTACT, "ada").replace("EMAIL;PREF=2:ada2@example.org\r\n", "").replace("Lovelace;Ada", "Byron;Ada")
    values = property_map(vcard_to_contact(card, CONTACT))
    assert values[(0x3A11, CEVT_LPWSTR)] == "Byron"
    assert values[(0x4013, CEVT_LPWSTR)] == "Byron, Ada"
    assert values[(0x4093, CEVT_LPWSTR)] == ""
    assert values[(0x4317, CEVT_LPWSTR)] == "unknown kept"
    assert values[(0x7777, CEVT_UI2)] == 5


def test_new_vcard_from_another_application():
    card = ("BEGIN:VCARD\nVERSION:3.0\nFN:Grace Hopper\nN:Hopper;Grace;Brewster;Rear Admiral;\n"
            "TEL;TYPE=HOME:555 1\nTEL;TYPE=WORK:555 2\nTEL;TYPE=WORK:555 3\nitem1.EMAIL;TYPE=INTERNET:grace@navy.mil\n"
            "ADR;TYPE=WORK:;;Pentagon;Arlington;VA;22202;USA\nBDAY:1906-12-09\nEND:VCARD\n")
    values = property_map(vcard_to_contact(card))
    assert values[(0x3A06, CEVT_LPWSTR)] == "Grace"
    assert values[(0x4013, CEVT_LPWSTR)] == "Hopper, Grace"
    assert values[(0x4023, CEVT_LPWSTR)] == "Rear Admiral"
    assert values[(0x3A09, CEVT_LPWSTR)] == "555 1"
    assert values[(0x3A08, CEVT_LPWSTR)] == "555 2"
    assert values[(0x4007, CEVT_LPWSTR)] == "555 3"
    assert values[(0x4083, CEVT_LPWSTR)] == "grace@navy.mil"
    assert values[(0x4046, CEVT_LPWSTR)] == "Arlington"
    assert values[(0x4001, CEVT_FILETIME)] == filetime_for_local_date(date(1906, 12, 9))


def test_appointment_round_trip():
    text = appointment_to_ical(CE2_APPOINTMENT, "x")
    assert "DTSTART:19970101T200000Z" in text
    assert "DTEND:19970101T210000Z" in text
    assert "TRIGGER:-PT15M" in text
    assert "UID:040000008200E00074C5B7101A82E008" in text
    assert sorted_props(ical_to_appointment(text, CE2_APPOINTMENT)) == sorted_props(CE2_APPOINTMENT)


def test_appointment_from_another_application():
    text = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART;TZID=Europe/London:20260704T093000\r\nDURATION:PT1H30M\r\n"
            "SUMMARY:Standup\r\nLOCATION:Room 1\r\nDESCRIPTION:agenda\\nitems\r\nCLASS:PRIVATE\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    values = property_map(ical_to_appointment(text, os_major=2))
    assert values[(0x0037, CEVT_LPWSTR)] == "Standup"
    assert values[(0x4213, CEVT_I4)] == 90
    assert values[(0x4503, CEVT_I2)] == 0
    assert values[(0x0004, CEVT_I2)] == 1
    assert values[(0x1000, CEVT_LPWSTR)] == "agenda\nitems"
    assert "DTSTART:20260704T083000Z" in appointment_to_ical(ical_to_appointment(text, os_major=2))


def test_all_day_appointment_on_ce1():
    text = "BEGIN:VEVENT\nDTSTART;VALUE=DATE:19960102\nDTEND;VALUE=DATE:19960104\nSUMMARY:Trip\nEND:VEVENT\n"
    properties = ical_to_appointment(text, os_major=1)
    values = property_map(properties)
    assert values[(0x4215, CEVT_I4)] == 1
    assert values[(0x4213, CEVT_I4)] == 2880
    assert values[(0x4212, CEVT_FILETIME)] == values[(0x420D, CEVT_FILETIME)] == filetime_for_local_date(date(1996, 1, 2))
    assert (0x000F, CEVT_I2) not in values
    assert "DTSTART;VALUE=DATE:19960102" in appointment_to_ical(properties)


def test_task_round_trip():
    text = task_to_ical(CE1_TASK, "t")
    assert "STATUS:COMPLETED" in text and "PRIORITY:3" in text and "DUE" not in text
    assert sorted_props(ical_to_task(text, CE1_TASK, os_major=1)) == sorted_props(CE1_TASK)
    reopened = text.replace("STATUS:COMPLETED", "STATUS:NEEDS-ACTION").replace("COMPLETED:", "X-OLD:")
    reopened = reopened.replace("SUMMARY:Buy milk", "SUMMARY:Buy milk\r\nDUE;VALUE=DATE:19960105")
    values = property_map(ical_to_task(reopened, CE1_TASK, os_major=1))
    assert values[(0x410F, CEVT_I2)] == 0
    assert values[(0x4105, CEVT_FILETIME)] == filetime_for_local_date(date(1996, 1, 5))


def test_line_folding_round_trip():
    line = "DESCRIPTION:" + "é" * 100
    folded = fold_line(line)
    assert all(len(part.encode("utf-8")) <= 75 for part in folded.split("\r\n"))
    assert unfold(folded) == [line]


CE3_CONTACT = [
    prop(0x3A09, CEVT_LPWSTR, "*See Notes"), prop(0x3A08, CEVT_LPWSTR, "(1)800-443-1254"),
    prop(0x4013, CEVT_LPWSTR, "HP, Automated Information Service"), prop(0x3A16, CEVT_LPWSTR, "Hewlett-Packard"),
    prop(0x3A06, CEVT_LPWSTR, "Automated Information Service"), prop(0x3A11, CEVT_LPWSTR, "HP"),
    prop(0x0017, CEVT_BLOB, b"Country\tTelephone\rUSA\t\t+1 (970) 635-1000\r\x00"),
]


def test_ce3_contact_notes_come_from_the_blob():
    card = contact_to_vcard(CE3_CONTACT)
    assert "NOTE:Country\tTelephone\\nUSA\t\t+1 (970) 635-1000\\n" in card


def test_unchanged_blob_notes_are_not_copied_to_text_notes():
    card = contact_to_vcard(CE3_CONTACT)
    values = property_map(vcard_to_contact(card, CE3_CONTACT))
    assert (0x1000, CEVT_LPWSTR) not in values
    assert values[(0x0017, CEVT_BLOB)] == CE3_CONTACT[-1].value


def test_edited_blob_notes_are_written_as_text_notes():
    card = contact_to_vcard(CE3_CONTACT).replace("NOTE:Country", "NOTE:Edited")
    values = property_map(vcard_to_contact(card, CE3_CONTACT))
    assert values[(0x1000, CEVT_LPWSTR)].startswith("Edited")
