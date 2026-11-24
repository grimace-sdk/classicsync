import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from ..i18n import N_, _, ngettext
from ..convert.registry import DOCUMENT, IMAGE, SPREADSHEET
from ..paths import user_data_directory
from ..rapi.structures import datetime_to_filetime, filetime_to_datetime
from .mail.maildir import MaildirStore
from .objects import CALENDAR, CONTACTS, FILES, MAIL, TASKS, DeviceFile, DeviceRecord
from .pim.icalendar import appointment_to_ical, ical_to_appointment, ical_to_task, task_to_ical
from .pim.properties import SUBJECT
from .pim.record import property_map
from .pim.vcard import contact_fields, contact_to_vcard, display_name, vcard_to_contact
from .provider import Provider, Store
from .converted import DESKTOP_CHOICES, ConvertedMirror, default_formats
from .rawjson import record_from_json, record_to_json
from .settings_schema import Setting
from .state import safe_directory_name

TRASH_FOLDER = ".trash"
PARTIAL_SUFFIX = ".part"
SUMMARY_LABELS = {
    "FN": N_("Name: {value}"), "ORG": N_("Company: {value}"), "TEL": N_("Phone: {value}"), "EMAIL": N_("E-mail: {value}"),
    "SUMMARY": N_("Subject: {value}"), "DTSTART": N_("Start: {value}"), "DUE": N_("Due: {value}"),
    "LOCATION": N_("Location: {value}"), "STATUS": N_("Status: {value}"),
}
SUMMARY_LINES = 5


def file_hash(data):
    return hashlib.sha1(data).hexdigest()


def write_file_atomically(path, data, modified=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + PARTIAL_SUFFIX)
    partial.write_bytes(data)
    if modified:
        seconds = filetime_to_datetime(modified).timestamp()
        os.utime(partial, (seconds, seconds))
    partial.replace(path)


def slug(text, limit=40):
    cleaned = re.sub(r"[^\w\- ]+", "", text, flags=re.UNICODE).strip().replace(" ", "-")
    return cleaned[:limit].strip("-") or "item"


def text_summary(text):
    lines = []
    for line in text.splitlines():
        name, separator, value = line.partition(":")
        label = SUMMARY_LABELS.get(name.split(";")[0].upper())
        value = value.replace("\\,", ",").replace("\\;", ";").strip(" ;")
        if label and value:
            lines.append(_(label).format(value=value))
    return lines[:SUMMARY_LINES]


def file_summary(name, size, modified):
    when = filetime_to_datetime(modified).astimezone().strftime("%d/%m/%Y %H:%M") if modified else ""
    size_text = ngettext("{size} byte", "{size} bytes", size).format(size=f"{size:,}")
    return [name, size_text, when] if when else [name, size_text]


class Trash:
    def __init__(self, root):
        self.root = root
        self.session = datetime.now().strftime("%Y%m%d-%H%M%S")

    def move(self, path):
        if not path.exists():
            return
        relative = path.relative_to(self.root)
        target = self.root / TRASH_FOLDER / self.session / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        counter = 1
        while target.exists():
            target = target.with_name(f"{path.stem} {counter}{path.suffix}")
            counter += 1
        path.replace(target)


class FileStore(Store):
    object_type = FILES

    def __init__(self, root, folders, depth, device_name, trash, mirror=None):
        self.root = root
        self.folders = [folder.strip("\\").split("\\")[-1] for folder in folders]
        self.depth = depth
        self.device_name = device_name
        self.trash = trash
        self.mirror = mirror
        for folder in self.folders:
            (root / folder).mkdir(parents=True, exist_ok=True)

    def path_for(self, item_id):
        return self.root.joinpath(*item_id.split("/"))

    def stamp(self, path):
        info = path.stat()
        return f"{info.st_mtime_ns}:{info.st_size}"

    def _scan(self, directory, item_prefix, depth, found):
        for entry in sorted(directory.iterdir()):
            if entry.name.startswith(".") or entry.name.endswith(PARTIAL_SUFFIX):
                continue
            item_id = f"{item_prefix}/{entry.name}"
            if entry.is_dir():
                if depth < self.depth:
                    self._scan(entry, item_id, depth + 1, found)
            elif entry.is_file():
                found[item_id] = self.stamp(entry)

    def list_items(self):
        if self.mirror:
            self.mirror.refresh(self.path_for)
        found = {}
        for folder in self.folders:
            directory = self.root / folder
            if directory.is_dir():
                self._scan(directory, folder, 0, found)
        return found

    def read_item(self, item_id, device_id):
        path = self.path_for(item_id)
        modified = datetime_to_filetime(datetime.fromtimestamp(path.stat().st_mtime, timezone.utc))
        return DeviceFile(item_id, path.read_bytes(), modified)

    def conflict_name(self, item_id):
        folder, _, name = item_id.rpartition("/")
        stem, dot, extension = name.rpartition(".")
        if not stem:
            stem, dot, extension = name, "", ""
        counter = 1
        while True:
            suffix = f" ({self.device_name})" if counter == 1 else f" ({self.device_name} {counter})"
            candidate = f"{folder}/{stem}{suffix}{dot}{extension}"
            if not self.path_for(candidate).exists():
                return candidate
            counter += 1

    def write_item(self, item_id, device_id, device_object):
        if item_id is None:
            item_id = device_object.path
            if self.path_for(item_id).exists():
                item_id = self.conflict_name(item_id)
        path = self.path_for(item_id)
        write_file_atomically(path, device_object.data, device_object.modified)
        if self.mirror:
            self.mirror.update_from_raw(item_id, path)
        return item_id, self.stamp(path)

    def delete_item(self, item_id, device_id):
        self.trash.move(self.path_for(item_id))
        if self.mirror:
            self.mirror.remove(item_id, self.trash)

    def find_match(self, device_id, device_object, unmatched_item_ids):
        wanted = device_id.lower()
        return next((item_id for item_id in unmatched_item_ids if item_id.lower() == wanted), None)

    def same_content(self, item_id, device_id, device_object):
        return self.path_for(item_id).read_bytes() == device_object.data

    def describe_device(self, device_id, device_object):
        return device_id

    def describe_conflict(self, item_id, device_id, device_object):
        path = self.path_for(item_id)
        info = path.stat()
        modified = datetime_to_filetime(datetime.fromtimestamp(info.st_mtime, timezone.utc))
        return (file_summary(item_id, info.st_size, modified),
                file_summary(device_id, len(device_object.data), device_object.modified))


class RecordStore(Store):
    extension = ""

    def __init__(self, root, directory_name, os_major, trash):
        self.root = root
        self.directory = root / directory_name
        self.raw_directory = self.directory / "raw"
        self.os_major = os_major
        self.trash = trash
        self.raw_directory.mkdir(parents=True, exist_ok=True)

    def to_text(self, properties, uid):
        raise NotImplementedError

    def from_text(self, text, base_properties):
        raise NotImplementedError

    def title(self, properties):
        return property_map(properties).get(SUBJECT) or ""

    def item_path(self, item_id):
        return self.directory / (item_id + self.extension)

    def raw_path(self, device_id):
        return self.raw_directory / f"{device_id}.json"

    def list_items(self):
        return {path.stem: file_hash(path.read_bytes()) for path in sorted(self.directory.glob("*" + self.extension))
                if not path.name.startswith(".")}

    def base_properties(self, device_id):
        if device_id and self.raw_path(device_id).exists():
            return record_from_json(self.raw_path(device_id).read_text(encoding="utf-8"))[1]
        return []

    def read_item(self, item_id, device_id):
        text = self.item_path(item_id).read_text(encoding="utf-8")
        return DeviceRecord(self.from_text(text, self.base_properties(device_id)))

    def new_item_id(self, properties, device_id):
        base = slug(self.title(properties))
        suffix = device_id or hashlib.sha1(repr(properties).encode()).hexdigest()[:8]
        item_id = f"{base}-{suffix}"
        counter = 2
        while self.item_path(item_id).exists():
            item_id = f"{base}-{suffix}-{counter}"
            counter += 1
        return item_id

    def save_raw(self, device_id, device_object):
        write_file_atomically(self.raw_path(device_id),
                              record_to_json(device_object.oid, device_object.properties, self.object_type.database).encode("utf-8"))

    def write_item(self, item_id, device_id, device_object):
        item_id = item_id or self.new_item_id(device_object.properties, device_id)
        data = self.to_text(device_object.properties, item_id).encode("utf-8")
        write_file_atomically(self.item_path(item_id), data)
        if device_id:
            self.save_raw(device_id, device_object)
        return item_id, file_hash(data)

    def device_updated(self, item_id, device_id, device_object):
        self.save_raw(device_id, device_object)

    def delete_item(self, item_id, device_id):
        self.trash.move(self.item_path(item_id))
        if device_id:
            self.trash.move(self.raw_path(device_id))

    def describe(self, item_id):
        return item_id + self.extension

    def describe_device(self, device_id, device_object):
        return self.title(device_object.properties) or None

    def describe_conflict(self, item_id, device_id, device_object):
        path = self.item_path(item_id)
        desktop_text = path.read_text(encoding="utf-8") if path.exists() else ""
        device_text = self.to_text(device_object.properties, item_id)
        device_title = self.describe_device(device_id, device_object) or device_id
        return [self.describe(item_id), *text_summary(desktop_text)], [device_title, *text_summary(device_text)]


class ContactStore(RecordStore):
    object_type = CONTACTS
    extension = ".vcf"

    def __init__(self, root, os_major, trash):
        super().__init__(root, "Contacts", os_major, trash)

    def title(self, properties):
        return display_name(contact_fields(properties))

    def to_text(self, properties, uid):
        return contact_to_vcard(properties, uid)

    def from_text(self, text, base_properties):
        return vcard_to_contact(text, base_properties)


class CalendarStore(RecordStore):
    object_type = CALENDAR
    extension = ".ics"

    def __init__(self, root, os_major, trash):
        super().__init__(root, "Calendar", os_major, trash)

    def to_text(self, properties, uid):
        return appointment_to_ical(properties, uid)

    def from_text(self, text, base_properties):
        return ical_to_appointment(text, base_properties, self.os_major)


class TaskStore(RecordStore):
    object_type = TASKS
    extension = ".ics"

    def __init__(self, root, os_major, trash):
        super().__init__(root, "Tasks", os_major, trash)

    def to_text(self, properties, uid):
        return task_to_ical(properties, uid)

    def from_text(self, text, base_properties):
        return ical_to_task(text, base_properties, self.os_major)


DEFAULT_FORMATS = default_formats()
CONVERTED_FORMAT_KEYS = {DOCUMENT: "converted_documents", SPREADSHEET: "converted_spreadsheets", IMAGE: "converted_images"}


def default_folder(device_name):
    return user_data_directory() / safe_directory_name(device_name)


class FolderProvider(Provider):
    name = "folder"
    display_name = N_("Folder")
    object_types = (FILES, CONTACTS, CALENDAR, TASKS, MAIL)
    settings_schema = (
        Setting("folder", N_("Folder on this computer"), "path", per_device=True,
                help=N_("Where the desktop copies are kept. Empty: a folder named after the device in the classicsync data folder.")),
        Setting("convert_documents", N_("Convert documents"), "bool", True,
                help=N_("Keep Word, Excel and image copies of Pocket Word, Pocket Excel and 2bp files in a Converted folder.")),
        Setting("converted_documents", N_("Converted documents"), "choice", DEFAULT_FORMATS[DOCUMENT],
                choices=DESKTOP_CHOICES[DOCUMENT],
                help=N_("Format of the Converted copies of Pocket Word documents. Changing it replaces the copies.")),
        Setting("converted_spreadsheets", N_("Converted spreadsheets"), "choice", DEFAULT_FORMATS[SPREADSHEET],
                choices=DESKTOP_CHOICES[SPREADSHEET],
                help=N_("Format of the Converted copies of Pocket Excel workbooks. CSV holds the first sheet only; "
                        "edits to it keep the other sheets and formulas whose values did not change.")),
        Setting("converted_images", N_("Converted images"), "choice", DEFAULT_FORMATS[IMAGE],
                choices=DESKTOP_CHOICES[IMAGE], help=N_("Format of the Converted copies of 2bp images.")),
        Setting("file_folders", N_("Device folders"), "list", ["\\My Documents"], per_device=True,
                help=N_("Device folders to synchronize.")),
        Setting("file_depth", N_("Subfolder depth"), "int", 1, minimum=0, per_device=True,
                help=N_("How many levels of subfolders to synchronize below each device folder.")),
    )

    def __init__(self, context):
        super().__init__(context)
        settings = context.settings
        self.root = Path(settings["folder"]).expanduser() if settings.get("folder") else default_folder(context.device.name)
        self.root.mkdir(parents=True, exist_ok=True)
        self.trash = Trash(self.root)

    def open_store(self, object_type):
        settings = self.context.settings
        os_major = self.context.device.os_major
        if object_type.key == FILES.key:
            folders = settings.get("file_folders", ["\\My Documents"])
            mirror = None
            if settings.get("convert_documents", True):
                names = [folder.strip("\\").split("\\")[-1] for folder in folders]
                formats = {kind: settings.get(key) for kind, key in CONVERTED_FORMAT_KEYS.items() if settings.get(key)}
                mirror = ConvertedMirror(self.root, names, os_major, self.context.message, formats, self.trash)
            return FileStore(self.root, folders, settings.get("file_depth", 1), self.context.device.name, self.trash, mirror)
        if object_type.key == CONTACTS.key:
            return ContactStore(self.root, os_major, self.trash)
        if object_type.key == CALENDAR.key:
            return CalendarStore(self.root, os_major, self.trash)
        if object_type.key == TASKS.key:
            return TaskStore(self.root, os_major, self.trash)
        if object_type.key == MAIL.key:
            return MaildirStore(self.root, self.trash, self.context.device.name)
        raise ValueError(f"folder provider does not handle {object_type.key}")
