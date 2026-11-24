import base64
import hashlib
import json

from ..rapi import cedb
from ..rapi.structures import filetime_to_datetime

TYPE_NAMES = {
    cedb.CEVT_I2: "I2",
    cedb.CEVT_UI2: "UI2",
    cedb.CEVT_I4: "I4",
    cedb.CEVT_UI4: "UI4",
    cedb.CEVT_R8: "R8",
    cedb.CEVT_BOOL: "BOOL",
    cedb.CEVT_LPWSTR: "LPWSTR",
    cedb.CEVT_FILETIME: "FILETIME",
    cedb.CEVT_BLOB: "BLOB",
}
TYPES_BY_NAME = {name: value for value, name in TYPE_NAMES.items()}


def property_to_json(prop):
    entry = {"id": f"0x{prop.identifier:04x}", "type": TYPE_NAMES.get(prop.value_type, prop.value_type)}
    if prop.flags:
        entry["flags"] = prop.flags
    if prop.value is None:
        entry["value"] = None
    elif prop.value_type == cedb.CEVT_BLOB:
        entry["value"] = base64.b64encode(prop.value).decode("ascii")
    elif prop.value_type == cedb.CEVT_FILETIME:
        entry["value"] = prop.value
        moment = filetime_to_datetime(prop.value)
        if moment and moment.year < 9999:
            entry["utc"] = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        entry["value"] = prop.value
    return entry


def property_from_json(entry):
    value_type = entry["type"]
    value_type = TYPES_BY_NAME[value_type] if isinstance(value_type, str) else int(value_type)
    identifier = int(entry["id"], 16) if isinstance(entry["id"], str) else int(entry["id"])
    value = entry.get("value")
    if value is not None:
        if value_type == cedb.CEVT_BLOB:
            value = base64.b64decode(value)
        elif value_type == cedb.CEVT_BOOL:
            value = bool(value)
        elif value_type == cedb.CEVT_R8:
            value = float(value)
        elif value_type != cedb.CEVT_LPWSTR:
            value = int(value)
    return cedb.PropertyValue(identifier, value_type, value, entry.get("flags", 0))


def properties_to_json(properties):
    return [property_to_json(prop) for prop in properties]


def properties_from_json(entries):
    return [property_from_json(entry) for entry in entries]


def record_to_json(oid, properties, database=""):
    document = {"oid": oid, "properties": properties_to_json(properties)}
    if database:
        document = {"database": database, **document}
    return json.dumps(document, indent=1, ensure_ascii=False) + "\n"


def record_from_json(text):
    document = json.loads(text)
    return document.get("oid", 0), properties_from_json(document["properties"])


def sorted_properties(properties):
    return sorted(properties, key=lambda prop: (prop.identifier, prop.value_type))


def properties_hash(properties):
    canonical = json.dumps(properties_to_json(sorted_properties(properties)), sort_keys=True)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()
