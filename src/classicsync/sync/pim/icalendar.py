import re
from datetime import date, datetime, timedelta, timezone

from ...rapi.cedb import PropertyValue
from .properties import (
    APPOINTMENT_BUSY_STATUS, APPOINTMENT_DAY, APPOINTMENT_DURATION, APPOINTMENT_LOCATION, APPOINTMENT_RECURRENCE,
    APPOINTMENT_START, APPOINTMENT_TYPE, APPOINTMENT_TYPE_ALL_DAY, APPOINTMENT_TYPE_NORMAL, BUSY_STATUS_NAMES, CATEGORIES,
    NO_DATE, NOTES_BLOB, NOTES_INK, NOTES_TEXT, REMINDER_ENABLED, REMINDER_MINUTES, REMINDER_OPTIONS, REMINDER_SOUND,
    SENSITIVITY, SUBJECT, TASK_COMPLETED, TASK_COMPLETED_DATE, TASK_DUE, TASK_IMPORTANCE, TASK_PROJECT, TASK_START,
    TASK_UNKNOWN_0003, TASK_UNKNOWN_4126, UNIQUE_ID, UNKNOWN_0002,
)
from .record import (
    filetime_for_local_date, filetime_from_utc, format_date, format_utc, local_date_from_filetime, merge_properties,
    notes_for_write, notes_value, parse_date, property_map, text_value, utc_from_filetime,
)
from .text import all_lines, escape_text, first_line, format_line, parse_components, split_escaped, unescape_text

PRODID = "-//classicsync//classicsync//EN"
MINUTES_PER_DAY = 1440
DURATION_PATTERN = re.compile(r"([+-]?)P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")

APPOINTMENT_OWNED = {
    APPOINTMENT_START, APPOINTMENT_DAY, APPOINTMENT_DURATION, APPOINTMENT_TYPE, SUBJECT, APPOINTMENT_LOCATION,
    NOTES_TEXT, SENSITIVITY, APPOINTMENT_BUSY_STATUS, CATEGORIES, REMINDER_ENABLED, REMINDER_MINUTES,
}
TASK_OWNED = {SUBJECT, TASK_START, TASK_DUE, TASK_COMPLETED, TASK_COMPLETED_DATE, NOTES_TEXT, CATEGORIES, SENSITIVITY, TASK_IMPORTANCE}


def template(entries):
    return [PropertyValue(key[0], key[1], value) for key, value in entries]


def appointment_template(os_major):
    if os_major <= 1:
        return template([
            (APPOINTMENT_RECURRENCE, 0), (APPOINTMENT_TYPE, APPOINTMENT_TYPE_NORMAL), (REMINDER_MINUTES, 15),
            (REMINDER_ENABLED, 0), (REMINDER_OPTIONS, 13), (UNKNOWN_0002, 0), (SUBJECT, ""), (APPOINTMENT_LOCATION, ""),
            (NOTES_TEXT, ""), (REMINDER_SOUND, "Alarm1.wav"),
        ])
    return template([
        (APPOINTMENT_RECURRENCE, 0), (APPOINTMENT_TYPE, APPOINTMENT_TYPE_NORMAL), (REMINDER_MINUTES, 15),
        (REMINDER_ENABLED, 0), (REMINDER_OPTIONS, 13), (UNKNOWN_0002, 0), (APPOINTMENT_BUSY_STATUS, 2), (SENSITIVITY, 0),
        (SUBJECT, ""), (APPOINTMENT_LOCATION, ""), (NOTES_BLOB, b""), (REMINDER_SOUND, "Alarm1.wav"), (NOTES_INK, b""),
    ])


def task_template(os_major):
    entries = [
        (TASK_START, NO_DATE), (TASK_PROJECT, ""), (TASK_UNKNOWN_4126, 0), (SUBJECT, ""), (NOTES_TEXT, ""),
        (TASK_IMPORTANCE, 0x2033 if os_major <= 1 else 2), (TASK_DUE, NO_DATE), (TASK_COMPLETED, 0),
        (REMINDER_SOUND, "Alarm1.wav"), (REMINDER_MINUTES, 0), (TASK_UNKNOWN_0003, 0), (REMINDER_ENABLED, 0),
        (REMINDER_OPTIONS, 13), (UNKNOWN_0002, 0),
    ]
    if os_major > 1:
        entries.append((SENSITIVITY, 0))
    return template(entries)


def calendar_document(component_lines):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", *component_lines, "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


def unique_id(values, fallback):
    blob = values.get(UNIQUE_ID)
    if blob:
        return blob.hex().upper()
    return fallback or "classicsync"


def categories_lines(values):
    categories = [item.strip() for item in text_value(values, CATEGORIES).split(",") if item.strip()]
    return [format_line("CATEGORIES", ",".join(escape_text(item) for item in categories))] if categories else []


def alarm_lines(values):
    if not values.get(REMINDER_ENABLED):
        return []
    minutes = values.get(REMINDER_MINUTES) or 0
    return ["BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:Reminder", f"TRIGGER:-PT{minutes}M", "END:VALARM"]


def common_lines(values):
    lines = []
    if values.get(SENSITIVITY):
        lines.append("CLASS:PRIVATE")
    if notes_value(values):
        lines.append(format_line("DESCRIPTION", escape_text(notes_value(values))))
    return lines + categories_lines(values)


def appointment_to_ical(properties, uid=None):
    values = property_map(properties)
    start_filetime = values.get(APPOINTMENT_START)
    if not start_filetime:
        raise ValueError("appointment has no start time")
    start = utc_from_filetime(start_filetime)
    minutes = values.get(APPOINTMENT_DURATION) or 0
    lines = ["BEGIN:VEVENT", format_line("UID", unique_id(values, uid)), f"DTSTAMP:{format_utc(start)}"]
    if values.get(APPOINTMENT_TYPE) == APPOINTMENT_TYPE_ALL_DAY:
        first_day = local_date_from_filetime(start_filetime)
        days = max(1, round(minutes / MINUTES_PER_DAY))
        lines.append(f"DTSTART;VALUE=DATE:{format_date(first_day)}")
        lines.append(f"DTEND;VALUE=DATE:{format_date(first_day + timedelta(days=days))}")
    else:
        lines.append(f"DTSTART:{format_utc(start)}")
        lines.append(f"DTEND:{format_utc(start + timedelta(minutes=minutes))}")
    lines.append(format_line("SUMMARY", escape_text(text_value(values, SUBJECT))))
    if text_value(values, APPOINTMENT_LOCATION):
        lines.append(format_line("LOCATION", escape_text(text_value(values, APPOINTMENT_LOCATION))))
    lines.extend(common_lines(values))
    busy = values.get(APPOINTMENT_BUSY_STATUS)
    if busy is not None:
        lines.append("TRANSP:TRANSPARENT" if busy == 0 else "TRANSP:OPAQUE")
        lines.append(f"X-MICROSOFT-CDO-BUSYSTATUS:{BUSY_STATUS_NAMES.get(busy, 'BUSY')}")
    if values.get(APPOINTMENT_RECURRENCE):
        lines.append("X-CLASSICSYNC-RECURRING:TRUE")
    lines.extend(alarm_lines(values))
    lines.append("END:VEVENT")
    return calendar_document(lines)


def task_to_ical(properties, uid=None):
    values = property_map(properties)
    lines = ["BEGIN:VTODO", format_line("UID", unique_id(values, uid))]
    stamp = values.get(TASK_COMPLETED_DATE) if values.get(TASK_COMPLETED) else None
    lines.append(f"DTSTAMP:{format_utc(utc_from_filetime(stamp)) if stamp else '20000101T000000Z'}")
    lines.append(format_line("SUMMARY", escape_text(text_value(values, SUBJECT))))
    for key, name in ((TASK_START, "DTSTART"), (TASK_DUE, "DUE")):
        if values.get(key) and values[key] != NO_DATE:
            lines.append(f"{name};VALUE=DATE:{format_date(local_date_from_filetime(values[key]))}")
    if values.get(TASK_COMPLETED):
        lines.append("STATUS:COMPLETED")
        if values.get(TASK_COMPLETED_DATE):
            lines.append(f"COMPLETED:{format_utc(utc_from_filetime(values[TASK_COMPLETED_DATE]))}")
    else:
        lines.append("STATUS:NEEDS-ACTION")
    priority = priority_from_importance(values.get(TASK_IMPORTANCE))
    if priority:
        lines.append(f"PRIORITY:{priority}")
    lines.extend(common_lines(values))
    lines.append("END:VTODO")
    return calendar_document(lines)


def priority_from_importance(importance):
    if importance is None:
        return None
    if importance >> 8 == 0x20 and chr(importance & 0xFF).isdigit():
        return int(chr(importance & 0xFF)) or None
    return {0: 1, 1: 1, 2: 5, 3: 9}.get(importance)


def importance_from_priority(priority, previous, os_major):
    character_style = previous is not None and previous >> 8 == 0x20 or previous is None and os_major <= 1
    if character_style:
        return 0x2000 | ord(str(min(max(priority, 1), 9)))
    if priority <= 4:
        return 1
    return 2 if priority == 5 else 3


def parse_duration(text):
    match = DURATION_PATTERN.match(text.strip().upper())
    if not match:
        raise ValueError(f"bad duration {text!r}")
    sign, weeks, days, hours, minutes, seconds = match.groups()
    length = timedelta(weeks=int(weeks or 0), days=int(days or 0), hours=int(hours or 0),
                       minutes=int(minutes or 0), seconds=int(seconds or 0))
    return -length if sign == "-" else length


def parse_moment(line):
    value = line.value.strip()
    if "DATE" in [item.upper() for item in line.parameter("VALUE")] or len(value) == 8:
        return parse_date(value)
    moment = datetime.strptime(value.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        return moment.replace(tzinfo=timezone.utc)
    zone_name = (line.parameter("TZID") or [None])[0]
    if zone_name:
        try:
            from zoneinfo import ZoneInfo
            return moment.replace(tzinfo=ZoneInfo(zone_name))
        except Exception:
            pass
    return moment.astimezone()


def single_component(text, name):
    for calendar in parse_components(text):
        for component in [calendar, *calendar["children"]]:
            if component["name"] == name:
                return component
    raise ValueError(f"no {name} in file")


def text_of(component, name):
    line = first_line(component, name)
    return unescape_text(line.value) if line else None


def categories_of(component):
    items = []
    for line in all_lines(component, "CATEGORIES"):
        items.extend(unescape_text(item).strip() for item in split_escaped(line.value, ","))
    return ", ".join(item for item in items if item) or None


def sensitivity_of(component, values_before):
    classification = (text_of(component, "CLASS") or "PUBLIC").upper()
    if classification == "PUBLIC":
        return 0
    return values_before.get(SENSITIVITY) or 1


def reminder_of(component):
    for alarm in component["children"]:
        if alarm["name"] != "VALARM":
            continue
        trigger = first_line(alarm, "TRIGGER")
        if trigger is None:
            continue
        try:
            offset = parse_duration(trigger.value)
        except ValueError:
            continue
        return max(0, int(-offset.total_seconds() // 60))
    return None


def has_key(base, key):
    return any((prop.identifier, prop.value_type) == key for prop in base)


def ical_to_appointment(text, base_properties=(), os_major=2):
    event = single_component(text, "VEVENT")
    base = list(base_properties) or appointment_template(os_major)
    before = property_map(base)
    start_line = first_line(event, "DTSTART")
    if start_line is None:
        raise ValueError("VEVENT has no DTSTART")
    start = parse_moment(start_line)
    end_line = first_line(event, "DTEND")
    duration_line = first_line(event, "DURATION")
    values = {}
    if isinstance(start, date) and not isinstance(start, datetime):
        end = parse_moment(end_line) if end_line else start + (parse_duration(duration_line.value) if duration_line else timedelta(days=1))
        days = max(1, (end - start).days)
        start_filetime = filetime_for_local_date(start)
        values[APPOINTMENT_TYPE] = APPOINTMENT_TYPE_ALL_DAY
        values[APPOINTMENT_DURATION] = days * MINUTES_PER_DAY
        day_filetime = start_filetime
    else:
        if end_line:
            end = parse_moment(end_line)
            if not isinstance(end, datetime):
                end = datetime(end.year, end.month, end.day).astimezone()
        else:
            end = start + (parse_duration(duration_line.value) if duration_line else timedelta(0))
        start_filetime = filetime_from_utc(start)
        values[APPOINTMENT_TYPE] = APPOINTMENT_TYPE_NORMAL if before.get(APPOINTMENT_TYPE) in (None, APPOINTMENT_TYPE_ALL_DAY) else before[APPOINTMENT_TYPE]
        values[APPOINTMENT_DURATION] = max(0, int((end - start).total_seconds() // 60))
        day_filetime = filetime_for_local_date(start.astimezone().date())
    values[APPOINTMENT_START] = start_filetime
    if has_key(base, APPOINTMENT_DAY) or os_major <= 1:
        values[APPOINTMENT_DAY] = day_filetime
    values[SUBJECT] = text_of(event, "SUMMARY") or ""
    values[APPOINTMENT_LOCATION] = text_of(event, "LOCATION")
    values[NOTES_TEXT] = notes_for_write(before, text_of(event, "DESCRIPTION"))
    values[CATEGORIES] = categories_of(event)
    if has_key(base, SENSITIVITY) or os_major > 1:
        values[SENSITIVITY] = sensitivity_of(event, before)
    if has_key(base, APPOINTMENT_BUSY_STATUS) or os_major > 1:
        busy = (text_of(event, "X-MICROSOFT-CDO-BUSYSTATUS") or "").upper()
        statuses = {name: number for number, name in BUSY_STATUS_NAMES.items()}
        if busy in statuses:
            values[APPOINTMENT_BUSY_STATUS] = statuses[busy]
        else:
            transparent = (text_of(event, "TRANSP") or "").upper() == "TRANSPARENT"
            values[APPOINTMENT_BUSY_STATUS] = 0 if transparent else (before.get(APPOINTMENT_BUSY_STATUS) or 2)
    reminder = reminder_of(event)
    values[REMINDER_ENABLED] = 1 if reminder is not None else 0
    values[REMINDER_MINUTES] = reminder if reminder is not None else before.get(REMINDER_MINUTES, 15)
    return merge_properties(base, APPOINTMENT_OWNED, values)


def ical_to_task(text, base_properties=(), os_major=2):
    todo = single_component(text, "VTODO")
    base = list(base_properties) or task_template(os_major)
    before = property_map(base)
    values = {SUBJECT: text_of(todo, "SUMMARY") or ""}
    for key, name in ((TASK_START, "DTSTART"), (TASK_DUE, "DUE")):
        line = first_line(todo, name)
        if line:
            moment = parse_moment(line)
            day = moment.astimezone().date() if isinstance(moment, datetime) else moment
            values[key] = filetime_for_local_date(day)
        else:
            values[key] = NO_DATE
    completed = (text_of(todo, "STATUS") or "").upper() == "COMPLETED" or first_line(todo, "COMPLETED") is not None
    values[TASK_COMPLETED] = 1 if completed else 0
    if completed:
        completed_line = first_line(todo, "COMPLETED")
        if completed_line:
            moment = parse_moment(completed_line)
            values[TASK_COMPLETED_DATE] = filetime_from_utc(moment) if isinstance(moment, datetime) else filetime_for_local_date(moment)
        else:
            values[TASK_COMPLETED_DATE] = before.get(TASK_COMPLETED_DATE) or filetime_for_local_date(datetime.now().date())
    priority_line = first_line(todo, "PRIORITY")
    priority = int(priority_line.value) if priority_line and priority_line.value.strip().isdigit() else 0
    if priority:
        values[TASK_IMPORTANCE] = importance_from_priority(priority, before.get(TASK_IMPORTANCE), os_major)
    else:
        values[TASK_IMPORTANCE] = before.get(TASK_IMPORTANCE)
    values[NOTES_TEXT] = notes_for_write(before, text_of(todo, "DESCRIPTION"))
    values[CATEGORIES] = categories_of(todo)
    if has_key(base, SENSITIVITY) or os_major > 1:
        values[SENSITIVITY] = sensitivity_of(todo, before)
    return merge_properties(base, TASK_OWNED, values)
