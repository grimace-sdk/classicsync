from dataclasses import dataclass, field
from pathlib import Path

from ..formats.pdb import PalmDatabase, PdbError, PdbRecord, PdbResource, palm_seconds, read_pdb, write_pdb
from .dlp import DB_ATTRIBUTE_BACKUP, DB_ATTRIBUTE_READ_ONLY, DlpError, DlpStatus

UNSAFE_CHARACTERS = ' *+,./:;<=>?[]|\\^"'
ALWAYS_BACKED_UP = {"AddressDB", "DatebookDB", "ExpenseDB", "MailDB", "MemoDB", "ToDoDB"}
RECORD_FLAGS_MASK = 0xF0
CATEGORY_MASK = 0x0F


@dataclass
class BackupResult:
    written: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


def backup_file_name(database):
    name = "".join("_" if character in UNSAFE_CHARACTERS else character for character in database.name)
    return name + (".PRC" if database.is_resource else ".PDB")


def wants_backup(database):
    if database.attributes & DB_ATTRIBUTE_READ_ONLY or not database.in_ram:
        return False
    if database.name in ALWAYS_BACKED_UP or database.attributes & DB_ATTRIBUTE_BACKUP:
        return True
    return database.creator != database.creator.lower()


def is_unchanged(path, database):
    try:
        stored = read_pdb(path.read_bytes())
    except (OSError, PdbError):
        return False
    return (database.backed_up is not None and stored.name == database.name and stored.creator == database.creator
            and palm_seconds(stored.created) == palm_seconds(database.created)
            and palm_seconds(stored.modified) == palm_seconds(database.modified))


async def read_database(client, info):
    database = PalmDatabase(info.name, info.type, info.creator, info.attributes, info.version, info.created, info.modified,
                            info.backed_up, info.modification_number)
    handle = await client.open_database(info.name)
    try:
        count = await client.record_count(handle)
        if info.is_resource:
            for index in range(count):
                kind, resource_id, data = await client.read_resource_by_index(handle, index)
                database.resources.append(PdbResource(kind, resource_id, data))
        else:
            database.app_info = await client.read_app_block(handle)
            database.sort_info = await client.read_sort_block(handle)
            for index in range(count):
                try:
                    record_id, attributes, category, data = await client.read_record_by_index(handle, index)
                except DlpError as error:
                    if error.status in (DlpStatus.RECORD_DELETED, DlpStatus.NOT_FOUND):
                        continue
                    raise
                flags = (attributes & RECORD_FLAGS_MASK) | (category & CATEGORY_MASK)
                database.records.append(PdbRecord(data, flags, record_id))
    finally:
        await client.close_database(handle, update_backup_date=True)
    return database


async def backup_handheld(client, folder, everything=False, progress=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    result = BackupResult()
    for info in await client.read_database_list(ram=True):
        if not everything and not wants_backup(info):
            result.skipped.append(info.name)
            continue
        path = folder / backup_file_name(info)
        if is_unchanged(path, info):
            result.unchanged.append(path.name)
            continue
        if progress:
            progress(info.name)
        database = await read_database(client, info)
        path.write_bytes(write_pdb(database))
        result.written.append((path.name, len(database.resources if database.is_resource else database.records)))
    return result
