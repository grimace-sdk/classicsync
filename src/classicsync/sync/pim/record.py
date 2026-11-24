from datetime import date, datetime, timezone

from ...rapi.cedb import CEVT_BLOB, CEVT_LPWSTR, PropertyValue
from ...rapi.structures import datetime_to_filetime, filetime_to_datetime


def property_map(properties):
    return {(prop.identifier, prop.value_type): prop.value for prop in properties if not prop.missing}


def text_value(values, key):
    value = values.get(key)
    return value if isinstance(value, str) else ""


def merge_properties(base, owned, values):
    result = []
    seen = set()
    for prop in base:
        key = (prop.identifier, prop.value_type)
        if key not in owned:
            result.append(prop)
            continue
        seen.add(key)
        value = values.get(key)
        if value is None:
            if prop.value_type == CEVT_LPWSTR:
                result.append(PropertyValue(prop.identifier, prop.value_type, ""))
            elif prop.value_type == CEVT_BLOB:
                result.append(prop)
            continue
        result.append(PropertyValue(prop.identifier, prop.value_type, value))
    for key, value in values.items():
        if key not in seen and value is not None:
            result.append(PropertyValue(key[0], key[1], value))
    return result


def utc_from_filetime(filetime):
    return filetime_to_datetime(filetime)


def filetime_from_utc(moment):
    return datetime_to_filetime(moment.astimezone(timezone.utc))


def local_date_from_filetime(filetime):
    return filetime_to_datetime(filetime).astimezone().date()


def filetime_for_local_date(day):
    return datetime_to_filetime(datetime(day.year, day.month, day.day).astimezone(timezone.utc))


def format_utc(moment):
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def format_date(day):
    return day.strftime("%Y%m%d")


def parse_date(text):
    text = text.strip().replace("-", "")
    return date(int(text[0:4]), int(text[4:6]), int(text[6:8]))
