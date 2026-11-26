from ..rapi import cedb
from ..rapi.client import HKEY_LOCAL_MACHINE, RapiError
from .objects import DeviceFile, DeviceInfo, DeviceRecord
from .pim.properties import PRIVATE_IDENTIFIERS
from .rawjson import properties_hash

INVALID_DEVICE_NAME_CHARACTERS = set('\\:*?"<>|')
ERROR_ALREADY_EXISTS = 183
FREE_MARGIN = 64 * 1024


class DeviceSourceError(Exception):
    pass


def device_id_for_oid(oid):
    return f"{oid:08x}"


def oid_for_device_id(device_id):
    return int(device_id, 16)


def file_stamp(entry):
    return f"{entry.last_write_time}:{entry.size}"


async def read_device_info(client):
    version = client.version or await client.get_version()
    name = ""
    try:
        key = await client.reg_open_key(HKEY_LOCAL_MACHINE, "Ident")
        try:
            _, name = await client.reg_query_value(key, "Name")
        finally:
            await client.reg_close_key(key)
    except RapiError:
        pass
    return DeviceInfo(name=name or "Device", os_major=version.major, os_minor=version.minor)


class DeviceDatabase:
    def __init__(self, client, name):
        self.client = client
        self.name = name
        self.handle = None
        self.records = {}

    async def open(self):
        self.handle, _ = await self.client.open_database(self.name)

    async def close(self):
        if self.handle is not None:
            await self.client.close_handle(self.handle)
            self.handle = None

    async def list(self):
        self.records = {}
        await self.client.seek_database(self.handle, cedb.CEDB_SEEK_BEGINNING)
        while (record := await self.client.read_record(self.handle)) is not None:
            oid, properties = record
            self.records[device_id_for_oid(oid)] = [prop for prop in properties if not prop.missing]
        return {device_id: properties_hash(properties) for device_id, properties in self.records.items()}

    async def read(self, device_id):
        return DeviceRecord(list(self.records[device_id]), oid_for_device_id(device_id))

    async def written(self, device_id, device_object):
        return await self.read(device_id)

    async def _reread(self, oid):
        await self.client.seek_database(self.handle, cedb.CEDB_SEEK_CEOID, oid)
        record = await self.client.read_record(self.handle)
        if record is None:
            raise RapiError(f"CeReadRecordProps 0x{oid:08x}", 1168)
        return [prop for prop in record[1] if not prop.missing]

    async def write(self, device_id, device_object):
        properties = [prop for prop in device_object.properties
                      if prop.value is not None and not prop.flags and prop.identifier not in PRIVATE_IDENTIFIERS]
        oid = oid_for_device_id(device_id) if device_id else 0
        if device_id and device_id in self.records:
            wanted = {prop.propid for prop in properties}
            for old in self.records[device_id]:
                if old.propid not in wanted:
                    properties.append(cedb.PropertyValue(old.identifier, old.value_type, None, cedb.CEDB_PROPDELETE))
        oid = await self.client.write_record(self.handle, oid, properties)
        device_id = device_id_for_oid(oid)
        self.records[device_id] = await self._reread(oid)
        return device_id, properties_hash(self.records[device_id])

    async def delete(self, device_id):
        await self.client.delete_record(self.handle, oid_for_device_id(device_id))
        self.records.pop(device_id, None)


class DeviceFolder:
    def __init__(self, client, roots, depth=1, extensions=()):
        self.client = client
        self.roots = {root.strip("\\").split("\\")[-1]: "\\" + root.strip("\\") for root in roots}
        self.depth = depth
        self.extensions = tuple(extension.lower() for extension in extensions)
        self.entries = {}
        self.free_space = None

    async def open(self):
        try:
            self.free_space = (await self.client.get_store_information()).free_size
        except RapiError:
            self.free_space = None

    async def close(self):
        pass

    def device_path(self, device_id):
        root, *rest = device_id.split("/")
        return "\\".join([self.roots[root], *rest])

    async def _scan(self, device_id, depth):
        pattern = self.device_path(device_id) + "\\*.*"
        try:
            entries = await self.client.find_all_files(pattern)
        except RapiError:
            return
        for entry in entries:
            child = f"{device_id}/{entry.name}"
            if entry.is_directory:
                if depth < self.depth:
                    await self._scan(child, depth + 1)
            elif self.wanted(entry.name):
                self.entries[child] = entry

    def wanted(self, name):
        return not self.extensions or name.lower().endswith(self.extensions)

    async def list(self):
        self.entries = {}
        for root in self.roots:
            await self._scan(root, 0)
        return {device_id: file_stamp(entry) for device_id, entry in self.entries.items()}

    def valid_id(self, device_id):
        root, *rest = device_id.split("/")
        return root in self.roots and 0 < len(rest) <= self.depth + 1 and self.wanted(rest[-1] if rest else "") and not any(
            character in INVALID_DEVICE_NAME_CHARACTERS for part in rest for character in part)

    async def read(self, device_id):
        entry = self.entries[device_id]
        data = await self.client.read_file_contents(self.device_path(device_id))
        return DeviceFile(device_id, data, entry.last_write_time, entry.attributes)

    async def written(self, device_id, device_object):
        entry = self.entries[device_id]
        return DeviceFile(device_id, device_object.data, entry.last_write_time, entry.attributes)

    async def _make_directory(self, path):
        try:
            await self.client.create_directory(path)
        except RapiError as error:
            if error.code != ERROR_ALREADY_EXISTS:
                try:
                    await self.client.get_file_attributes(path)
                except RapiError:
                    raise error from None

    async def _make_parents(self, device_id):
        root, *rest = device_id.split("/")
        path = self.roots[root]
        await self._make_directory(path)
        for part in rest[:-1]:
            path = path + "\\" + part
            await self._make_directory(path)

    async def write(self, device_id, device_object):
        device_id = device_id or device_object.path
        if not self.valid_id(device_id):
            raise ValueError(f"{device_id} can't be stored on the device")
        if self.free_space is not None and len(device_object.data) + FREE_MARGIN > self.free_space:
            raise ValueError(f"not enough storage on the device for {device_id}")
        await self._make_parents(device_id)
        path = self.device_path(device_id)
        await self.client.write_file_contents(path, device_object.data, modified=device_object.modified or None)
        entries = await self.client.find_all_files(path)
        if not entries:
            raise RapiError(f"CeFindAllFiles {path}", 2)
        self.entries[device_id] = entries[0]
        if self.free_space is not None:
            self.free_space = max(0, self.free_space - len(device_object.data))
        return device_id, file_stamp(entries[0])

    async def delete(self, device_id):
        await self.client.delete_file(self.device_path(device_id))
        self.entries.pop(device_id, None)
