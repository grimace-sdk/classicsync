import fnmatch
from types import SimpleNamespace

from classicsync.rapi import cedb
from classicsync.rapi.client import HKEY_LOCAL_MACHINE, REG_DWORD, REG_SZ, RapiError
from classicsync.rapi.structures import FILE_ATTRIBUTE_DIRECTORY, FILE_ATTRIBUTE_NORMAL, FindData, StoreInformation, VersionInfo


class FakeRapiClient:
    def __init__(self, name="HPC", os_major=2):
        self.registry = {}
        self.keys = {}
        self.next_key = 0x100
        self.name = name
        if os_major >= 2:
            self.registry[(HKEY_LOCAL_MACHINE, "software\\microsoft\\windows ce services")] = {"Version": (REG_DWORD, 0x20000)}
        self.version = None
        self.os_major = os_major
        self.files = {}
        self.directories = {"\\my documents": "\\My Documents"}
        self.databases = {"Contacts Database": {}, "Appointments Database": {}, "Tasks Database": {}}
        self.handles = {}
        self.next_oid = 0x1000
        self.clock = 130000000000000000

    def tick(self):
        self.clock += 10_000_000
        return self.clock

    def put_file(self, path, data, modified=None):
        self.files[path.lower()] = SimpleNamespace(path=path, data=bytes(data), modified=modified or self.tick())

    def file(self, path):
        return self.files[path.lower()].data

    def add_record(self, database, properties):
        self.next_oid += 1
        self.databases[database][self.next_oid] = list(properties)
        return self.next_oid

    async def get_version(self):
        self.version = VersionInfo(self.os_major, 0, 0, 3, "")
        return self.version

    @property
    def name(self):
        return self.registry[(HKEY_LOCAL_MACHINE, "ident")]["Name"][1]

    @name.setter
    def name(self, value):
        self.registry.setdefault((HKEY_LOCAL_MACHINE, "ident"), {})["Name"] = (REG_SZ, value)

    def registry_value(self, subkey, name):
        values = self.registry.get((HKEY_LOCAL_MACHINE, subkey.lower()))
        return values[name][1] if values and name in values else None

    async def reg_open_key(self, root, subkey):
        if (root, subkey.lower()) not in self.registry:
            raise RapiError(f"CeRegOpenKeyEx {subkey}", 2)
        self.next_key += 1
        self.keys[self.next_key] = (root, subkey.lower())
        return self.next_key

    async def reg_create_key(self, root, subkey, class_name=""):
        disposition = 2 if (root, subkey.lower()) in self.registry else 1
        self.registry.setdefault((root, subkey.lower()), {})
        return await self.reg_open_key(root, subkey), disposition

    async def reg_query_value(self, handle, name):
        values = self.registry[self.keys[handle]]
        if name not in values:
            raise RapiError(f"CeRegQueryValueEx {name}", 2)
        return values[name]

    async def reg_set_value(self, handle, name, value_type, value):
        self.registry[self.keys[handle]][name] = (value_type, value)

    async def reg_delete_key(self, handle, subkey):
        root, path = self.keys[handle]
        key = (root, f"{path}\\{subkey.lower()}")
        if key not in self.registry:
            raise RapiError(f"CeRegDeleteKey {subkey}", 2)
        del self.registry[key]

    async def reg_close_key(self, handle):
        self.keys.pop(handle, None)

    async def get_store_information(self):
        return StoreInformation(8 << 20, 4 << 20)

    async def open_database(self, name=None, oid=0, sort_propid=0, flags=0):
        if name not in self.databases:
            raise RapiError(f"CeOpenDatabase {name}", 2)
        handle = len(self.handles) + 100
        self.handles[handle] = SimpleNamespace(name=name, position=0)
        return handle, 0

    async def close_handle(self, handle):
        self.handles.pop(handle, None)

    async def seek_database(self, handle, seek_type, value=0):
        cursor = self.handles[handle]
        oids = sorted(self.databases[cursor.name])
        if seek_type == cedb.CEDB_SEEK_CEOID:
            cursor.position = oids.index(value)
        else:
            cursor.position = 0
        return value, cursor.position, 0

    async def read_record(self, handle, propids=None, buffer_size=0):
        cursor = self.handles[handle]
        oids = sorted(self.databases[cursor.name])
        if cursor.position >= len(oids):
            return None
        oid = oids[cursor.position]
        cursor.position += 1
        return oid, [cedb.PropertyValue(prop.identifier, prop.value_type, prop.value) for prop in self.databases[cursor.name][oid]]

    async def write_record(self, handle, oid, properties):
        records = self.databases[self.handles[handle].name]
        if oid == 0:
            self.next_oid += 1
            oid = self.next_oid
            records[oid] = []
        current = {prop.propid: prop for prop in records[oid]}
        for prop in properties:
            if prop.flags & cedb.CEDB_PROPDELETE:
                current.pop(prop.propid, None)
            else:
                current[prop.propid] = cedb.PropertyValue(prop.identifier, prop.value_type, prop.value)
        records[oid] = list(current.values())
        return oid

    async def delete_record(self, handle, oid):
        del self.databases[self.handles[handle].name][oid]

    async def find_all_files(self, pattern, flags=0):
        directory, _, mask = pattern.rpartition("\\")
        if not any(character in mask for character in "*?"):
            entry = self.files.get(pattern.lower())
            return [self._find_data(entry)] if entry else []
        mask = "*" if mask == "*.*" else mask
        entries = []
        for key, path in self.directories.items():
            parent, _, name = path.rpartition("\\")
            if parent.lower() == directory.lower() and fnmatch.fnmatch(name.lower(), mask.lower()):
                entries.append(FindData(name=name, attributes=FILE_ATTRIBUTE_DIRECTORY))
        for entry in self.files.values():
            parent, _, name = entry.path.rpartition("\\")
            if parent.lower() == directory.lower() and fnmatch.fnmatch(name.lower(), mask.lower()):
                entries.append(self._find_data(entry))
        return entries

    def _find_data(self, entry):
        return FindData(name=entry.path.rpartition("\\")[2], attributes=FILE_ATTRIBUTE_NORMAL,
                        last_write_time=entry.modified, size=len(entry.data))

    async def read_file_contents(self, path, progress=None):
        return self.file(path)

    async def write_file_contents(self, path, data, modified=None, progress=None):
        self.put_file(path, data, modified or self.tick())

    async def create_directory(self, path):
        if path.lower() in self.directories:
            raise RapiError(f"CeCreateDirectory {path}", 183)
        self.directories[path.lower()] = path

    async def get_file_attributes(self, path):
        if path.lower() in self.directories:
            return FILE_ATTRIBUTE_DIRECTORY
        if path.lower() in self.files:
            return FILE_ATTRIBUTE_NORMAL
        raise RapiError(f"CeGetFileAttributes {path}", 2)

    async def delete_file(self, path):
        if path.lower() not in self.files:
            raise RapiError(f"CeDeleteFile {path}", 2)
        del self.files[path.lower()]
