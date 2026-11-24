import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from ..folder import text_summary, write_file_atomically
from ..objects import CALENDAR, CONTACTS, TASKS, DeviceRecord
from ..pim.icalendar import appointment_to_ical, ical_to_appointment, ical_to_task, task_to_ical
from ..pim.merge import merge_component
from ..pim.properties import APPOINTMENT_START, SUBJECT
from ..pim.record import property_map
from ..pim.text import parse_line, unescape_text, unfold
from ..pim.vcard import contact_fields, contact_to_vcard, display_name, vcard_to_contact
from ..pim.vcard3 import card_version, vcard_in_version, vcard_to_version4
from ..provider import Store
from ..rawjson import properties_hash, record_from_json, record_to_json

DTSTAMP_LINE = re.compile(r"^DTSTAMP:.*$", re.MULTILINE)


@dataclass(frozen=True)
class PimCodec:
    component: str
    managed: frozenset
    managed_children: tuple = ()
    date_only: tuple = ()

    def to_text(self, properties, uid):
        raise NotImplementedError

    def from_text(self, text, base_properties, os_major):
        raise NotImplementedError

    def title(self, properties):
        return property_map(properties).get(SUBJECT) or ""

    def match_key(self, properties):
        return self.title(properties).strip().lower()


class ContactCodec(PimCodec):
    def to_text(self, properties, uid):
        return contact_to_vcard(properties, uid)

    def from_text(self, text, base_properties, os_major):
        return vcard_to_contact(vcard_to_version4(text), base_properties)

    def title(self, properties):
        return display_name(contact_fields(properties))


class AppointmentCodec(PimCodec):
    def to_text(self, properties, uid):
        return appointment_to_ical(properties, uid)

    def from_text(self, text, base_properties, os_major):
        return ical_to_appointment(text, base_properties, os_major)

    def match_key(self, properties):
        return (self.title(properties).strip().lower(), property_map(properties).get(APPOINTMENT_START))


class TaskCodec(PimCodec):
    def to_text(self, properties, uid):
        return task_to_ical(properties, uid)

    def from_text(self, text, base_properties, os_major):
        return ical_to_task(text, base_properties, os_major)


CONTACT_MANAGED = frozenset({
    "FN", "N", "ORG", "TITLE", "EMAIL", "TEL", "ADR", "URL", "RELATED", "X-ASSISTANT", "X-OFFICE-LOCATION", "CATEGORIES",
    "BDAY", "ANNIVERSARY", "X-ANNIVERSARY", "X-SPOUSE", "X-CHILDREN", "NOTE",
})
EVENT_MANAGED = frozenset({
    "DTSTAMP", "DTSTART", "DTEND", "DURATION", "SUMMARY", "LOCATION", "DESCRIPTION", "CLASS", "CATEGORIES", "TRANSP",
    "X-MICROSOFT-CDO-BUSYSTATUS",
})
TASK_MANAGED = frozenset({
    "DTSTAMP", "SUMMARY", "DTSTART", "DUE", "STATUS", "COMPLETED", "PERCENT-COMPLETE", "PRIORITY", "CLASS", "DESCRIPTION",
    "CATEGORIES",
})
CODECS = {
    CONTACTS.key: ContactCodec("VCARD", CONTACT_MANAGED),
    CALENDAR.key: AppointmentCodec("VEVENT", EVENT_MANAGED, ("VALARM",)),
    TASKS.key: TaskCodec("VTODO", TASK_MANAGED, date_only=("DTSTART", "DUE")),
}
TITLE_NAMES = {"VCARD": "FN", "VEVENT": "SUMMARY", "VTODO": "SUMMARY"}


def now_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def text_title(text, component):
    wanted = TITLE_NAMES[component]
    for raw in unfold(text):
        line = parse_line(raw)
        if line.name == wanted and line.value.strip():
            return unescape_text(line.value).strip()
    return ""


def text_uid(text, component):
    inside = False
    for raw in unfold(text):
        line = parse_line(raw)
        if line.name == "BEGIN" and line.value.strip().upper() == component:
            inside = True
        elif line.name == "UID" and inside:
            return line.value.strip()
    return ""


class RawRecords:
    def __init__(self, directory, database=""):
        self.directory = directory
        self.database = database

    def path(self, device_id):
        return self.directory / f"{device_id}.json"

    def load(self, device_id):
        if device_id and self.path(device_id).exists():
            return record_from_json(self.path(device_id).read_text(encoding="utf-8"))[1]
        return []

    def save(self, device_id, device_object):
        write_file_atomically(self.path(device_id),
                              record_to_json(device_object.oid, device_object.properties, self.database).encode("utf-8"))

    def remove(self, device_id):
        if device_id:
            self.path(device_id).unlink(missing_ok=True)


class RemotePimStore(Store):
    vcard_version = "3.0"

    def __init__(self, object_type, cache_directory, os_major):
        self.object_type = object_type
        self.codec = CODECS[object_type.key]
        self.os_major = os_major
        self.raw = RawRecords(cache_directory / object_type.key, object_type.database)
        self.texts = {}

    def list_remote(self):
        raise NotImplementedError

    def fetch_text(self, item_id):
        raise NotImplementedError

    def put_text(self, item_id, text, uid):
        raise NotImplementedError

    def delete_remote(self, item_id):
        raise NotImplementedError

    def text(self, item_id):
        if item_id not in self.texts:
            self.texts[item_id] = self.fetch_text(item_id)
        return self.texts[item_id]

    def list_items(self):
        return self.list_remote()

    def device_properties(self, item_id, base_properties):
        return self.codec.from_text(self.text(item_id), base_properties, self.os_major)

    def read_item(self, item_id, device_id):
        return DeviceRecord(self.device_properties(item_id, self.raw.load(device_id)))

    def remote_text(self, item_id, device_object):
        uid = None if item_id else uuid.uuid4().hex.upper()
        generated = self.codec.to_text(device_object.properties, uid)
        if self.codec.component != "VCARD":
            generated = DTSTAMP_LINE.sub(f"DTSTAMP:{now_stamp()}", generated.replace("\r\n", "\n")).replace("\n", "\r\n")
        existing = self.text(item_id) if item_id else ""
        if self.codec.component == "VCARD":
            generated = vcard_in_version(generated, card_version(existing) or self.vcard_version)
        merged = merge_component(existing, generated, self.codec.component, self.codec.managed, self.codec.managed_children,
                                 date_only_names=self.codec.date_only)
        return merged, text_uid(merged, self.codec.component) or uid

    def write_item(self, item_id, device_id, device_object):
        text, uid = self.remote_text(item_id, device_object)
        item_id, stamp = self.put_text(item_id, text, uid)
        self.texts[item_id] = text
        if device_id:
            self.raw.save(device_id, device_object)
        return item_id, stamp

    def device_updated(self, item_id, device_id, device_object):
        self.raw.save(device_id, device_object)

    def delete_item(self, item_id, device_id):
        self.delete_remote(item_id)
        self.texts.pop(item_id, None)
        self.raw.remove(device_id)

    def find_match(self, device_id, device_object, unmatched_item_ids):
        wanted = self.codec.match_key(device_object.properties)
        if not wanted or wanted == ("", None):
            return None
        for item_id in unmatched_item_ids:
            try:
                candidate = self.device_properties(item_id, [])
            except ValueError:
                continue
            if self.codec.match_key(candidate) == wanted:
                return item_id
        return None

    def same_content(self, item_id, device_id, device_object):
        try:
            merged = self.device_properties(item_id, device_object.properties)
        except ValueError:
            return False
        return properties_hash(merged) == properties_hash(device_object.properties)

    def duplicate_key(self, item_id):
        try:
            return properties_hash(self.device_properties(item_id, []))
        except ValueError:
            return None

    def describe(self, item_id):
        try:
            return text_title(self.text(item_id), self.codec.component) or item_id
        except Exception:
            return item_id

    def describe_device(self, device_id, device_object):
        return self.codec.title(device_object.properties) or None

    def describe_conflict(self, item_id, device_id, device_object):
        remote_text = self.text(item_id)
        device_text = self.codec.to_text(device_object.properties, None)
        device_title = self.describe_device(device_id, device_object) or device_id
        return [self.describe(item_id), *text_summary(remote_text)], [device_title, *text_summary(device_text)]
