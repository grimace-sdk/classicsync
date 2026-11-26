import copy
from datetime import datetime, time, timedelta, timezone

from ..rapi.cedb import CEVT_LPWSTR, PropertyValue
from ..sync.pim.icalendar import priority_from_importance
from ..sync.pim.properties import (
    APPOINTMENT_DURATION, APPOINTMENT_START, APPOINTMENT_TYPE, APPOINTMENT_TYPE_ALL_DAY, APPOINTMENT_TYPE_NORMAL, CATEGORIES,
    CONTACT_TEXT_FIELDS, NO_DATE, NOTES_TEXT, RECURRENCE_EXCEPTIONS, RECURRENCE_RULE, REMINDER_ENABLED, REMINDER_MINUTES,
    SENSITIVITY, SUBJECT, TASK_COMPLETED, TASK_DUE, TASK_IMPORTANCE, TASK_PRIORITY,
)
from ..sync.pim.record import (
    filetime_for_local_date, filetime_from_utc, format_date, local_date_from_filetime, parse_date, property_map, text_value,
    utc_from_filetime,
)
from .records import (
    ADDRESS_CITY, ADDRESS_COMPANY, ADDRESS_COUNTRY, ADDRESS_FIRST_NAME, ADDRESS_LAST_NAME, ADDRESS_NOTE, ADDRESS_PHONE_COUNT,
    ADDRESS_PHONE_FIRST, ADDRESS_STATE, ADDRESS_STREET, ADDRESS_TITLE, ADDRESS_ZIP, ALARM_DAYS, ALARM_HOURS, PHONE_EMAIL,
    PHONE_FAX, PHONE_HOME, PHONE_MAIN, PHONE_MOBILE, PHONE_OTHER, PHONE_PAGER, PHONE_WORK, REPEAT_DAILY, REPEAT_MONTHLY_BY_DATE,
    REPEAT_MONTHLY_BY_DAY, REPEAT_WEEKLY, REPEAT_YEARLY, Address, Appointment, Repeat, ToDo,
)

MINUTES_PER_DAY = 1440
PRIVATE = 1
DAY_CODES = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"]
LAST_WEEK = 4
MAX_ALARM_ADVANCE = 99
COUNT_SEARCH_DAYS = 366 * 50
DEFAULT_PRIORITY = 1
LOWEST_PRIORITY = 5

ADDRESS_TEXT = {
    ADDRESS_LAST_NAME: "surname",
    ADDRESS_FIRST_NAME: "given_name",
    ADDRESS_COMPANY: "company",
    ADDRESS_TITLE: "title",
    ADDRESS_NOTE: "notes",
}
ADDRESS_PARTS = {ADDRESS_STREET: "street", ADDRESS_CITY: "city", ADDRESS_STATE: "state", ADDRESS_ZIP: "postal_code",
                 ADDRESS_COUNTRY: "country"}
ADDRESS_PREFIXES = ("other", "home", "work")
PHONE_TARGETS = {
    PHONE_WORK: ("work_phone", "work_phone2"),
    PHONE_HOME: ("home_phone", "home_phone2"),
    PHONE_FAX: ("work_fax", "home_fax"),
    PHONE_OTHER: ("work_phone2", "home_phone2", "car_phone"),
    PHONE_EMAIL: ("email1", "email2", "email3"),
    PHONE_MAIN: ("work_phone", "work_phone2"),
    PHONE_PAGER: ("pager",),
    PHONE_MOBILE: ("mobile_phone", "car_phone"),
}
PHONE_OVERFLOW = ("work_phone2", "home_phone2", "car_phone", "assistant_phone", "home_phone", "work_phone", "mobile_phone",
                  "pager", "home_fax", "work_fax")
PHONE_SOURCES = [
    ("work_phone", PHONE_WORK), ("home_phone", PHONE_HOME), ("mobile_phone", PHONE_MOBILE), ("email1", PHONE_EMAIL),
    ("work_fax", PHONE_FAX), ("pager", PHONE_PAGER), ("work_phone2", PHONE_WORK), ("home_phone2", PHONE_HOME),
    ("home_fax", PHONE_FAX), ("car_phone", PHONE_OTHER), ("assistant_phone", PHONE_OTHER), ("email2", PHONE_EMAIL),
    ("email3", PHONE_EMAIL),
]


def text_property(name, value):
    return PropertyValue(CONTACT_TEXT_FIELDS[name], CEVT_LPWSTR, value)


def common_properties(category, secret):
    properties = [PropertyValue(SENSITIVITY[0], SENSITIVITY[1], PRIVATE if secret else 0)]
    if category:
        properties.append(PropertyValue(CATEGORIES[0], CATEGORIES[1], category))
    return properties


def address_to_properties(address, category="", secret=False):
    fields = {}
    for index, name in ADDRESS_TEXT.items():
        if address.fields[index]:
            fields[name] = address.fields[index]
    for index, part in ADDRESS_PARTS.items():
        if address.fields[index]:
            fields[f"other_{part}"] = address.fields[index]
    for label, value in address.phones():
        targets = PHONE_TARGETS.get(label, ())
        overflow = () if label == PHONE_EMAIL else PHONE_OVERFLOW
        target = next((name for name in (*targets, *overflow) if name not in fields), None)
        if target:
            fields[target] = value
    return [text_property(name, value) for name, value in fields.items()] + common_properties(category, secret)


def contact_text(values, name):
    return text_value(values, (CONTACT_TEXT_FIELDS[name], CEVT_LPWSTR))


def properties_to_address(properties, base=None):
    values = property_map(properties)
    address = copy.deepcopy(base) if base else Address()
    for index, name in ADDRESS_TEXT.items():
        address.fields[index] = contact_text(values, name) or None
    prefix = next((candidate for candidate in ADDRESS_PREFIXES
                   if any(contact_text(values, f"{candidate}_{part}") for part in ADDRESS_PARTS.values())), "other")
    for index, part in ADDRESS_PARTS.items():
        address.fields[index] = contact_text(values, f"{prefix}_{part}") or None
    wanted = [(label, contact_text(values, name)) for name, label in PHONE_SOURCES if contact_text(values, name)]
    slots = [None] * ADDRESS_PHONE_COUNT
    remaining = list(wanted)
    for slot in range(ADDRESS_PHONE_COUNT):
        existing = (address.phone_labels[slot], address.fields[ADDRESS_PHONE_FIRST + slot])
        match = next((entry for entry in remaining if existing[1] and entry[1] == existing[1]), None)
        if match:
            slots[slot] = existing
            remaining.remove(match)
    for slot in range(ADDRESS_PHONE_COUNT):
        if slots[slot] is None and remaining:
            slots[slot] = remaining.pop(0)
    for slot, entry in enumerate(slots):
        if entry:
            address.phone_labels[slot], address.fields[ADDRESS_PHONE_FIRST + slot] = entry
        else:
            address.fields[ADDRESS_PHONE_FIRST + slot] = None
    if not address.fields[ADDRESS_PHONE_FIRST + address.display_phone]:
        address.display_phone = next((slot for slot in range(ADDRESS_PHONE_COUNT) if slots[slot]), 0)
    return address


def alarm_minutes(alarm):
    advance, unit = alarm
    return advance * {ALARM_HOURS: 60, ALARM_DAYS: MINUTES_PER_DAY}.get(unit, 1)


def alarm_from_minutes(minutes):
    if minutes % MINUTES_PER_DAY == 0 and minutes // MINUTES_PER_DAY <= MAX_ALARM_ADVANCE and minutes:
        return (minutes // MINUTES_PER_DAY, ALARM_DAYS)
    if minutes % 60 == 0 and minutes // 60 <= MAX_ALARM_ADVANCE and minutes:
        return (minutes // 60, ALARM_HOURS)
    return (min(minutes, MAX_ALARM_ADVANCE), 0)


def local_moment(day, moment):
    return datetime.combine(day, moment or time()).astimezone()


def until_text(end, all_day):
    if all_day:
        return format_date(end)
    return local_moment(end, time(23, 59, 59)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def repeat_to_rule(repeat, start_day, all_day):
    parts = []
    if repeat.kind == REPEAT_DAILY:
        parts.append("FREQ=DAILY")
    elif repeat.kind == REPEAT_WEEKLY:
        days = [code for bit, code in enumerate(DAY_CODES) if repeat.repeat_on & 1 << bit]
        parts.append("FREQ=WEEKLY")
        if days:
            parts.append("BYDAY=" + ",".join(days))
        parts.append("WKST=" + ("MO" if repeat.start_of_week == 1 else "SU"))
    elif repeat.kind == REPEAT_MONTHLY_BY_DAY:
        week, weekday = divmod(repeat.repeat_on, 7)
        ordinal = -1 if week >= LAST_WEEK else week + 1
        parts.append(f"FREQ=MONTHLY;BYDAY={ordinal}{DAY_CODES[weekday]}")
    elif repeat.kind == REPEAT_MONTHLY_BY_DATE:
        parts.append(f"FREQ=MONTHLY;BYMONTHDAY={start_day.day}")
    elif repeat.kind == REPEAT_YEARLY:
        parts.append("FREQ=YEARLY")
    else:
        return ""
    if repeat.frequency > 1:
        parts.append(f"INTERVAL={repeat.frequency}")
    if repeat.end:
        parts.append("UNTIL=" + until_text(repeat.end, all_day))
    return ";".join(parts)


def rule_parts(rule):
    return {key.upper(): value for key, _, value in (part.partition("=") for part in rule.split(";")) if key}


def parse_until(value):
    value = value.strip()
    if len(value) == 8:
        return parse_date(value)
    moment = datetime.strptime(value.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone().date()


def occurs(repeat, start_day, day):
    if day < start_day:
        return False
    if repeat.kind == REPEAT_DAILY:
        return (day - start_day).days % repeat.frequency == 0
    if repeat.kind == REPEAT_WEEKLY:
        week_start = (start_day.weekday() + 1 - repeat.start_of_week) % 7
        weeks = ((day - start_day).days + week_start) // 7
        return weeks % repeat.frequency == 0 and bool(repeat.repeat_on & 1 << (day.weekday() + 1) % 7)
    months = (day.year - start_day.year) * 12 + day.month - start_day.month
    if repeat.kind == REPEAT_MONTHLY_BY_DATE:
        return day.day == start_day.day and months % repeat.frequency == 0
    if repeat.kind == REPEAT_MONTHLY_BY_DAY:
        week, weekday = divmod(repeat.repeat_on, 7)
        if months % repeat.frequency or (day.weekday() + 1) % 7 != weekday:
            return False
        if week >= LAST_WEEK:
            return (day + timedelta(days=7)).month != day.month
        return (day.day - 1) // 7 == week
    if repeat.kind == REPEAT_YEARLY:
        return (day.month, day.day) == (start_day.month, start_day.day) and (day.year - start_day.year) % repeat.frequency == 0
    return False


def end_after_count(repeat, start_day, count):
    found = 0
    for offset in range(COUNT_SEARCH_DAYS):
        day = start_day + timedelta(days=offset)
        if occurs(repeat, start_day, day):
            found += 1
            if found == count:
                return day
    return None


def rule_to_repeat(rule, start_day):
    parts = rule_parts(rule)
    frequency = max(1, int(parts.get("INTERVAL", "1") or 1))
    by_day = [item.strip().upper() for item in parts.get("BYDAY", "").split(",") if item.strip()]
    kind = parts.get("FREQ", "").upper()
    start_dow = (start_day.weekday() + 1) % 7
    if kind == "DAILY":
        repeat = Repeat(REPEAT_DAILY, frequency=frequency)
    elif kind == "WEEKLY":
        mask = 0
        for item in by_day:
            if item[-2:] in DAY_CODES:
                mask |= 1 << DAY_CODES.index(item[-2:])
        repeat = Repeat(REPEAT_WEEKLY, frequency=frequency, repeat_on=mask or 1 << start_dow,
                        start_of_week=1 if parts.get("WKST", "SU").upper() == "MO" else 0)
    elif kind == "MONTHLY" and by_day and by_day[0][-2:] in DAY_CODES:
        ordinal = by_day[0][:-2] or str((start_day.day - 1) // 7 + 1)
        week = LAST_WEEK if ordinal.startswith("-") else min(int(ordinal.lstrip("+")) - 1, LAST_WEEK - 1)
        repeat = Repeat(REPEAT_MONTHLY_BY_DAY, frequency=frequency, repeat_on=week * 7 + DAY_CODES.index(by_day[0][-2:]))
    elif kind == "MONTHLY":
        repeat = Repeat(REPEAT_MONTHLY_BY_DATE, frequency=frequency)
    elif kind == "YEARLY":
        repeat = Repeat(REPEAT_YEARLY, frequency=frequency)
    else:
        return None
    if parts.get("UNTIL"):
        repeat.end = parse_until(parts["UNTIL"])
    elif parts.get("COUNT", "").isdigit():
        repeat.end = end_after_count(repeat, start_day, int(parts["COUNT"]))
    return repeat


def appointment_to_properties(appointment, category="", secret=False):
    properties = []
    if appointment.untimed:
        properties += [PropertyValue(*APPOINTMENT_START, filetime_for_local_date(appointment.day)),
                       PropertyValue(*APPOINTMENT_TYPE, APPOINTMENT_TYPE_ALL_DAY),
                       PropertyValue(*APPOINTMENT_DURATION, MINUTES_PER_DAY)]
    else:
        start = local_moment(appointment.day, appointment.start)
        end = local_moment(appointment.day, appointment.end or appointment.start)
        properties += [PropertyValue(*APPOINTMENT_START, filetime_from_utc(start)),
                       PropertyValue(*APPOINTMENT_TYPE, APPOINTMENT_TYPE_NORMAL),
                       PropertyValue(*APPOINTMENT_DURATION, max(0, int((end - start).total_seconds() // 60)))]
    properties.append(PropertyValue(*SUBJECT, appointment.description))
    if appointment.note:
        properties.append(PropertyValue(*NOTES_TEXT, appointment.note))
    properties.append(PropertyValue(*REMINDER_ENABLED, 1 if appointment.alarm else 0))
    if appointment.alarm:
        properties.append(PropertyValue(*REMINDER_MINUTES, alarm_minutes(appointment.alarm)))
    rule = repeat_to_rule(appointment.repeat, appointment.day, appointment.untimed) if appointment.repeat else ""
    properties.append(PropertyValue(*RECURRENCE_RULE, rule))
    exceptions = ",".join(format_date(day) for day in appointment.exceptions if day) if rule else ""
    properties.append(PropertyValue(*RECURRENCE_EXCEPTIONS, exceptions))
    return properties + common_properties(category, secret)


def properties_to_appointment(properties, base=None):
    values = property_map(properties)
    appointment = copy.deepcopy(base) if base else Appointment(None)
    start_filetime = values.get(APPOINTMENT_START)
    if not start_filetime:
        raise ValueError("appointment has no start time")
    if values.get(APPOINTMENT_TYPE) == APPOINTMENT_TYPE_ALL_DAY:
        appointment.day = local_date_from_filetime(start_filetime)
        appointment.start = appointment.end = None
    else:
        start = utc_from_filetime(start_filetime).astimezone()
        end = start + timedelta(minutes=values.get(APPOINTMENT_DURATION) or 0)
        appointment.day = start.date()
        appointment.start = start.time().replace(second=0, microsecond=0, tzinfo=None)
        appointment.end = end.time().replace(second=0, microsecond=0, tzinfo=None) if end.date() == start.date() else time(23, 59)
    appointment.description = text_value(values, SUBJECT)
    appointment.note = text_value(values, NOTES_TEXT)
    appointment.alarm = alarm_from_minutes(values.get(REMINDER_MINUTES) or 0) if values.get(REMINDER_ENABLED) else None
    rule = text_value(values, RECURRENCE_RULE)
    appointment.repeat = rule_to_repeat(rule, appointment.day) if rule else None
    exceptions = text_value(values, RECURRENCE_EXCEPTIONS)
    appointment.exceptions = [parse_date(item) for item in exceptions.split(",") if item.strip()] if appointment.repeat else []
    return appointment


def todo_to_properties(todo, category="", secret=False):
    properties = [PropertyValue(*SUBJECT, todo.description),
                  PropertyValue(*TASK_DUE, filetime_for_local_date(todo.due) if todo.due else NO_DATE),
                  PropertyValue(*TASK_COMPLETED, 1 if todo.completed else 0),
                  PropertyValue(*TASK_PRIORITY, todo.priority or DEFAULT_PRIORITY)]
    if todo.note:
        properties.append(PropertyValue(*NOTES_TEXT, todo.note))
    return properties + common_properties(category, secret)


def properties_to_todo(properties, base=None):
    values = property_map(properties)
    todo = copy.deepcopy(base) if base else ToDo()
    todo.description = text_value(values, SUBJECT)
    todo.note = text_value(values, NOTES_TEXT)
    due = values.get(TASK_DUE)
    todo.due = local_date_from_filetime(due) if due and due != NO_DATE else None
    todo.completed = bool(values.get(TASK_COMPLETED))
    if values.get(TASK_PRIORITY):
        todo.priority = min(max(values[TASK_PRIORITY], 1), LOWEST_PRIORITY)
    elif values.get(TASK_IMPORTANCE) is not None:
        priority = priority_from_importance(values[TASK_IMPORTANCE])
        todo.priority = min(max((priority + 1) // 2, 1), LOWEST_PRIORITY) if priority else DEFAULT_PRIORITY
    return todo


def category_and_secret(properties):
    values = property_map(properties)
    names = [item.strip() for item in text_value(values, CATEGORIES).split(",") if item.strip()]
    return (names[0] if names else ""), bool(values.get(SENSITIVITY))

