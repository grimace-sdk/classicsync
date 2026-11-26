from dataclasses import dataclass, field
from pathlib import Path

from ..formats.pdb import PdbError, read_pdb
from .dlp import DB_ATTRIBUTE_BACKUP

NAME_LIMIT = 31
DB_ATTRIBUTE_RESET_AFTER_INSTALL = 0x0020
RECORD_DELETED = 0x80
RECORD_FLAGS_MASK = 0xF0
CATEGORY_MASK = 0x0F
INSTALLABLE_EXTENSIONS = {".prc", ".pdb", ".pqa"}


class InstallError(ValueError):
    pass


@dataclass
class InstallResult:
    installed: list = field(default_factory=list)
    replaced: list = field(default_factory=list)
    reset_needed: bool = False


def load_installable(path):
    path = Path(path)
    if path.suffix.lower() not in INSTALLABLE_EXTENSIONS:
        raise InstallError(f"{path.name}: not a .prc, .pdb or .pqa file")
    try:
        database = read_pdb(path.read_bytes())
    except PdbError as error:
        raise InstallError(f"{path.name}: {error}") from error
    if not database.type.strip("\0") or not database.creator.strip("\0"):
        raise InstallError(f"{path.name}: missing type or creator")
    if not 1 <= len(database.name) <= NAME_LIMIT:
        raise InstallError(f"{path.name}: database name must be 1 to {NAME_LIMIT} characters")
    return database


async def install_database(client, database):
    replaced = await client.delete_database(database.name)
    attributes = database.attributes
    if database.creator != database.creator.lower():
        attributes |= DB_ATTRIBUTE_BACKUP
    handle = await client.create_database(database.name, database.creator, database.type, attributes, database.version)
    try:
        if database.is_resource:
            for resource in database.resources:
                await client.write_resource(handle, resource.type, resource.id, resource.data)
        else:
            if database.app_info:
                await client.write_app_block(handle, database.app_info)
            if database.sort_info:
                await client.write_sort_block(handle, database.sort_info)
            for record in database.records:
                if record.attributes & RECORD_DELETED:
                    continue
                await client.write_record(handle, record.unique_id, record.attributes & RECORD_FLAGS_MASK,
                                          record.attributes & CATEGORY_MASK, record.data)
    finally:
        await client.close_database(handle, update_backup_date=True)
    return replaced


def load_installables(paths):
    return [(Path(path).name, load_installable(path)) for path in paths]


async def install_files(client, databases, progress=None):
    result = InstallResult()
    for file_name, database in databases:
        if progress:
            progress(file_name)
        if await install_database(client, database):
            result.replaced.append(file_name)
        result.installed.append(file_name)
        result.reset_needed |= bool(database.attributes & DB_ATTRIBUTE_RESET_AFTER_INSTALL)
    return result
