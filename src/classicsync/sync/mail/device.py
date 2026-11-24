from ...i18n import _
from ...rapi import cedb
from ...rapi.cedb import PropertyValue
from ...rapi.client import RapiError
from ..rawjson import properties_hash
from .records import (
    FOLDER_INBOX, FOLDER_MASK, FOLDER_OUTBOX, HELPER_DATABASE, LAST_USER_FOLDER_V1, LAST_USER_FOLDER_V2, MESSAGE_DATABASE,
    SPECIAL_FOLDERS, STATUS_COMPOSED, STATUS_DELETE, STATUS_READ, V1_FLAGS, V1_LAST_ID, V1_VERSION, V2_FLAGS, V2_LAST_ID,
    V2_SERVICE_MESSAGE_OID, V2_SERVICE_OID, V2_VERSION, VERSION_1, VERSION_2, VERSION_3, folder_from_v1,
    folder_from_v2, is_head_v1, is_head_v2, is_message_v1, is_message_v2, is_service_v2, message_from_v1, message_from_v2,
    v1_folder_properties, v1_properties, v2_folder_properties, v2_properties, v2_service_properties, values_by_key,
)
from .rfc5322 import content_key

DELETED_FOLDER_V1 = "Deleted Items"
DELETED_FOLDER_V2 = "Deleted"
DEFAULT_SERVICE_V1 = "Mail"
DEFAULT_SERVICE_V2 = "Windows CE Inbox Services"
ROOT_FOLDER_V3 = 0xFA
FOLDER_NAME_LIMIT_V1 = 15


def device_id_for_oid(oid):
    return f"{oid:08x}"


def oid_for_device_id(device_id):
    return int(device_id, 16)


class DeviceMailbox:
    def __init__(self, client):
        self.client = client
        self.message_handle = None
        self.helper_handle = None
        self.version = None
        self.head_oid = 0
        self.last_id = 0
        self.folders = {}
        self.folder_oids = {}
        self.messages = {}
        self.services = {}

    @property
    def single_database(self):
        return self.version is not None and self.version < VERSION_2

    @property
    def deleted_folder(self):
        return DELETED_FOLDER_V1 if self.single_database else DELETED_FOLDER_V2

    async def open(self):
        names = {entry.get("name", "").lower() for entry in await self.client.find_all_databases()}
        if MESSAGE_DATABASE.lower() not in names:
            return
        self.message_handle, _ = await self.client.open_database(MESSAGE_DATABASE)
        if HELPER_DATABASE.lower() in names:
            self.helper_handle, _ = await self.client.open_database(HELPER_DATABASE)

    async def close(self):
        for handle in (self.message_handle, self.helper_handle):
            if handle is not None:
                await self.client.close_handle(handle)
        self.message_handle = self.helper_handle = None

    async def read_all(self, handle):
        await self.client.seek_database(handle, cedb.CEDB_SEEK_BEGINNING)
        found = []
        while (record := await self.client.read_record(handle)) is not None:
            oid, properties = record
            found.append((oid, [prop for prop in properties if not prop.missing]))
        return found

    async def reread(self, handle, oid):
        await self.client.seek_database(handle, cedb.CEDB_SEEK_CEOID, oid)
        record = await self.client.read_record(handle)
        if record is None:
            raise RapiError(f"CeReadRecordProps 0x{oid:08x}", 1168)
        return [prop for prop in record[1] if not prop.missing]

    def load_head(self, message_records):
        for oid, properties in message_records:
            values = values_by_key(properties)
            if is_head_v1(values):
                self.version, self.last_id, self.head_oid = values[V1_VERSION], values.get(V1_LAST_ID, 0), oid
                return
            if is_head_v2(values):
                self.version, self.last_id, self.head_oid = values[V2_VERSION], values.get(V2_LAST_ID, 0), oid
                return
        self.version = VERSION_1 if self.helper_handle is None else VERSION_2

    async def list(self):
        self.messages, self.folders, self.folder_oids, self.services = {}, {}, {}, {}
        if self.message_handle is None:
            return {}
        message_records = await self.read_all(self.message_handle)
        self.load_head(message_records)
        if self.single_database:
            for oid, properties in message_records:
                values = values_by_key(properties)
                folder = folder_from_v1(values)
                if folder:
                    self.folders[folder[0]] = folder[1]
                    self.folder_oids[folder[0]] = oid
                elif is_message_v1(values):
                    self.messages[device_id_for_oid(oid)] = properties
        else:
            for oid, properties in await self.read_all(self.helper_handle) if self.helper_handle is not None else []:
                values = values_by_key(properties)
                folder = folder_from_v2(values)
                if folder:
                    self.folders[folder[0]] = folder[1]
                    self.folder_oids[folder[0]] = oid
                elif is_service_v2(values):
                    self.services[oid] = properties
            for oid, properties in message_records:
                if is_message_v2(values_by_key(properties)):
                    self.messages[device_id_for_oid(oid)] = properties
        return {device_id: self.stamp(device_id) for device_id in self.messages}

    def stamp(self, device_id):
        return properties_hash(self.messages[device_id])

    def folder_name(self, message):
        if message.deleted:
            return self.deleted_folder
        return self.folders.get(message.folder_id, f"Folder {message.folder_id}")

    def message(self, device_id):
        oid = oid_for_device_id(device_id)
        properties = self.messages[device_id]
        if self.single_database:
            message = message_from_v1(properties, oid)
        else:
            service_oid = values_by_key(properties).get(V2_SERVICE_OID, 0)
            message = message_from_v2(properties, self.services.get(service_oid, []), oid)
        message.folder = self.folder_name(message)
        return message

    async def read(self, device_id):
        return self.message(device_id)

    async def written(self, device_id, device_object):
        return self.message(device_id)

    def folder_names(self):
        return list(self.folders.values())

    def find_folder(self, name):
        wanted = name.lower()
        return next((folder_id for folder_id, folder_name in self.folders.items() if folder_name.lower() == wanted), None)

    def free_folder_id(self):
        last = LAST_USER_FOLDER_V1 if self.single_database else LAST_USER_FOLDER_V2
        for folder_id in range(0, last + 1):
            if folder_id not in self.folders:
                return folder_id
        raise ValueError(_("the device has no room for another Inbox folder"))

    async def create_folder(self, name):
        if self.single_database:
            name = name[:FOLDER_NAME_LIMIT_V1]
        existing = self.find_folder(name)
        if existing is not None:
            return existing
        folder_id = self.free_folder_id()
        if self.single_database:
            oid = await self.client.write_record(self.message_handle, 0, v1_folder_properties(folder_id, name))
        else:
            parent = ROOT_FOLDER_V3 if self.version >= VERSION_3 else None
            oid = await self.client.write_record(self.helper_handle, 0, v2_folder_properties(folder_id, name, parent))
        self.folders[folder_id] = name
        self.folder_oids[folder_id] = oid
        return folder_id

    def folder_in_use(self, folder_id):
        return any(self.message(device_id).folder_id == folder_id for device_id in self.messages)

    async def delete_folder(self, name):
        folder_id = self.find_folder(name)
        if folder_id is None or folder_id in SPECIAL_FOLDERS or self.folder_in_use(folder_id):
            return False
        handle = self.message_handle if self.single_database else self.helper_handle
        await self.client.delete_record(handle, self.folder_oids.pop(folder_id))
        del self.folders[folder_id]
        return True

    async def next_message_id(self):
        self.last_id += 1
        last_id = PropertyValue(*(V1_LAST_ID if self.single_database else V2_LAST_ID), self.last_id)
        await self.client.write_record(self.message_handle, self.head_oid, [last_id])
        return self.last_id

    def require_store(self):
        if self.message_handle is None or self.version is None:
            raise ValueError(_("Inbox has not been set up on the device: open Inbox on the device once, then synchronize again"))

    def default_service(self):
        for device_id in self.messages:
            message = self.message(device_id)
            if message.flags & STATUS_COMPOSED and message.service_name:
                return message.service_name
        return DEFAULT_SERVICE_V1 if self.single_database else DEFAULT_SERVICE_V2

    def composed_flags(self):
        return STATUS_COMPOSED if self.single_database else STATUS_COMPOSED | STATUS_READ

    async def target_folder(self, message, existing):
        if message.folder.lower() == self.deleted_folder.lower():
            return (existing.folder_id if existing else FOLDER_INBOX), STATUS_DELETE
        return await self.create_folder(message.folder or self.folders.get(FOLDER_INBOX, "Inbox")), 0

    async def write(self, device_id, device_object):
        self.require_store()
        existing = self.message(device_id) if device_id in self.messages else None
        folder_id, deleted = await self.target_folder(device_object, existing)
        if existing:
            oid = await self.update_message(existing, device_object, folder_id, deleted)
        else:
            oid = await self.add_message(device_object, folder_id, deleted)
        device_id = device_id_for_oid(oid)
        self.messages[device_id] = await self.reread(self.message_handle, oid)
        return device_id, self.stamp(device_id)

    async def update_message(self, existing, incoming, folder_id, deleted):
        existing.flags = (existing.flags & ~(STATUS_READ | STATUS_DELETE)) | (incoming.flags & STATUS_READ) | deleted
        existing.folder_id = folder_id
        flags_key = V1_FLAGS if self.single_database else V2_FLAGS
        if content_key(existing) == content_key(incoming):
            changes = [PropertyValue(*flags_key, (existing.flags & ~FOLDER_MASK) | folder_id)]
        else:
            existing.headers, existing.body, existing.date = incoming.headers, incoming.body, incoming.date
            existing.message_length = 0
            if self.single_database:
                changes = v1_properties(existing)
            else:
                service_oid = values_by_key(self.messages[device_id_for_oid(existing.oid)]).get(V2_SERVICE_OID, 0)
                changes = v2_properties(existing, service_oid)
        return await self.client.write_record(self.message_handle, existing.oid, changes)

    async def add_message(self, incoming, folder_id, deleted):
        incoming.message_id = await self.next_message_id()
        incoming.folder_id = folder_id
        incoming.flags = (incoming.flags & STATUS_READ) | deleted
        incoming.message_length = 0
        if folder_id == FOLDER_OUTBOX:
            incoming.flags |= self.composed_flags()
            incoming.service_name = incoming.service_name or self.default_service()
        if self.single_database:
            return await self.client.write_record(self.message_handle, 0, v1_properties(incoming))
        service_oid = await self.client.write_record(self.helper_handle, 0, v2_service_properties(incoming))
        oid = await self.client.write_record(self.message_handle, 0, v2_properties(incoming, service_oid))
        await self.client.write_record(self.helper_handle, service_oid, [PropertyValue(*V2_SERVICE_MESSAGE_OID, oid)])
        self.services[service_oid] = await self.reread(self.helper_handle, service_oid)
        return oid

    async def delete(self, device_id):
        properties = self.messages.get(device_id, [])
        await self.client.delete_record(self.message_handle, oid_for_device_id(device_id))
        service_oid = values_by_key(properties).get(V2_SERVICE_OID, 0)
        if service_oid and self.helper_handle is not None and service_oid in self.services:
            await self.client.delete_record(self.helper_handle, service_oid)
            self.services.pop(service_oid, None)
        self.messages.pop(device_id, None)

    async def finish(self, store):
        if self.version is None:
            return
        known = {name.lower() for name in store.known_folders()}
        device_names = {name.lower(): name for name in self.folder_names()}
        desktop_names = {name.lower(): name for name in store.folder_names() if name.lower() != self.deleted_folder.lower()}
        for lower, name in desktop_names.items():
            if lower in device_names:
                continue
            if lower in known:
                store.remove_folder(name)
            else:
                await self.create_folder(name)
        for lower, name in device_names.items():
            if lower in desktop_names:
                continue
            if lower in known and await self.delete_folder(name):
                continue
            store.create_folder(name)
        store.save_known_folders(self.folder_names())
