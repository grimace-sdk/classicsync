import sys

from . import cli
from .i18n import _, ngettext
from .install import DesktopAppRecords, InstallError, install_file, list_installed_apps, uninstall_app


def print_progress(written, total):
    if sys.stderr.isatty():
        print("\r" + _("copying {percent}%").format(percent=written * 100 // max(total, 1)), end="" if written < total else "\n", file=sys.stderr)


async def command_install(arguments):
    async with cli.rapi_session(arguments) as client:
        outcomes = await install_file(
            client, arguments.file,
            destination=cli.device_path(arguments.destination) if arguments.destination else None,
            default_folder=not arguments.ask_destination,
            progress=print_progress,
            log=lambda message: print(message, file=sys.stderr) if arguments.verbose else None,
        )
    failures = 0
    for outcome in outcomes:
        print(outcome.message)
        for error in outcome.errors:
            print(f"  {error}", file=sys.stderr)
        failures += len(outcome.errors)
    if failures:
        raise InstallError(ngettext("{count} step failed", "{count} steps failed", failures).format(count=failures))


async def command_apps(arguments):
    async with cli.rapi_session(arguments) as client:
        installed = await list_installed_apps(client)
    print(_("Installed on the device:"))
    for app in installed:
        print(f"  {app.name}" + (f"  ({app.install_directory})" if app.install_directory else ""))
    if not installed:
        print("  " + _("none"))
    installed_names = {app.name.lower() for app in installed}
    records = DesktopAppRecords().all()
    if records:
        print(_("Added to this computer:"))
        for record in records:
            state = _("installed") if (record.uninstall or record.name).lower() in installed_names else _("not installed")
            print(f"  {record.name}  {record.description}  [{state}]  {record.ini_path}")


async def command_uninstall(arguments):
    records = DesktopAppRecords()
    async with cli.rapi_session(arguments) as client:
        installed = await list_installed_apps(client)
        wanted = arguments.name.lower()
        record = records.get(arguments.name)
        if record and record.uninstall:
            wanted = record.uninstall.lower()
        match = next((app for app in installed if app.name.lower() == wanted), None)
        if match is None:
            raise InstallError(_("{name} is not installed on the device; see 'classicsync apps'").format(name=arguments.name))
        await uninstall_app(client, match.name)
        print(_("started \\Windows\\Unload.exe \"{name}\"; check the device screen").format(name=match.name))
    if arguments.desktop and record:
        records.remove(record.name)
        print(_("removed {name} from this computer's list").format(name=record.name))


def add_commands(subparsers, device_command):
    install = device_command("install", command_install, _("install a .cab, CeAppMgr .ini, H/PC .load or Casio .cbea package on the device"))
    install.add_argument("file")
    install.add_argument("--dest", dest="destination", help=_("install folder for .load scripts"))
    install.add_argument("--ask-destination", action="store_true", help=_("let wceload ask where to install instead of /noaskdest"))
    device_command("apps", command_apps, _("list programs installed on the device"))
    uninstall = device_command("uninstall", command_uninstall, _("remove a program from the device with Unload.exe"))
    uninstall.add_argument("name")
    uninstall.add_argument("--desktop", action="store_true", help=_("also forget it on this computer"))
