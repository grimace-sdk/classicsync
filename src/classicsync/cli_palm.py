from .i18n import _
from .palm import palm_usb_session
from .palm.backup import backup_handheld

DEFAULT_WAIT = 60.0


def describe_user(user):
    if not user.synced:
        return _("none (this handheld has never been synchronized)")
    last = user.last_sync.strftime("%Y-%m-%d %H:%M") if user.last_sync else _("never")
    return _("{name} (ID {user_id:#x}, last synchronized {last})").format(name=user.name, user_id=user.user_id, last=last)


def describe_database(database):
    flags = [_("resource") if database.is_resource else _("records")]
    if not database.in_ram:
        flags.append("ROM")
    modified = database.modified.strftime("%Y-%m-%d") if database.modified else "-"
    return f"  {database.name:<32} {database.type} {database.creator}  {modified}  {', '.join(flags)}"


async def command_palm_info(arguments):
    print(_("Waiting for a Palm handheld: press the HotSync button on the cradle."))
    async with palm_usb_session(arguments.wait) as client:
        system = await client.read_sys_info()
        user = await client.read_user_info()
        databases = await client.read_database_list(ram=True, rom=arguments.rom)
        await client.end_of_sync()
    print(_("Palm OS {version}, desktop link protocol {major}.{minor}").format(
        version=system.os_version, major=system.dlp_version[0], minor=system.dlp_version[1]))
    print(_("User: {user}").format(user=describe_user(user)))
    print(_("{count} databases:").format(count=len(databases)))
    for database in sorted(databases, key=lambda database: database.name.lower()):
        print(describe_database(database))


async def command_palm_backup(arguments):
    print(_("Waiting for a Palm handheld: press the HotSync button on the cradle."))
    async with palm_usb_session(arguments.wait) as client:
        result = await backup_handheld(client, arguments.folder, everything=arguments.all,
                                       progress=lambda name: print(_("  reading {name}").format(name=name)))
        await client.end_of_sync()
    for name, count in result.written:
        print(_("backed up {name} ({count} entries)").format(name=name, count=count))
    print(_("{written} written, {unchanged} unchanged, {skipped} not backed up").format(
        written=len(result.written), unchanged=len(result.unchanged), skipped=len(result.skipped)))


def add_commands(subparsers):
    palm = subparsers.add_parser("palm", help=_("talk to a Palm OS handheld over HotSync"))
    palm_commands = palm.add_subparsers(dest="palm_command", required=True)
    info = palm_commands.add_parser("info", help=_("show the handheld's OS, HotSync user and databases"))
    info.add_argument("--wait", type=float, default=DEFAULT_WAIT, help=_("seconds to wait for the handheld"))
    info.add_argument("--rom", action="store_true", help=_("include databases in ROM"))
    info.set_defaults(handler=command_palm_info)
    backup = palm_commands.add_parser("backup", help=_("copy the handheld's databases to .pdb and .prc files"))
    backup.add_argument("folder")
    backup.add_argument("--all", action="store_true", help=_("include databases HotSync would leave out"))
    backup.add_argument("--wait", type=float, default=DEFAULT_WAIT, help=_("seconds to wait for the handheld"))
    backup.set_defaults(handler=command_palm_backup)
