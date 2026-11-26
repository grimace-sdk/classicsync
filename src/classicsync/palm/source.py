import hashlib
import re

from ..sync.objects import CALENDAR, CONTACTS, TASKS, DeviceFile, DeviceRecord
from ..sync.providers.notes.provider import NOTES, TEXT_EXTENSION
from ..sync.rawjson import properties_hash
from . import convert, records
from .dlp import OPEN_READ, OPEN_SECRET, OPEN_WRITE, DlpError, DlpStatus

RECORD_DELETED = 0x80
RECORD_ARCHIVED = 0x08
RECORD_SECRET = 0x10
MEMO_LIMIT = 4095
TITLE_LIMIT = 40
UNSAFE_TITLE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


class PalmKind:
    def __init__(self, database, parse, build, to_properties, from_properties):
        self.database = database
        self.parse = parse
        self.build = build
        self.to_properties = to_properties
        self.from_properties = from_properties


KINDS = {
    CONTACTS.key: PalmKind("AddressDB", records.parse_address, records.build_address, convert.address_to_properties,
                           convert.properties_to_address),
    CALENDAR.key: PalmKind("DatebookDB", records.parse_appointment, records.build_appointment, convert.appointment_to_properties,
                           convert.properties_to_appointment),
    TASKS.key: PalmKind("ToDoDB", records.parse_todo, records.build_todo, convert.todo_to_properties, convert.properties_to_todo),
    NOTES.key: PalmKind("MemoDB", records.parse_memo, records.build_memo, None, None),
}


def device_id_for(record_id):
    return f"{record_id:06x}"


def record_id_for(device_id):
    return int(device_id, 16)


class PalmDatabaseSource:
    def __init__(self, client, object_type):
        self.client = client
        self.kind = KINDS[object_type.key]
        self.handle = None
        self.app_info = b""
        self.categories = None
        self.categories_changed = False
        self.records = {}

    async def open(self):
        self.handle = await self.client.open_database(self.kind.database, OPEN_READ | OPEN_WRITE | OPEN_SECRET)
        self.app_info = await self.client.read_app_block(self.handle)
        self.categories = records.parse_categories(self.app_info)

    async def close(self):
        if self.handle is not None:
            await self.client.close_database(self.handle)
            self.handle = None

    def _properties(self, device_id):
        parsed, category, attributes = self.records[device_id]
        return self.kind.to_properties(parsed, self.categories.name_of(category) if category else "",
                                       bool(attributes & RECORD_SECRET))

    async def list(self):
        self.records = {}
        for index in range(await self.client.record_count(self.handle)):
            try:
                record_id, attributes, category, data = await self.client.read_record_by_index(self.handle, index)
            except DlpError as error:
                if error.status in (DlpStatus.RECORD_DELETED, DlpStatus.NOT_FOUND):
                    continue
                raise
            if attributes & (RECORD_DELETED | RECORD_ARCHIVED) or not data:
                continue
            self.records[device_id_for(record_id)] = (self.kind.parse(data), category, attributes)
        return {device_id: self.stamp(device_id) for device_id in self.records}

    def stamp(self, device_id):
        return properties_hash(self._properties(device_id), include_private=True)

    async def read(self, device_id):
        return DeviceRecord(self._properties(device_id), record_id_for(device_id))

    def to_device(self, device_object, base):
        parsed = self.kind.from_properties(device_object.properties, base)
        category_name, secret = convert.category_and_secret(device_object.properties)
        return parsed, category_name, secret

    async def written(self, device_id, device_object):
        return await self.read(device_id)

    def _category_index(self, name):
        if not name:
            return records.UNFILED
        index = self.categories.index_of(name)
        if index is None:
            index = self.categories.add(name)
            if index is None:
                return records.UNFILED
            self.categories_changed = True
        return index

    async def write(self, device_id, device_object):
        base, _category, previous = self.records.get(device_id, (None, 0, 0)) if device_id else (None, 0, 0)
        parsed, category_name, secret = self.to_device(device_object, base)
        category = self._category_index(category_name)
        attributes = RECORD_SECRET if secret is True or secret is None and previous & RECORD_SECRET else 0
        record_id = await self.client.write_record(self.handle, record_id_for(device_id) if device_id else 0, attributes, category,
                                                   self.kind.build(parsed))
        device_id = device_id_for(record_id)
        self.records[device_id] = (self.kind.parse(self.kind.build(parsed)), category, attributes)
        return device_id, self.stamp(device_id)

    async def delete(self, device_id):
        await self.client.delete_record(self.handle, record_id_for(device_id))
        self.records.pop(device_id, None)

    async def finish(self, store):
        if self.categories_changed:
            await self.client.write_app_block(self.handle, records.build_categories(self.categories, self.app_info))
            self.categories_changed = False
        await self.client.clean_up_database(self.handle)
        await self.client.reset_sync_flags(self.handle)


def memo_title(text):
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    title = UNSAFE_TITLE.sub(" ", first).strip(" .")
    return title[:TITLE_LIMIT].rstrip() or "Memo"


class PalmMemoSource(PalmDatabaseSource):
    def memo_file(self, device_id):
        text, category, _attributes = self.records[device_id]
        name = memo_title(text) + TEXT_EXTENSION
        folder = self.categories.name_of(category) if category else ""
        return DeviceFile(f"{folder}/{name}" if folder else name, text.encode("utf-8"))

    def stamp(self, device_id):
        memo = self.memo_file(device_id)
        return hashlib.sha1(memo.path.encode("utf-8") + b"\0" + memo.data).hexdigest()

    async def read(self, device_id):
        return self.memo_file(device_id)

    def to_device(self, device_object, base):
        text = device_object.data.decode("utf-8", errors="replace").replace("\r\n", "\n")[:MEMO_LIMIT]
        folder = device_object.path.rpartition("/")[0]
        return text, folder.split("/")[0] if folder else "", None
