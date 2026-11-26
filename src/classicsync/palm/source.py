import hashlib

from ..sync.objects import DeviceFile, DeviceRecord
from ..sync.rawjson import properties_hash
from . import records
from .dlp import OPEN_READ, OPEN_SECRET, OPEN_WRITE, DlpError, DlpStatus

RECORD_DELETED = 0x80
RECORD_ARCHIVED = 0x08
RECORD_SECRET = 0x10


def device_id_for(record_id):
    return f"{record_id:06x}"


def record_id_for(device_id):
    return int(device_id, 16)


def device_object_stamp(device_object):
    if isinstance(device_object, DeviceFile):
        return hashlib.sha1(device_object.path.encode("utf-8") + b"\0" + device_object.data).hexdigest()
    return properties_hash(device_object.properties, include_private=True)


class PalmDatabaseSource:
    def __init__(self, client, conduit):
        self.client = client
        self.conduit = conduit
        self.handle = None
        self.app_info = b""
        self.categories = None
        self.categories_changed = False
        self.records = {}

    async def open(self):
        self.handle = await self.client.open_database(self.conduit.database, OPEN_READ | OPEN_WRITE | OPEN_SECRET)
        self.app_info = await self.client.read_app_block(self.handle)
        self.categories = records.parse_categories(self.app_info)

    async def close(self):
        if self.handle is not None:
            await self.client.close_database(self.handle)
            self.handle = None

    def device_object(self, device_id):
        record, category, attributes = self.records[device_id]
        device_object = self.conduit.to_desktop(record, self.categories.name_of(category) if category else "",
                                                bool(attributes & RECORD_SECRET))
        if isinstance(device_object, DeviceRecord):
            device_object.oid = record_id_for(device_id)
        return device_object

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
            self.records[device_id_for(record_id)] = (self.conduit.parse(data), category, attributes)
        return {device_id: device_object_stamp(self.device_object(device_id)) for device_id in self.records}

    async def read(self, device_id):
        return self.device_object(device_id)

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
        record, category_name, secret = self.conduit.from_desktop(device_object, base)
        category = self._category_index(category_name)
        keep_secret = secret is None and previous & RECORD_SECRET
        attributes = RECORD_SECRET if secret or keep_secret else 0
        data = self.conduit.build(record)
        record_id = await self.client.write_record(self.handle, record_id_for(device_id) if device_id else 0, attributes, category,
                                                   data)
        device_id = device_id_for(record_id)
        self.records[device_id] = (self.conduit.parse(data), category, attributes)
        return device_id, device_object_stamp(self.device_object(device_id))

    async def delete(self, device_id):
        await self.client.delete_record(self.handle, record_id_for(device_id))
        self.records.pop(device_id, None)

    async def finish(self, store):
        if self.categories_changed:
            await self.client.write_app_block(self.handle, records.build_categories(self.categories, self.app_info))
            self.categories_changed = False
        await self.client.clean_up_database(self.handle)
        await self.client.reset_sync_flags(self.handle)
