import sys

from . import cli
from .backup import VERSION_ACTIVESYNC, VERSION_HPC_EXPLORER, BackupError, DeviceIdentity, backup, inspect, restore
from .rapi.structures import FILE_ATTRIBUTE_DIRECTORY, PROCESSOR_NAMES, filetime_to_datetime


def print_progress(update):
    if not sys.stderr.isatty() or not update.item:
        return
    percent = update.done * 100 // max(update.total, 1)
    print(f"\r{percent:3d}% {update.phase}: {update.item[-60:]:<60}", end="", file=sys.stderr, flush=True)


def finish_progress():
    if sys.stderr.isatty():
        print(file=sys.stderr)


def print_skipped(skipped):
    for item, reason in skipped:
        print(f"  skipped {item}: {reason}", file=sys.stderr)


async def command_backup(arguments):
    version = VERSION_HPC_EXPLORER if arguments.hpc_explorer else VERSION_ACTIVESYNC
    async with cli.rapi_session(arguments) as client:
        try:
            result = await backup(client, arguments.file, full=not arguments.incremental, progress=print_progress,
                                  identity=DeviceIdentity(arguments.platform or ""), file_version=version)
        except BackupError as error:
            raise ValueError(str(error)) from error
        finally:
            finish_progress()
    kind = "incremental" if result.incremental else "full"
    print(f"{kind} backup to {result.path}: {result.files} files ({result.bytes} bytes), {result.folders} folders, "
          f"{result.databases} databases ({result.records} records), {result.unchanged} unchanged, {result.removed} removed")
    print_skipped(result.skipped)


async def command_restore(arguments):
    async with cli.rapi_session(arguments) as client:
        try:
            result = await restore(client, arguments.file, progress=print_progress,
                                   identity=DeviceIdentity(arguments.platform or ""),
                                   data_only=True if arguments.data_only else None, allow_mismatch=arguments.force)
        except BackupError as error:
            raise ValueError(str(error)) from error
        finally:
            finish_progress()
    mode = "data files only" if result.data_only else "full"
    print(f"{mode} restore from {result.path}: {result.files} files, {result.folders} folders, "
          f"{result.databases} databases ({result.records} records), {len(result.deleted)} items removed")
    print_skipped(result.skipped)
    if result.reset_required:
        print("Disconnect and reset the device for the restored registry to take effect.")


def format_time(filetime):
    moment = filetime_to_datetime(filetime)
    return moment.strftime("%Y-%m-%d %H:%M:%S") if moment else "-"


async def command_backup_info(arguments):
    try:
        contents = inspect(arguments.file)
    except BackupError as error:
        raise ValueError(str(error)) from error
    information = contents.information
    created = information.created
    print(f"Backup set version {information.version}"
          f" ({'ActiveSync 3.x / CE Services 2.2' if information.version >= VERSION_ACTIVESYNC else 'H/PC Explorer 1.x'})")
    print(f"Created: {created.strftime('%Y-%m-%d %H:%M:%S') if created else 'unknown'} (desktop local time)")
    if information.os_major is not None:
        print(f"Windows CE {information.os_major}.{information.os_minor:02d}")
    else:
        print(f"Windows CE build {information.os_build}")
    processor = PROCESSOR_NAMES.get(information.processor_type, f"type {information.processor_type}")
    print(f"Processor: {processor} (level {information.processor_level}, revision {information.processor_revision})")
    print(f"Language: {information.language:#06x}; {'not a Handheld PC' if information.not_handheld_pc else 'Handheld PC'}"
          + (f"; OEM: {information.oem_info}" if information.oem_info else ""))
    print(f"Storage memory: {information.store_pages} pages of {information.page_size} bytes, {information.store_used} bytes used;"
          f" partnership {information.partnership_id:#x}")
    print(f"Registry: {contents.registry_size} bytes" if contents.registry_size else "Registry: not present")
    total = sum(entry.size for entry in contents.files)
    print(f"Files: {len(contents.files)} ({total} bytes) in {len(contents.folders)} folders")
    if arguments.files:
        for entry in contents.entries:
            marker = "\\" if entry.attributes & FILE_ATTRIBUTE_DIRECTORY else ""
            print(f"  {format_time(entry.modified)}  {entry.size:>9}  {entry.path}{marker}")
    print(f"Databases: {len(contents.databases)}")
    for database in contents.databases:
        print(f"  {database.name:<32} type {database.database_type:#010x}  {database.records:>5} records  "
              f"{len(database.sort_orders)} sort orders  modified {format_time(database.modified)}")


def add_commands(subparsers, device_command):
    backup_command = device_command("backup", command_backup, "back up the device to an ActiveSync-compatible .stg file")
    backup_command.add_argument("file")
    backup_command.add_argument("--incremental", action="store_true", help="update an existing backup file with what changed")
    backup_command.add_argument("--hpc-explorer", action="store_true", help="write a file H/PC Explorer 1.x can restore")
    backup_command.add_argument("--platform", help="device platform reported on connect (HPC, Jupiter, Palm PC, PocketPC)")
    restore_command = device_command("restore", command_restore, "restore the device from a .stg backup file")
    restore_command.add_argument("file")
    restore_command.add_argument("--data-only", action="store_true", help="restore data files and databases only")
    restore_command.add_argument("--force", action="store_true", help="restore data even if the backup is from another device")
    restore_command.add_argument("--platform", help="device platform reported on connect (HPC, Jupiter, Palm PC, PocketPC)")
    info = subparsers.add_parser("backup-info", help="list what a .stg backup file contains")
    info.add_argument("file")
    info.add_argument("--files", action="store_true", help="list every file and folder")
    info.set_defaults(handler=command_backup_info)
