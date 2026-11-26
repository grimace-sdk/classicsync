from ..sync.objects import CALENDAR, CONTACTS, TASKS, DeviceRecord
from ..sync.rawjson import properties_hash
from . import convert, records
from .dlp import OPEN_READ, OPEN_SECRET, OPEN_WRITE, DlpError, DlpStatus

RECORD_DELETED = 0x80
RECORD_ARCHIVED = 0x08
RECORD_SECRET = 0x10


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
        return {device_id: properties_hash(self._properties(device_id), include_private=True) for device_id in self.records}

    async def read(self, device_id):
        return DeviceRecord(self._properties(device_id), record_id_for(device_id))

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
        base = self.records.get(device_id, (None, 0, 0))[0] if device_id else None
        parsed = self.kind.from_properties(device_object.properties, base)
        category_name, secret = convert.category_and_secret(device_object.properties)
        category = self._category_index(category_name)
        attributes = RECORD_SECRET if secret else 0
        record_id = await self.client.write_record(self.handle, record_id_for(device_id) if device_id else 0, attributes, category,
                                                   self.kind.build(parsed))
        device_id = device_id_for(record_id)
        self.records[device_id] = (self.kind.parse(self.kind.build(parsed)), category, attributes)
        return device_id, properties_hash(self._properties(device_id), include_private=True)

    async def delete(self, device_id):
        await self.client.delete_record(self.handle, record_id_for(device_id))
        self.records.pop(device_id, None)

    async def finish(self, store):
        if self.categories_changed:
            await self.client.write_app_block(self.handle, records.build_categories(self.categories, self.app_info))
            self.categories_changed = False
        await self.client.clean_up_database(self.handle)
        await self.client.reset_sync_flags(self.handle)
