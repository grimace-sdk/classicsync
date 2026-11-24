import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..rapi.client import GENERIC_WRITE, RapiError
from ..rapi.structures import (
    FAF_ATTRIBUTES, FAF_LASTWRITE_TIME, FAF_NAME, FAF_SIZE_LOW, FILE_ATTRIBUTE_DIRECTORY, FILE_ATTRIBUTE_HIDDEN,
    FILE_ATTRIBUTE_INROM, FILE_ATTRIBUTE_NORMAL, FILE_ATTRIBUTE_READONLY, FILE_ATTRIBUTE_TEMPORARY,
)
from .compound import CompoundFileError, Storage, Stream, read_compound_file, write_compound_file
from .device import (
    NOTIFICATION_DATABASE_EVENT, create_database, default_language, delete_database, event_has_occurred,
    find_all_databases, get_memory_division, open_database_by_oid, read_device_file, read_raw_record, reg_copy_file, reg_restore_file,
    set_database_info, set_memory_division, write_device_file, write_raw_record,
)
from .format import (
    ACTIVESYNC_EXCLUDED_DATABASES, BACKUP_SET_INFORMATION, CEDB_VALIDMODTIME, DATABASE_INFO, DEFAULT_LANGUAGE,
    DIRECTORY_ATTRIBUTES, EXCLUDED_FILES, EXECUTABLE_EXTENSIONS, FILE_HEADER_SIZE, FILE_NAME_ESCAPES,
    HPC_EXPLORER_EXCLUDED_DATABASES, PEGASUS_DATABASES, PIM_DATABASES, RECORD_PREFIX, RECYCLE_FOLDER, REGISTRY_DEVICE_PATH,
    REGISTRY_FILE, RESERVED_NAMES, SHORTCUT_EXTENSIONS, VERSION_ACTIVESYNC, BackupFormatError, BackupSetInformation,
    DatabaseInfo, FileHeader, RecordBlock, database_element_name, database_name_from_element, datetime_to_systemtime,
    element_name_for, has_extension, pack_file_stream, record_stream_name, unescape_name, unpack_file_stream,
)

log = logging.getLogger("classicsync.backup")

HANDHELD_PC_PLATFORMS = ("HPC", "Jupiter")
EVENT_NOTIFICATIONS_DATABASE = "\\EventNotifications"
EVENT_RESTART_SHORTCUT = "\\Windows\\EventRst.Lnk"
EVENT_RESTART_STARTUP_SHORTCUT = "\\Windows\\StartUp\\EventRst.Lnk"
RESTART_SYNCHRONIZATION_MARKERS = ("\\Restart Synchronization Marker.1", "\\Restart Synchronization Marker.2")
MAX_DEVICE_PATH = 0x102
BACKUP_FIND_FLAGS = FAF_ATTRIBUTES | FAF_LASTWRITE_TIME | FAF_SIZE_LOW | FAF_NAME
RESTORE_FIND_FLAGS = FAF_ATTRIBUTES | FAF_NAME
ERROR_ALREADY_EXISTS = 183


class BackupError(Exception):
    pass


class BackupMismatchError(BackupError):
    def __init__(self, problems):
        self.problems = problems
        super().__init__("backup does not match this device: " + "; ".join(problems))


@dataclass
class DeviceIdentity:
    platform: str = ""
    oem_info: str = ""
    partnership_id: int = 0

    @classmethod
    def from_announcement(cls, announcement, partnership_id=0):
        info = getattr(announcement, "info", None)
        if info is None:
            return cls("HPC", "", partnership_id)
        return cls(info.platform, info.oem_info, partnership_id)

    @property
    def not_handheld_pc(self):
        return int(bool(self.platform) and self.platform not in HANDHELD_PC_PLATFORMS)


@dataclass
class BackupProgress:
    phase: str
    item: str = ""
    done: int = 0
    total: int = 0


@dataclass
class BackupResult:
    path: Path
    incremental: bool = False
    files: int = 0
    folders: int = 0
    databases: int = 0
    records: int = 0
    unchanged: int = 0
    removed: int = 0
    bytes: int = 0
    skipped: list = field(default_factory=list)


@dataclass
class RestoreResult:
    path: Path
    data_only: bool = False
    files: int = 0
    folders: int = 0
    databases: int = 0
    records: int = 0
    deleted: list = field(default_factory=list)
    registry_restored: bool = False
    skipped: list = field(default_factory=list)

    @property
    def reset_required(self):
        return self.registry_restored


@dataclass
class BackupEntry:
    path: str
    kind: str
    size: int = 0
    attributes: int = 0
    modified: int = 0


@dataclass
class BackupDatabase:
    name: str
    database_type: int
    records: int
    sort_orders: list
    modified: int


@dataclass
class BackupContents:
    information: BackupSetInformation
    entries: list
    databases: list
    registry_size: int = 0

    @property
    def files(self):
        return [entry for entry in self.entries if entry.kind == "file"]

    @property
    def folders(self):
        return [entry for entry in self.entries if entry.kind == "folder"]


class Reporter:
    def __init__(self, progress, total):
        self.progress = progress
        self.total = max(total, 1)
        self.done = 0

    def __call__(self, phase, item="", add=0):
        self.done += add
        if self.progress:
            self.progress(BackupProgress(phase, item, min(self.done, self.total), self.total))


def join_device_path(directory, name):
    return f"{directory}\\{name}"


def name_matches(name, names):
    folded = name.casefold()
    return any(folded == candidate.casefold() for candidate in names)


def stream_header(stream):
    try:
        return FileHeader.unpack(stream.data)
    except BackupFormatError:
        return None


def full_name_of(entry):
    if isinstance(entry, Storage):
        attributes = entry.stream(DIRECTORY_ATTRIBUTES)
        header = stream_header(attributes) if attributes else None
    else:
        header = stream_header(entry)
    return header.name if header else None


def device_name_of(entry):
    return full_name_of(entry) or unescape_name(entry.name, FILE_NAME_ESCAPES)


def read_backup_set_information(root):
    stream = root.stream(BACKUP_SET_INFORMATION)
    if stream is None:
        raise BackupFormatError(f"no {BACKUP_SET_INFORMATION} stream")
    return BackupSetInformation.unpack(stream.data)


def open_backup(path):
    try:
        root = read_compound_file(path)
    except CompoundFileError as error:
        raise BackupError(f"{path} is not a valid backup file: {error}") from error
    try:
        information = read_backup_set_information(root)
    except BackupFormatError as error:
        raise BackupError(f"{path} is not a valid backup file: {error}") from error
    return root, information


def write_backup_file(root, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".partial", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(write_compound_file(root))
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


async def describe_device(client):
    version = await client.get_version()
    system = await client.get_system_info()
    language = await default_language(client, DEFAULT_LANGUAGE)
    return version, system, language


def excluded_databases_for(file_version):
    return ACTIVESYNC_EXCLUDED_DATABASES if file_version >= VERSION_ACTIVESYNC else HPC_EXPLORER_EXCLUDED_DATABASES


async def read_backup_set_from_device(client, identity, file_version):
    version, system, language = await describe_device(client)
    store = await client.get_store_information()
    try:
        division = await get_memory_division(client)
    except RapiError:
        division = None
    store_pages = division.store_pages if division else 0
    page_size = division.page_size if division else system.page_size
    store_used = store_pages * page_size - store.free_size if division else store.store_size - store.free_size
    os_version = (version.major << 16) | version.minor if file_version >= VERSION_ACTIVESYNC else version.build
    return BackupSetInformation(
        partnership_id=identity.partnership_id,
        processor_type=system.processor_type,
        store_pages=store_pages,
        ram_pages=division.ram_pages if division else 0,
        page_size=page_size,
        store_used=max(store_used, 0),
        backup_time=datetime_to_systemtime(datetime.now()),
        version=file_version,
        os_version=os_version,
        language=language,
        not_handheld_pc=identity.not_handheld_pc,
        processor_level=system.processor_level,
        processor_revision=system.processor_revision,
        oem_info=identity.oem_info,
    )


def can_update_incrementally(previous, current):
    return (previous.version == current.version and previous.partnership_id == current.partnership_id
            and previous.language == current.language and previous.not_handheld_pc == current.not_handheld_pc)


class FileBackup:
    def __init__(self, client, incremental, reporter, result):
        self.client = client
        self.incremental = incremental
        self.report = reporter
        self.result = result

    async def backup_directory(self, device_directory, storage):
        listing = await self.client.find_all_files(join_device_path(device_directory, "*"), BACKUP_FIND_FLAGS)
        present = set()
        for entry in listing:
            device_path = join_device_path(device_directory, entry.name)
            if len(device_path) > MAX_DEVICE_PATH:
                self.result.skipped.append((device_path, "path too long"))
                continue
            element = element_name_for(entry.name, storage, entry.is_directory, full_name_of)
            present.add(element.upper())
            if entry.is_directory:
                await self.backup_folder(device_directory, device_path, entry, element, storage)
            else:
                await self.backup_file(device_path, entry, element, storage)
        if self.incremental:
            self.remove_missing(storage, present)

    async def backup_folder(self, device_directory, device_path, entry, element, storage):
        if entry.attributes & FILE_ATTRIBUTE_TEMPORARY:
            return
        if device_directory == "" and entry.name == RECYCLE_FOLDER:
            return
        folder = storage.storage(element) if self.incremental else None
        if folder is None:
            folder = storage.create_storage(element)
            folder.set_stream(DIRECTORY_ATTRIBUTES, FileHeader(entry.last_write_time, entry.attributes, entry.name).pack())
        self.result.folders += 1
        await self.backup_directory(device_path, folder)

    async def backup_file(self, device_path, entry, element, storage):
        if entry.attributes & FILE_ATTRIBUTE_INROM or name_matches(entry.name, EXCLUDED_FILES):
            return
        existing = storage.stream(element) if self.incremental else None
        if existing is not None:
            header = stream_header(existing)
            if header is not None and header.modified == entry.last_write_time:
                self.result.unchanged += 1
                self.report("files", device_path, entry.size)
                return
        self.report("files", device_path)
        try:
            contents = await read_device_file(self.client, device_path)
        except RapiError as error:
            log.warning("could not back up %s: %s", device_path, error)
            self.result.skipped.append((device_path, str(error)))
            return
        header = FileHeader(entry.last_write_time, entry.attributes, entry.name)
        storage.set_stream(element, pack_file_stream(header, contents))
        self.result.files += 1
        self.result.bytes += len(contents)
        self.report("files", device_path, len(contents))

    def remove_missing(self, storage, present):
        for entry in list(storage):
            name = entry.name.upper()
            if name in present or name in RESERVED_NAMES or name == REGISTRY_FILE.upper():
                continue
            storage.remove(entry.name)
            self.result.removed += 1


async def read_database_records(client, database):
    handle = await open_database_by_oid(client, database.oid)
    records = []
    try:
        while True:
            record = await read_raw_record(client, handle)
            if record is None:
                return records
            records.append(record)
    finally:
        await client.close_handle(handle)


async def backup_databases(client, root, incremental, excluded, reporter, result):
    storage = root.storage(PEGASUS_DATABASES) if incremental else None
    if storage is None:
        storage = root.create_storage(PEGASUS_DATABASES)
    present = set()
    for database in await find_all_databases(client):
        info = database.info
        element = database_element_name(info.name)
        present.add(element.upper())
        if name_matches(info.name, excluded):
            continue
        existing = storage.storage(element) if incremental else None
        if existing is not None and existing.stream(DATABASE_INFO) is not None:
            try:
                previous = DatabaseInfo.unpack(existing.stream(DATABASE_INFO).data)
            except BackupFormatError:
                previous = None
            if previous is not None and previous.modified == info.modified:
                result.unchanged += 1
                reporter("databases", info.name, info.size)
                continue
        reporter("databases", info.name)
        try:
            records = await read_database_records(client, database)
        except RapiError as error:
            log.warning("could not back up database %s: %s", info.name, error)
            result.skipped.append((info.name, str(error)))
            continue
        folder = Storage(element)
        folder.set_stream(DATABASE_INFO, info.pack())
        for oid, property_count, block in records:
            folder.set_stream(record_stream_name(oid), RecordBlock(property_count, block).pack())
        storage.add(folder)
        result.databases += 1
        result.records += len(records)
        reporter("databases", info.name, info.size)
    if incremental:
        for entry in list(storage):
            if entry.name.upper() not in present:
                storage.remove(entry.name)
                result.removed += 1


async def backup(client, path, full=True, progress=None, identity=None, file_version=VERSION_ACTIVESYNC):
    path = Path(path)
    identity = identity or DeviceIdentity()
    information = await read_backup_set_from_device(client, identity, file_version)
    root = None
    incremental = False
    if not full and path.exists():
        try:
            previous_root, previous = open_backup(path)
            if can_update_incrementally(previous, information):
                root, incremental = previous_root, True
            else:
                log.info("existing backup %s is from another device or format; making a full backup", path)
        except BackupError as error:
            log.warning("%s; making a full backup", error)
    if root is None:
        root = Storage()
    result = BackupResult(path, incremental)
    reporter = Reporter(progress, information.store_used)
    reporter("registry", REGISTRY_DEVICE_PATH)
    try:
        await reg_copy_file(client, REGISTRY_DEVICE_PATH)
    except RapiError as error:
        raise BackupError(f"could not copy the device registry: {error}") from error
    try:
        root.set_stream(BACKUP_SET_INFORMATION, information.pack())
        await FileBackup(client, incremental, reporter, result).backup_directory("", root)
        await backup_databases(client, root, incremental, excluded_databases_for(file_version), reporter, result)
    finally:
        try:
            await client.delete_file(REGISTRY_DEVICE_PATH)
        except RapiError:
            pass
    reporter("writing", str(path))
    write_backup_file(root, path)
    reporter("done", str(path))
    return result


def compatibility_problems(information, version, system, language, identity):
    problems = []
    data_only = False
    if identity.platform and information.not_handheld_pc != identity.not_handheld_pc:
        problems.append("device type differs")
    if information.language != language:
        problems.append(f"language {information.language:#06x} differs from the device's {language:#06x}")
    if information.processor_type != system.processor_type:
        problems.append(f"processor type {information.processor_type} differs from the device's {system.processor_type}")
    elif ((information.processor_level and information.processor_level != system.processor_level)
          or (information.processor_revision and information.processor_revision != system.processor_revision)):
        problems.append("processor level or revision differs")
    if information.version >= VERSION_ACTIVESYNC:
        if information.os_major != version.major or version.minor < information.os_minor:
            problems.append(f"backup is from Windows CE {information.os_major}.{information.os_minor:02d}, "
                            f"device runs {version.major}.{version.minor:02d}")
        elif version.minor != information.os_minor:
            data_only = True
    if information.oem_info and identity.oem_info and information.oem_info != identity.oem_info:
        problems.append(f"backup is from {information.oem_info!r}, device is {identity.oem_info!r}")
    return problems, data_only


class FileRestore:
    def __init__(self, client, data_only, reporter, result):
        self.client = client
        self.data_only = data_only
        self.report = reporter
        self.result = result
        self.shortcuts = []

    def skipped_in_data_only(self, device_directory, name):
        if not has_extension(name, EXECUTABLE_EXTENSIONS):
            return False
        return not (device_directory.casefold() == "\\windows" and name.casefold() == REGISTRY_FILE.casefold())

    async def restore_directory(self, device_directory, storage):
        listing = await self.client.find_all_files(join_device_path(device_directory, "*"), RESTORE_FIND_FLAGS)
        remaining = {}
        for entry in listing:
            if entry.is_directory and entry.attributes & FILE_ATTRIBUTE_TEMPORARY:
                continue
            remaining[entry.name.upper()] = entry
        for element in storage:
            if element.name.upper() in RESERVED_NAMES:
                continue
            name = device_name_of(element)
            device_path = join_device_path(device_directory, name)
            is_folder = isinstance(element, Storage)
            if self.data_only and not is_folder and self.skipped_in_data_only(device_directory, name):
                continue
            existing = remaining.pop(name.upper(), None)
            if self.data_only and existing is not None and not existing.is_directory:
                continue
            if is_folder:
                await self.restore_folder(device_path, element)
            else:
                await self.restore_file(device_path, element)
                if self.data_only and has_extension(name, SHORTCUT_EXTENSIONS):
                    self.shortcuts.append(device_path)
        if not self.data_only:
            for entry in remaining.values():
                await self.remove_device_entry(join_device_path(device_directory, entry.name), entry)

    async def restore_folder(self, device_path, storage):
        try:
            await self.client.create_directory(device_path)
        except RapiError as error:
            if error.code != ERROR_ALREADY_EXISTS:
                try:
                    await self.client.get_file_attributes(device_path)
                except RapiError:
                    self.result.skipped.append((device_path, str(error)))
                    return
        self.result.folders += 1
        await self.restore_directory(device_path, storage)

    async def restore_file(self, device_path, stream):
        try:
            header, contents = unpack_file_stream(stream.data)
        except BackupFormatError as error:
            self.result.skipped.append((device_path, str(error)))
            return
        self.report("files", device_path)
        try:
            await write_device_file(self.client, device_path, contents, header.attributes, header.modified)
        except RapiError as error:
            log.warning("could not restore %s: %s", device_path, error)
            self.result.skipped.append((device_path, str(error)))
            return
        self.result.files += 1
        self.report("files", device_path, len(contents))

    async def remove_device_entry(self, device_path, entry):
        if entry.attributes & FILE_ATTRIBUTE_INROM or name_matches(entry.name, EXCLUDED_FILES):
            return
        self.report("removing", device_path)
        try:
            if entry.is_directory:
                for child in await self.client.find_all_files(join_device_path(device_path, "*"), RESTORE_FIND_FLAGS):
                    await self.remove_device_entry(join_device_path(device_path, child.name), child)
                if device_path.casefold() == f"\\{RECYCLE_FOLDER}".casefold():
                    return
                await self.client.remove_directory(device_path)
            else:
                if entry.attributes & FILE_ATTRIBUTE_READONLY:
                    await self.client.set_file_attributes(device_path, FILE_ATTRIBUTE_NORMAL)
                await self.client.delete_file(device_path)
            self.result.deleted.append(device_path)
        except RapiError as error:
            log.warning("could not remove %s: %s", device_path, error)
            self.result.skipped.append((device_path, str(error)))

    async def verify_shortcuts(self):
        for shortcut in self.shortcuts:
            self.report("shortcuts", shortcut)
            try:
                text = (await read_device_file(self.client, shortcut)).decode("latin-1")
            except RapiError:
                continue
            target = shortcut_target(text)
            if target and not await self.client.find_all_files(target, FAF_NAME):
                try:
                    await self.client.delete_file(shortcut)
                    self.result.deleted.append(shortcut)
                except RapiError:
                    pass


def shortcut_target(text):
    _, _, command = text.partition("#")
    command = command.strip().strip("\0")
    if command.startswith('"'):
        return command[1:].partition('"')[0]
    return command.partition(" ")[0]


def database_records(folder):
    records = []
    for entry in folder:
        if isinstance(entry, Stream) and entry.name.upper() != DATABASE_INFO.upper():
            records.append(RecordBlock.unpack(entry.data))
    return records


async def restore_databases(client, root, data_only, reporter, result):
    storage = root.storage(PEGASUS_DATABASES)
    excluded = list(ACTIVESYNC_EXCLUDED_DATABASES) + (list(PIM_DATABASES) if data_only else [])
    device_databases = await find_all_databases(client)
    for database in device_databases:
        database.pending_delete = not name_matches(database.info.name, excluded)
    for folder in storage or []:
        if not isinstance(folder, Storage) or folder.stream(DATABASE_INFO) is None:
            continue
        name = database_name_from_element(folder.name)
        if name_matches(name, excluded):
            continue
        try:
            info = DatabaseInfo.unpack(folder.stream(DATABASE_INFO).data)
            records = database_records(folder)
        except BackupFormatError as error:
            result.skipped.append((name, str(error)))
            continue
        reporter("databases", info.name)
        if name.casefold() == EVENT_NOTIFICATIONS_DATABASE.casefold():
            await event_has_occurred(client, NOTIFICATION_DATABASE_EVENT)
        for database in device_databases:
            if database.pending_delete and database.info.name.casefold() == name.casefold():
                await delete_database_quietly(client, database, result, replaced=True)
                database.pending_delete = False
                break
        try:
            await restore_database(client, info, records)
        except RapiError as error:
            log.warning("could not restore database %s: %s", info.name, error)
            result.skipped.append((info.name, str(error)))
            continue
        result.databases += 1
        result.records += len(records)
        reporter("databases", info.name, sum(len(record.block) for record in records))
        if name.casefold() == EVENT_NOTIFICATIONS_DATABASE.casefold():
            try:
                await client.copy_file(EVENT_RESTART_SHORTCUT, EVENT_RESTART_STARTUP_SHORTCUT)
            except RapiError:
                pass
    for database in device_databases:
        if database.pending_delete:
            reporter("removing", database.info.name)
            await delete_database_quietly(client, database, result)


async def delete_database_quietly(client, database, result, replaced=False):
    try:
        await delete_database(client, database.oid, database.info.name)
        if not replaced:
            result.deleted.append(database.info.name)
    except RapiError as error:
        log.warning("could not delete database %s: %s", database.info.name, error)
        result.skipped.append((database.info.name, str(error)))


async def restore_database(client, info, records):
    oid = await create_database(client, info)
    handle = await open_database_by_oid(client, oid)
    try:
        for record in records:
            await write_raw_record(client, handle, record.property_count, record.block)
    finally:
        await client.close_handle(handle)
    restored = DatabaseInfo(info.name, info.database_type, CEDB_VALIDMODTIME, info.record_count, info.sort_count,
                            info.size, info.modified, info.sort_orders)
    try:
        await set_database_info(client, oid, restored)
    except RapiError as error:
        log.info("could not restore the modification time of %s: %s", info.name, error)


async def prepare_memory(client, information):
    try:
        division = await get_memory_division(client)
    except RapiError:
        return
    if information.store_pages and information.store_pages != division.store_pages:
        if await set_memory_division(client, information.store_pages):
            division = await get_memory_division(client)
    if division.store_pages and information.store_used > division.store_pages * division.page_size:
        raise BackupError(f"the backup needs {information.store_used} bytes of storage memory; "
                          f"the device has {division.store_pages * division.page_size}")


async def create_restart_markers(client):
    for marker in RESTART_SYNCHRONIZATION_MARKERS:
        try:
            handle = await client.create_file(marker, GENERIC_WRITE, 0, 2, FILE_ATTRIBUTE_HIDDEN)
            await client.close_handle(handle)
        except RapiError:
            pass


async def restore(client, path, progress=None, identity=None, data_only=None, allow_mismatch=False,
                  restart_markers=True):
    path = Path(path)
    identity = identity or DeviceIdentity()
    root, information = open_backup(path)
    version, system, language = await describe_device(client)
    problems, version_data_only = compatibility_problems(information, version, system, language, identity)
    if problems and not allow_mismatch:
        raise BackupMismatchError(problems)
    if data_only is None:
        data_only = version_data_only or bool(problems)
    result = RestoreResult(path, data_only)
    reporter = Reporter(progress, information.store_used)
    await prepare_memory(client, information)
    if identity.not_handheld_pc:
        try:
            await client.kill_all_apps()
        except RapiError:
            pass
    files = FileRestore(client, data_only, reporter, result)
    await files.restore_directory("", root)
    if not data_only and has_registry(root):
        reporter("registry", REGISTRY_DEVICE_PATH)
        try:
            await reg_restore_file(client, REGISTRY_DEVICE_PATH)
            result.registry_restored = True
        except RapiError as error:
            raise BackupError(f"could not restore the device registry: {error}") from error
    await restore_databases(client, root, data_only, reporter, result)
    if data_only:
        try:
            await client.delete_file(REGISTRY_DEVICE_PATH)
        except RapiError:
            pass
        await files.verify_shortcuts()
    if restart_markers:
        await create_restart_markers(client)
    reporter("done", str(path))
    return result


def has_registry(root):
    windows = root.storage("Windows")
    return windows is not None and windows.stream(REGISTRY_FILE) is not None


def collect_entries(storage, device_directory, entries):
    for element in storage:
        if element.name.upper() in RESERVED_NAMES:
            continue
        name = device_name_of(element)
        device_path = join_device_path(device_directory, name)
        if isinstance(element, Storage):
            attributes = element.stream(DIRECTORY_ATTRIBUTES)
            header = stream_header(attributes) if attributes else None
            entries.append(BackupEntry(device_path, "folder", 0, header.attributes if header else FILE_ATTRIBUTE_DIRECTORY,
                                       header.modified if header else 0))
            collect_entries(element, device_path, entries)
        else:
            header = stream_header(element)
            size = len(element.data) - header.size if header else max(len(element.data) - FILE_HEADER_SIZE, 0)
            entries.append(BackupEntry(device_path, "file", size, header.attributes if header else 0,
                                       header.modified if header else 0))


def inspect(path):
    root, information = open_backup(path)
    entries = []
    collect_entries(root, "", entries)
    databases = []
    for folder in root.storage(PEGASUS_DATABASES) or []:
        if not isinstance(folder, Storage) or folder.stream(DATABASE_INFO) is None:
            continue
        info = DatabaseInfo.unpack(folder.stream(DATABASE_INFO).data)
        record_count = sum(1 for entry in folder if entry.name.upper().startswith(RECORD_PREFIX.upper()))
        databases.append(BackupDatabase(info.name or database_name_from_element(folder.name), info.database_type,
                                        record_count, info.sort_orders, info.modified))
    registry = next((entry for entry in entries if entry.path.casefold() == REGISTRY_DEVICE_PATH.casefold()), None)
    return BackupContents(information, entries, databases, registry.size if registry else 0)
