from datetime import date, datetime, time, timedelta, timezone

from ...objects import CALENDAR, CONTACTS, TASKS
from ..native_pim import (
    BUSY_BUSY, EventFields, TaskFields, changed_fields, changed_values, contact_fields_from_text, contact_text,
    empty_contact_fields, event_fields_from_text, event_text, normalized_contact_fields, normalized_event, normalized_task,
    task_fields_from_text, task_text, without_recurring_times,
)

FOLDER_CALENDAR = 9
FOLDER_CONTACTS = 10
FOLDER_TASKS = 13
DEFAULT_FOLDERS = {CONTACTS.key: FOLDER_CONTACTS, CALENDAR.key: FOLDER_CALENDAR, TASKS.key: FOLDER_TASKS}

ITEM_APPOINTMENT = 1
ITEM_CONTACT = 2
ITEM_TASK = 3
ITEM_TYPES = {CONTACTS.key: ITEM_CONTACT, CALENDAR.key: ITEM_APPOINTMENT, TASKS.key: ITEM_TASK}

CLASS_APPOINTMENT = 26
CLASS_CONTACT = 40
CLASS_TASK = 48
ITEM_CLASSES = {CONTACTS.key: CLASS_CONTACT, CALENDAR.key: CLASS_APPOINTMENT, TASKS.key: CLASS_TASK}

NO_DATE_YEAR = 4501
NO_DATE = datetime(NO_DATE_YEAR, 1, 1)

SENSITIVITY_NORMAL = 0
SENSITIVITY_PRIVATE = 2
IMPORTANCE_LOW = 0
IMPORTANCE_NORMAL = 1
IMPORTANCE_HIGH = 2
BUSY_WORKING_ELSEWHERE = 4

CONTACT_PROPERTIES = {
    "given_name": "FirstName", "surname": "LastName", "middle_name": "MiddleName", "name_prefix": "Title",
    "generation": "Suffix", "company": "CompanyName", "department": "Department", "title": "JobTitle",
    "office_location": "OfficeLocation", "work_phone": "BusinessTelephoneNumber",
    "work_phone2": "Business2TelephoneNumber", "home_phone": "HomeTelephoneNumber",
    "home_phone2": "Home2TelephoneNumber", "mobile_phone": "MobileTelephoneNumber", "car_phone": "CarTelephoneNumber",
    "pager": "PagerNumber", "work_fax": "BusinessFaxNumber", "home_fax": "HomeFaxNumber", "assistant": "AssistantName",
    "assistant_phone": "AssistantTelephoneNumber", "spouse": "Spouse", "children": "Children", "web_page": "WebPage",
    "categories": "Categories", "email1": "Email1Address", "email2": "Email2Address", "email3": "Email3Address",
    "home_street": "HomeAddressStreet", "home_city": "HomeAddressCity", "home_state": "HomeAddressState",
    "home_postal_code": "HomeAddressPostalCode", "home_country": "HomeAddressCountry",
    "work_street": "BusinessAddressStreet", "work_city": "BusinessAddressCity", "work_state": "BusinessAddressState",
    "work_postal_code": "BusinessAddressPostalCode", "work_country": "BusinessAddressCountry",
    "other_street": "OtherAddressStreet", "other_city": "OtherAddressCity", "other_state": "OtherAddressState",
    "other_postal_code": "OtherAddressPostalCode", "other_country": "OtherAddressCountry", "notes": "Body",
}
CONTACT_DATE_PROPERTIES = {"birthday": "Birthday", "anniversary": "Anniversary"}


def com_text(value):
    return "" if value is None else str(value).replace("\r\n", "\n")


def com_date(value):
    if value is None or value.year >= NO_DATE_YEAR:
        return None
    return date(value.year, value.month, value.day)


def com_utc(value):
    if value is None or value.year >= NO_DATE_YEAR:
        return None
    return datetime(value.year, value.month, value.day, value.hour, value.minute, value.second, tzinfo=timezone.utc)


def naive_utc(moment):
    moment = moment.astimezone(timezone.utc)
    return datetime(moment.year, moment.month, moment.day, moment.hour, moment.minute, moment.second)


def naive_day(day):
    return datetime(day.year, day.month, day.day) if day else NO_DATE


def item_stamp(item):
    moment = item.LastModificationTime
    return f"{moment.year:04d}{moment.month:02d}{moment.day:02d}T{moment.hour:02d}{moment.minute:02d}{moment.second:02d}"


def contact_values(item):
    values = empty_contact_fields()
    for name, attribute in CONTACT_PROPERTIES.items():
        values[name] = com_text(getattr(item, attribute, ""))
    for name, attribute in CONTACT_DATE_PROPERTIES.items():
        values[name] = com_date(getattr(item, attribute, None))
    return values


def apply_contact_values(item, changes):
    for name, value in changes.items():
        if name in CONTACT_PROPERTIES:
            setattr(item, CONTACT_PROPERTIES[name], (value or "").replace("\n", "\r\n"))
        elif name in CONTACT_DATE_PROPERTIES:
            setattr(item, CONTACT_DATE_PROPERTIES[name], naive_day(value))


def outlook_busy(busy_status):
    return BUSY_BUSY if busy_status == BUSY_WORKING_ELSEWHERE else busy_status


def appointment_fields(item):
    all_day = bool(item.AllDayEvent)
    if all_day:
        start = com_date(item.Start)
        end = com_date(item.End)
        if end is None or end <= start:
            end = start + timedelta(days=1)
    else:
        start = com_utc(getattr(item, "StartUTC", None) or item.Start)
        end = com_utc(getattr(item, "EndUTC", None) or item.End)
    return EventFields(
        summary=com_text(item.Subject), location=com_text(item.Location), description=com_text(item.Body), start=start,
        end=end, all_day=all_day, reminder_minutes=int(item.ReminderMinutesBeforeStart) if item.ReminderSet else None,
        busy=outlook_busy(item.BusyStatus), private=item.Sensitivity != SENSITIVITY_NORMAL,
        categories=com_text(item.Categories), recurring=bool(item.IsRecurring),
    )


def apply_appointment_fields(item, event, changes):
    if getattr(item, "IsRecurring", False):
        changes = without_recurring_times(changes)
    simple = {"summary": "Subject", "location": "Location", "description": "Body", "categories": "Categories"}
    for name, attribute in simple.items():
        if name in changes:
            setattr(item, attribute, (changes[name] or "").replace("\n", "\r\n"))
    if {"start", "end", "all_day"} & set(changes):
        item.AllDayEvent = event.all_day
        if event.all_day:
            item.Start = datetime.combine(event.start, time())
            item.End = datetime.combine(event.end, time())
        else:
            item.StartUTC = naive_utc(event.start)
            item.EndUTC = naive_utc(event.end)
    if "reminder_minutes" in changes:
        item.ReminderSet = event.reminder_minutes is not None
        if event.reminder_minutes is not None:
            item.ReminderMinutesBeforeStart = event.reminder_minutes
    if "busy" in changes:
        item.BusyStatus = event.busy
    if "private" in changes:
        item.Sensitivity = SENSITIVITY_PRIVATE if event.private else SENSITIVITY_NORMAL


def priority_from_importance(importance):
    return {IMPORTANCE_HIGH: 1, IMPORTANCE_NORMAL: 5, IMPORTANCE_LOW: 9}.get(importance, 0)


def importance_from_priority(priority):
    if not priority:
        return IMPORTANCE_NORMAL
    if priority <= 4:
        return IMPORTANCE_HIGH
    return IMPORTANCE_NORMAL if priority == 5 else IMPORTANCE_LOW


def task_fields(item):
    completed = bool(item.Complete)
    return TaskFields(
        summary=com_text(item.Subject), description=com_text(item.Body), start=com_date(item.StartDate),
        due=com_date(item.DueDate), completed=completed, completed_at=com_utc(item.DateCompleted) if completed else None,
        priority=priority_from_importance(item.Importance), private=item.Sensitivity != SENSITIVITY_NORMAL,
        categories=com_text(item.Categories),
    )


def apply_task_fields(item, task, changes):
    simple = {"summary": "Subject", "description": "Body", "categories": "Categories"}
    for name, attribute in simple.items():
        if name in changes:
            setattr(item, attribute, (changes[name] or "").replace("\n", "\r\n"))
    if "start" in changes:
        item.StartDate = naive_day(task.start)
    if "due" in changes:
        item.DueDate = naive_day(task.due)
    if "completed" in changes or "completed_at" in changes:
        item.Complete = task.completed
        if task.completed and task.completed_at:
            item.DateCompleted = naive_utc(task.completed_at)
    if "priority" in changes:
        item.Importance = importance_from_priority(task.priority)
    if "private" in changes:
        item.Sensitivity = SENSITIVITY_PRIVATE if task.private else SENSITIVITY_NORMAL


def item_uid(item):
    return getattr(item, "GlobalAppointmentID", "") or item.EntryID


def item_text(type_key, item):
    if type_key == CONTACTS.key:
        return contact_text(contact_values(item), item.EntryID)
    if type_key == CALENDAR.key:
        return event_text(appointment_fields(item), item_uid(item))
    return task_text(task_fields(item), item.EntryID)


def apply_text(type_key, item, text, new=False):
    if type_key == CONTACTS.key:
        before = empty_contact_fields() if new else normalized_contact_fields(contact_values(item))
        apply_contact_values(item, changed_values(before, contact_fields_from_text(text)))
    elif type_key == CALENDAR.key:
        event = event_fields_from_text(text)
        before = EventFields(start=None) if new else normalized_event(appointment_fields(item))
        apply_appointment_fields(item, event, changed_fields(before, event, ignored=("recurring",)))
    else:
        task = task_fields_from_text(text)
        before = TaskFields() if new else normalized_task(task_fields(item))
        apply_task_fields(item, task, changed_fields(before, task))


def item_in_range(type_key, item, earliest, latest):
    if type_key != CALENDAR.key:
        return True
    if item.IsRecurring:
        pattern = item.GetRecurrencePattern()
        return bool(pattern.NoEndDate) or com_date(pattern.PatternEndDate) is None or com_date(pattern.PatternEndDate) >= earliest
    start = com_date(item.Start)
    end = com_date(item.End) or start
    return start is not None and start <= latest and end >= earliest


def resolve_folder(namespace, default_folder, path):
    parts = [part for part in path.replace("/", "\\").split("\\") if part]
    if not parts:
        return default_folder
    folder = None
    for store_folder in namespace.Folders:
        if store_folder.Name == parts[0]:
            folder = store_folder
            parts = parts[1:]
            break
    if folder is None:
        folder = default_folder
    for part in parts:
        folder = next((child for child in folder.Folders if child.Name == part), None)
        if folder is None:
            raise LookupError(part)
    return folder
