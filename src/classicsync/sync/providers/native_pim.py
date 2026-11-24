from dataclasses import dataclass, fields
from datetime import date, datetime, timedelta, timezone

from ...rapi.cedb import PropertyValue
from ..pim.icalendar import (
    calendar_document, categories_of, parse_duration, parse_moment, reminder_of, single_component, text_of,
)
from ..pim.record import filetime_for_local_date, format_date, format_utc
from ..pim.text import escape_text, first_line, format_line
from ..pim.vcard import DATE_KEYS, TEXT_KEYS, contact_to_vcard, parse_vcard_fields
from ..pim.vcard3 import vcard_to_version4

BUSY_FREE = 0
BUSY_TENTATIVE = 1
BUSY_BUSY = 2
BUSY_OUT_OF_OFFICE = 3
BUSY_NAMES = {BUSY_FREE: "FREE", BUSY_TENTATIVE: "TENTATIVE", BUSY_BUSY: "BUSY", BUSY_OUT_OF_OFFICE: "OOF"}
EPOCH_STAMP = "20000101T000000Z"


def empty_contact_fields():
    values = {name: "" for name in TEXT_KEYS}
    values.update({name: None for name in DATE_KEYS})
    return values


def contact_text(contact_values, uid=None):
    properties = []
    for name, key in TEXT_KEYS.items():
        if contact_values.get(name):
            properties.append(PropertyValue(key[0], key[1], contact_values[name]))
    for name, key in DATE_KEYS.items():
        if contact_values.get(name):
            properties.append(PropertyValue(key[0], key[1], filetime_for_local_date(contact_values[name])))
    return contact_to_vcard(properties, uid)


def contact_fields_from_text(text):
    parsed = parse_vcard_fields(vcard_to_version4(text))
    values = empty_contact_fields()
    for name in TEXT_KEYS:
        values[name] = parsed.get(name) or ""
    for name in DATE_KEYS:
        values[name] = parsed.get(name)
    return values


def normalized_contact_fields(contact_values):
    return contact_fields_from_text(contact_text(contact_values))


def changed_values(old_values, new_values):
    return {name: value for name, value in new_values.items() if old_values.get(name) != value}


@dataclass
class EventFields:
    summary: str = ""
    location: str = ""
    description: str = ""
    start: object = None
    end: object = None
    all_day: bool = False
    reminder_minutes: object = None
    busy: int = BUSY_BUSY
    private: bool = False
    categories: str = ""
    recurring: bool = False


@dataclass
class TaskFields:
    summary: str = ""
    description: str = ""
    start: object = None
    due: object = None
    completed: bool = False
    completed_at: object = None
    priority: int = 0
    private: bool = False
    categories: str = ""


def as_dict(record):
    return {field.name: getattr(record, field.name) for field in fields(record)}


def changed_fields(old_record, new_record, ignored=()):
    old_values = as_dict(old_record)
    return {name: value for name, value in as_dict(new_record).items() if name not in ignored and old_values[name] != value}


def utc(moment):
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def categories_lines(categories):
    items = [item.strip() for item in (categories or "").split(",") if item.strip()]
    return [format_line("CATEGORIES", ",".join(escape_text(item) for item in items))] if items else []


def optional_text_line(name, value):
    return [format_line(name, escape_text(value))] if value else []


def event_text(event, uid):
    start = event.start
    lines = ["BEGIN:VEVENT", format_line("UID", uid)]
    if event.all_day:
        first_day = start if not isinstance(start, datetime) else start.date()
        last_day = event.end if isinstance(event.end, date) and not isinstance(event.end, datetime) else first_day + timedelta(days=1)
        lines.append(f"DTSTAMP:{format_date(first_day)}T000000Z")
        lines.append(f"DTSTART;VALUE=DATE:{format_date(first_day)}")
        lines.append(f"DTEND;VALUE=DATE:{format_date(last_day)}")
    else:
        lines.append(f"DTSTAMP:{format_utc(start) if start else EPOCH_STAMP}")
        lines.append(f"DTSTART:{format_utc(start)}")
        lines.append(f"DTEND:{format_utc(event.end or start)}")
    lines.append(format_line("SUMMARY", escape_text(event.summary or "")))
    lines.extend(optional_text_line("LOCATION", event.location))
    lines.extend(optional_text_line("DESCRIPTION", event.description))
    if event.private:
        lines.append("CLASS:PRIVATE")
    lines.extend(categories_lines(event.categories))
    lines.append("TRANSP:TRANSPARENT" if event.busy == BUSY_FREE else "TRANSP:OPAQUE")
    lines.append(f"X-MICROSOFT-CDO-BUSYSTATUS:{BUSY_NAMES.get(event.busy, 'BUSY')}")
    if event.recurring:
        lines.append("X-CLASSICSYNC-RECURRING:TRUE")
    if event.reminder_minutes is not None:
        lines.extend(["BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:Reminder", f"TRIGGER:-PT{event.reminder_minutes}M",
                      "END:VALARM"])
    lines.append("END:VEVENT")
    return calendar_document(lines)


def is_date(value):
    return isinstance(value, date) and not isinstance(value, datetime)


def event_fields_from_text(text):
    component = single_component(text, "VEVENT")
    start_line = first_line(component, "DTSTART")
    if start_line is None:
        raise ValueError("VEVENT has no DTSTART")
    start = parse_moment(start_line)
    end_line = first_line(component, "DTEND")
    duration_line = first_line(component, "DURATION")
    if end_line is not None:
        end = parse_moment(end_line)
    elif duration_line is not None:
        end = start + parse_duration(duration_line.value)
    else:
        end = start + timedelta(days=1) if is_date(start) else start
    all_day = is_date(start)
    if not all_day:
        start = utc(start)
        end = utc(end) if isinstance(end, datetime) else utc(datetime(end.year, end.month, end.day).astimezone())
    busy_name = (text_of(component, "X-MICROSOFT-CDO-BUSYSTATUS") or "").upper()
    busy_numbers = {name: number for number, name in BUSY_NAMES.items()}
    if busy_name in busy_numbers:
        busy = busy_numbers[busy_name]
    else:
        busy = BUSY_FREE if (text_of(component, "TRANSP") or "").upper() == "TRANSPARENT" else BUSY_BUSY
    recurring = first_line(component, "RRULE") is not None or first_line(component, "X-CLASSICSYNC-RECURRING") is not None
    return EventFields(
        summary=text_of(component, "SUMMARY") or "", location=text_of(component, "LOCATION") or "",
        description=text_of(component, "DESCRIPTION") or "", start=start, end=end, all_day=all_day,
        reminder_minutes=reminder_of(component), busy=busy,
        private=(text_of(component, "CLASS") or "PUBLIC").upper() != "PUBLIC",
        categories=categories_of(component) or "", recurring=recurring,
    )


def task_text(task, uid):
    lines = ["BEGIN:VTODO", format_line("UID", uid)]
    lines.append(f"DTSTAMP:{format_utc(task.completed_at) if task.completed and task.completed_at else EPOCH_STAMP}")
    lines.append(format_line("SUMMARY", escape_text(task.summary or "")))
    if task.start:
        lines.append(f"DTSTART;VALUE=DATE:{format_date(task.start)}")
    if task.due:
        lines.append(f"DUE;VALUE=DATE:{format_date(task.due)}")
    if task.completed:
        lines.append("STATUS:COMPLETED")
        if task.completed_at:
            lines.append(f"COMPLETED:{format_utc(task.completed_at)}")
    else:
        lines.append("STATUS:NEEDS-ACTION")
    if task.priority:
        lines.append(f"PRIORITY:{task.priority}")
    if task.private:
        lines.append("CLASS:PRIVATE")
    lines.extend(optional_text_line("DESCRIPTION", task.description))
    lines.extend(categories_lines(task.categories))
    lines.append("END:VTODO")
    return calendar_document(lines)


def local_day(moment):
    return moment.astimezone().date() if isinstance(moment, datetime) else moment


def task_fields_from_text(text):
    component = single_component(text, "VTODO")
    values = {}
    for name, key in (("DTSTART", "start"), ("DUE", "due")):
        line = first_line(component, name)
        values[key] = local_day(parse_moment(line)) if line else None
    completed_line = first_line(component, "COMPLETED")
    completed = (text_of(component, "STATUS") or "").upper() == "COMPLETED" or completed_line is not None
    completed_at = None
    if completed_line is not None:
        moment = parse_moment(completed_line)
        completed_at = utc(moment) if isinstance(moment, datetime) else utc(datetime(moment.year, moment.month, moment.day).astimezone())
    priority_line = first_line(component, "PRIORITY")
    priority = int(priority_line.value) if priority_line and priority_line.value.strip().isdigit() else 0
    return TaskFields(
        summary=text_of(component, "SUMMARY") or "", description=text_of(component, "DESCRIPTION") or "",
        start=values["start"], due=values["due"], completed=completed, completed_at=completed_at, priority=priority,
        private=(text_of(component, "CLASS") or "PUBLIC").upper() != "PUBLIC", categories=categories_of(component) or "",
    )


def normalized_event(event):
    return event_fields_from_text(event_text(event, "normalize"))


def normalized_task(task):
    return task_fields_from_text(task_text(task, "normalize"))


def without_recurring_times(changes):
    return {name: value for name, value in changes.items() if name not in ("start", "end", "all_day", "recurring")}

