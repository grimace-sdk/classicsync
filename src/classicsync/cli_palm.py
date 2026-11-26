from .cli_sync import print_progress
from .gui.settings import Settings
from .i18n import _
from .palm import palm_usb_session
from .palm.backup import backup_handheld
from .palm.install import InstallError, install_files, load_installables
from .palm.sync import create_palm_partnership, find_palm_partnership, synchronize_handheld
from .palm.users import new_identifier, set_user
from .sync import FIRST_SYNC_CHOICES, FIRST_SYNC_COMBINE

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


def pc_identifier():
    settings = Settings.load()
    if not settings.palm_pc_id:
        settings.palm_pc_id = new_identifier()
        settings.save()
    return settings.palm_pc_id


async def command_palm_install(arguments):
    try:
        databases = load_installables(arguments.files)
    except InstallError as error:
        raise ValueError(str(error)) from error
    print(_("Waiting for a Palm handheld: press the HotSync button on the cradle."))
    async with palm_usb_session(arguments.wait) as client:
        result = await install_files(client, databases, progress=lambda name: print(_("  installing {name}").format(name=name)))
        if result.reset_needed:
            await client.reset_system()
        await client.end_of_sync()
    for name in result.installed:
        print((_("replaced {name}") if name in result.replaced else _("installed {name}")).format(name=name))
    if result.reset_needed:
        print(_("The handheld will restart to finish installing."))


async def command_palm_user(arguments):
    print(_("Waiting for a Palm handheld: press the HotSync button on the cradle."))
    async with palm_usb_session(arguments.wait) as client:
        user_id = await set_user(client, arguments.name, pc_identifier())
        await client.end_of_sync()
    print(_("HotSync user set to {name} (ID {user_id:#x})").format(name=arguments.name, user_id=user_id))


async def command_palm_sync(arguments):
    print(_("Waiting for a Palm handheld: press the HotSync button on the cradle."))
    async with palm_usb_session(arguments.wait) as client:
        user = await client.read_user_info()
        if not user.name:
            await client.end_of_sync()
            raise ValueError(_("this handheld has no HotSync user yet; set one with 'classicsync palm user NAME'"))
        if not user.synced:
            await set_user(client, user.name, pc_identifier())
            user = await client.read_user_info()
        partnership = find_palm_partnership(user) or create_palm_partnership(user.name, user.user_id)
        options = partnership.load_options()
        if arguments.provider:
            options.provider = arguments.provider
        if arguments.only:
            options.object_types = arguments.only
        if arguments.folder:
            options.provider_settings["folder"] = arguments.folder
        if arguments.save:
            partnership.save_options(options)
        options.dry_run = arguments.dry_run
        report = await synchronize_handheld(client, partnership, pc_identifier(), options, print_progress,
                                            first_sync=lambda question: arguments.first_sync, log=print)
        await client.end_of_sync()
    for action in report.actions:
        if action.action != "match" or arguments.verbose:
            print(_("would {action}").format(action=action) if report.dry_run else str(action))
    for error in report.errors:
        print(_("skipped {error}").format(error=error))
    summary = _("{device}: {summary} (dry run)") if report.dry_run else _("{device}: {summary}")
    print(summary.format(device=report.device, summary=report.summary()))


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
    install = palm_commands.add_parser("install", help=_("install .prc, .pdb or .pqa files on the handheld"))
    install.add_argument("files", nargs="+")
    install.add_argument("--wait", type=float, default=DEFAULT_WAIT, help=_("seconds to wait for the handheld"))
    install.set_defaults(handler=command_palm_install)
    user = palm_commands.add_parser("user", help=_("set the handheld's HotSync user name"))
    user.add_argument("name")
    user.add_argument("--wait", type=float, default=DEFAULT_WAIT, help=_("seconds to wait for the handheld"))
    user.set_defaults(handler=command_palm_user)
    sync = palm_commands.add_parser("sync", help=_("synchronize addresses, the date book, to do items and memos"))
    sync.add_argument("--dry-run", action="store_true", help=_("show what would change without changing anything"))
    sync.add_argument("--provider", help=_("sync provider (default: folder, or the saved one)"))
    sync.add_argument("--only", action="append", metavar="TYPE", choices=["contacts", "calendar", "tasks", "notes"],
                      help=_("only this type (repeatable)"))
    sync.add_argument("--folder", help=_("folder provider: where to keep the desktop copies"))
    sync.add_argument("--save", action="store_true", help=_("remember --provider, --only and --folder for this handheld"))
    sync.add_argument("--first-sync", choices=FIRST_SYNC_CHOICES, default=FIRST_SYNC_COMBINE,
                      help=_("what to do when both sides already have items"))
    sync.add_argument("--wait", type=float, default=DEFAULT_WAIT, help=_("seconds to wait for the handheld"))
    sync.set_defaults(handler=command_palm_sync)
