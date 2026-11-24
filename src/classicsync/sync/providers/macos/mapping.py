import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from ..native_pim import (
    BUSY_BUSY, BUSY_FREE, BUSY_OUT_OF_OFFICE, BUSY_TENTATIVE, EventFields, TaskFields, empty_contact_fields,
)

LABEL_HOME = "_$!<Home>!$_"
LABEL_WORK = "_$!<Work>!$_"
LABEL_OTHER = "_$!<Other>!$_"
LABEL_MOBILE = "_$!<Mobile>!$_"
LABEL_IPHONE = "iPhone"
LABEL_MAIN = "_$!<Main>!$_"
LABEL_HOME_FAX = "_$!<HomeFAX>!$_"
LABEL_WORK_FAX = "_$!<WorkFAX>!$_"
LABEL_OTHER_FAX = "_$!<OtherFAX>!$_"
LABEL_PAGER = "_$!<Pager>!$_"
LABEL_CAR = "car"
LABEL_ASSISTANT_PHONE = "assistant"
LABEL_ANNIVERSARY = "_$!<Anniversary>!$_"
LABEL_SPOUSE = "_$!<Spouse>!$_"
LABEL_CHILD = "_$!<Child>!$_"
LABEL_ASSISTANT = "_$!<Assistant>!$_"

UNDEFINED_COMPONENT = 2 ** 31

NAME_ATTRIBUTES = {
    "given_name": "givenName", "surname": "familyName", "middle_name": "middleName", "name_prefix": "namePrefix",
    "generation": "nameSuffix", "company": "organizationName", "department": "departmentName", "title": "jobTitle",
}
GENERIC_PHONE_FIELDS = ("work_phone", "work_phone2", "home_phone", "home_phone2", "mobile_phone")
PHONE_LABEL_FIELDS = {
    LABEL_WORK: ("work_phone", "work_phone2"), LABEL_HOME: ("home_phone", "home_phone2"), LABEL_MOBILE: ("mobile_phone",),
    LABEL_IPHONE: ("mobile_phone",), LABEL_CAR: ("car_phone",), LABEL_PAGER: ("pager",), LABEL_WORK_FAX: ("work_fax",),
    LABEL_HOME_FAX: ("home_fax",), LABEL_OTHER_FAX: ("work_fax", "home_fax"), LABEL_ASSISTANT_PHONE: ("assistant_phone",),
}
PHONE_DEFAULT_LABELS = {
    "work_phone": LABEL_WORK, "work_phone2": LABEL_WORK, "home_phone": LABEL_HOME, "home_phone2": LABEL_HOME,
    "mobile_phone": LABEL_MOBILE, "car_phone": LABEL_CAR, "pager": LABEL_PAGER, "work_fax": LABEL_WORK_FAX,
    "home_fax": LABEL_HOME_FAX, "assistant_phone": LABEL_ASSISTANT_PHONE,
}
EMAIL_FIELDS = ("email1", "email2", "email3")
ADDRESS_PREFIXES = {LABEL_HOME: "home", LABEL_WORK: "work"}
ADDRESS_LABELS = {"home": LABEL_HOME, "work": LABEL_WORK, "other": LABEL_OTHER}
ADDRESS_ATTRIBUTES = {"street": "street", "city": "city", "state": "state", "postal_code": "postalCode", "country": "country"}
RELATION_FIELDS = {LABEL_SPOUSE: "spouse", LABEL_CHILD: "children", LABEL_ASSISTANT: "assistant"}
RELATION_LABELS = {name: label for label, name in RELATION_FIELDS.items()}

AVAILABILITY_NOT_SUPPORTED = -1
AVAILABILITY_BUSY = 0
AVAILABILITY_FREE = 1
AVAILABILITY_TENTATIVE = 2
AVAILABILITY_UNAVAILABLE = 3
BUSY_FROM_AVAILABILITY = {
    AVAILABILITY_BUSY: BUSY_BUSY, AVAILABILITY_FREE: BUSY_FREE, AVAILABILITY_TENTATIVE: BUSY_TENTATIVE,
    AVAILABILITY_UNAVAILABLE: BUSY_OUT_OF_OFFICE,
}
AVAILABILITY_FROM_BUSY = {busy: availability for availability, busy in BUSY_FROM_AVAILABILITY.items()}


def text_of(value):
    return "" if value is None else str(value)


def setter_name(attribute):
    return "set" + attribute[0].upper() + attribute[1:] + "_"


def day_from_components(components):
    if components is None:
        return None
    year, month, day = components.year(), components.month(), components.day()
    if any(value is None or value >= UNDEFINED_COMPONENT or value <= 0 for value in (year, month, day)):
        return None
    return date(year, month, day)


def moment_from_nsdate(value):
    if value is None:
        return None
    return datetime.fromtimestamp(value.timeIntervalSince1970(), timezone.utc)


def local_midnight(day):
    return datetime.combine(day, time()).astimezone()


@dataclass
class ContactSlots:
    values: dict = field(default_factory=empty_contact_fields)
    positions: dict = field(default_factory=dict)
    notes_available: bool = True


def labeled_entries(contact, attribute):
    return list(getattr(contact, attribute)() or [])


def contact_slots(contact, notes_available=True):
    slots = ContactSlots(notes_available=notes_available)
    values = slots.values
    for name, attribute in NAME_ATTRIBUTES.items():
        values[name] = text_of(getattr(contact, attribute)())
    if notes_available:
        values["notes"] = text_of(contact.note())
    for index, entry in enumerate(labeled_entries(contact, "phoneNumbers")):
        candidates = PHONE_LABEL_FIELDS.get(text_of(entry.label()), GENERIC_PHONE_FIELDS)
        target = next((name for name in candidates if name not in slots.positions), None)
        if target:
            values[target] = text_of(entry.value().stringValue())
            slots.positions[target] = ("phoneNumbers", index)
    for index, entry in enumerate(labeled_entries(contact, "emailAddresses")[:len(EMAIL_FIELDS)]):
        values[EMAIL_FIELDS[index]] = text_of(entry.value())
        slots.positions[EMAIL_FIELDS[index]] = ("emailAddresses", index)
    for index, entry in enumerate(labeled_entries(contact, "postalAddresses")):
        prefix = ADDRESS_PREFIXES.get(text_of(entry.label()), "other")
        if prefix in slots.positions:
            prefix = "other"
        if prefix in slots.positions:
            continue
        slots.positions[prefix] = ("postalAddresses", index)
        address = entry.value()
        for part, attribute in ADDRESS_ATTRIBUTES.items():
            values[f"{prefix}_{part}"] = text_of(getattr(address, attribute)())
    urls = labeled_entries(contact, "urlAddresses")
    if urls:
        values["web_page"] = text_of(urls[0].value())
        slots.positions["web_page"] = ("urlAddresses", 0)
    values["birthday"] = day_from_components(contact.birthday())
    for index, entry in enumerate(labeled_entries(contact, "dates")):
        if text_of(entry.label()) == LABEL_ANNIVERSARY and "anniversary" not in slots.positions:
            values["anniversary"] = day_from_components(entry.value())
            slots.positions["anniversary"] = ("dates", index)
    for index, entry in enumerate(labeled_entries(contact, "contactRelations")):
        name = RELATION_FIELDS.get(text_of(entry.label()))
        if name and name not in slots.positions:
            values[name] = text_of(entry.value().name())
            slots.positions[name] = ("contactRelations", index)
    return slots


class CollectionEdits:
    def __init__(self, contact):
        self.contact = contact
        self.collections = {}
        self.removed = {}

    def entries(self, attribute):
        if attribute not in self.collections:
            self.collections[attribute] = labeled_entries(self.contact, attribute)
            self.removed[attribute] = set()
        return self.collections[attribute]

    def put(self, position, attribute, label, value, factory):
        entries = self.entries(attribute)
        if position is not None:
            index = position[1]
            if value is None:
                self.removed[attribute].add(index)
            else:
                entries[index] = factory.labeled(text_of(entries[index].label()) or label, value)
        elif value is not None:
            entries.append(factory.labeled(label, value))

    def apply(self):
        for attribute, entries in self.collections.items():
            kept = [entry for index, entry in enumerate(entries) if index not in self.removed[attribute]]
            getattr(self.contact, setter_name(attribute))(kept)


def apply_contact_changes(contact, slots, changes, factory):
    edits = CollectionEdits(contact)
    changed_addresses = set()
    for name, value in changes.items():
        position = slots.positions.get(name)
        if name in NAME_ATTRIBUTES:
            getattr(contact, setter_name(NAME_ATTRIBUTES[name]))(value or "")
        elif name == "notes":
            if slots.notes_available:
                contact.setNote_(value or "")
        elif name in PHONE_DEFAULT_LABELS:
            edits.put(position, "phoneNumbers", PHONE_DEFAULT_LABELS[name], factory.phone(value) if value else None, factory)
        elif name in EMAIL_FIELDS:
            edits.put(position, "emailAddresses", LABEL_OTHER, value or None, factory)
        elif name == "web_page":
            edits.put(position, "urlAddresses", LABEL_HOME, value or None, factory)
        elif name == "birthday":
            contact.setBirthday_(factory.date_components(value) if value else None)
        elif name == "anniversary":
            edits.put(position, "dates", LABEL_ANNIVERSARY, factory.date_components(value) if value else None, factory)
        elif name in RELATION_LABELS:
            edits.put(position, "contactRelations", RELATION_LABELS[name], factory.relation(value) if value else None, factory)
        elif name.split("_", 1)[0] in ADDRESS_LABELS and name.split("_", 1)[1] in ADDRESS_ATTRIBUTES:
            changed_addresses.add(name.split("_", 1)[0])
    merged = {**slots.values, **changes}
    for prefix in changed_addresses:
        parts = {part: merged.get(f"{prefix}_{part}") or "" for part in ADDRESS_ATTRIBUTES}
        address = factory.postal_address(parts) if any(parts.values()) else None
        edits.put(slots.positions.get(prefix), "postalAddresses", ADDRESS_LABELS[prefix], address, factory)
    edits.apply()


def event_fields(event):
    all_day = bool(event.isAllDay())
    start = moment_from_nsdate(event.startDate())
    end = moment_from_nsdate(event.endDate()) or start
    if all_day:
        start_day = start.astimezone().date()
        end_day = (end - timedelta(seconds=1)).astimezone().date() + timedelta(days=1)
        start, end = start_day, max(end_day, start_day + timedelta(days=1))
    alarms = [alarm.relativeOffset() for alarm in (event.alarms() or [])]
    reminder = max(0, int(-min(alarms) // 60)) if alarms else None
    return EventFields(
        summary=text_of(event.title()), location=text_of(event.location()), description=text_of(event.notes()),
        start=start, end=end, all_day=all_day, reminder_minutes=reminder,
        busy=BUSY_FROM_AVAILABILITY.get(event.availability(), BUSY_BUSY), recurring=bool(event.hasRecurrenceRules()),
    )


def apply_event_changes(event, fields, changes, factory):
    if "summary" in changes:
        event.setTitle_(fields.summary)
    if "location" in changes:
        event.setLocation_(fields.location or None)
    if "description" in changes:
        event.setNotes_(fields.description or None)
    if {"start", "end", "all_day"} & set(changes):
        event.setAllDay_(fields.all_day)
        if fields.all_day:
            event.setStartDate_(factory.date(local_midnight(fields.start)))
            event.setEndDate_(factory.date(local_midnight(fields.end) - timedelta(seconds=1)))
        else:
            event.setStartDate_(factory.date(fields.start))
            event.setEndDate_(factory.date(fields.end))
    if "reminder_minutes" in changes:
        event.setAlarms_([factory.alarm(fields.reminder_minutes)] if fields.reminder_minutes is not None else None)
    if "busy" in changes and event.availability() != AVAILABILITY_NOT_SUPPORTED:
        event.setAvailability_(AVAILABILITY_FROM_BUSY.get(fields.busy, AVAILABILITY_BUSY))


def reminder_fields(reminder):
    completed = bool(reminder.isCompleted())
    return TaskFields(
        summary=text_of(reminder.title()), description=text_of(reminder.notes()),
        start=day_from_components(reminder.startDateComponents()), due=day_from_components(reminder.dueDateComponents()),
        completed=completed, completed_at=moment_from_nsdate(reminder.completionDate()) if completed else None,
        priority=int(reminder.priority() or 0),
    )


def apply_reminder_changes(reminder, fields, changes, factory):
    if "summary" in changes:
        reminder.setTitle_(fields.summary)
    if "description" in changes:
        reminder.setNotes_(fields.description or None)
    if "start" in changes:
        reminder.setStartDateComponents_(factory.date_components(fields.start) if fields.start else None)
    if "due" in changes:
        reminder.setDueDateComponents_(factory.date_components(fields.due) if fields.due else None)
    if "completed" in changes or "completed_at" in changes:
        reminder.setCompleted_(fields.completed)
        if fields.completed and fields.completed_at:
            reminder.setCompletionDate_(factory.date(fields.completed_at))
    if "priority" in changes:
        reminder.setPriority_(fields.priority)


def item_stamp(native_item, text):
    modified = None
    getter = getattr(native_item, "lastModifiedDate", None)
    if getter is not None:
        modified = moment_from_nsdate(getter())
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    return f"{modified.timestamp():.0f}:{digest}" if modified else digest
