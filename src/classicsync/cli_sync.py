import sys

from . import cli
from .i18n import _, ngettext
from .sync import (
    CONFLICT_POLICIES, FIRST_SYNC_CHOICES, FIRST_SYNC_COMBINE, Partnership, PartnershipError, create_partnership,
    delete_partnership, find_partnership, synchronize,
)
from .sync.folder import default_folder
from .sync.partners import clear_device_partner, find_by_name, rename_device


def print_progress(update):
    if update.phase in ("start", "message"):
        print(update.message, file=sys.stderr)
    elif update.phase == "scan":
        print(f"{update.message}...", file=sys.stderr)


def describe_partnership(partnership):
    if partnership.explicit:
        return _("{name} (partner {partner})").format(name=partnership.name, partner=partnership.label)
    return partnership.name


async def partnership_for_sync(client, arguments):
    lookup = await find_partnership(client)
    if lookup.migrated:
        print(_("converted the existing {name} partnership (partner {partner})").format(
            name=lookup.partnership.name, partner=lookup.partnership.label), file=sys.stderr)
    if lookup.partnership:
        return lookup.partnership
    if not arguments.new_partnership:
        raise PartnershipError(_("{device} is connected as a guest; run 'classicsync partnership create' or pass "
                                 "--new-partnership").format(device=lookup.device_name))
    partnership = await create_partnership(client, partners=lookup.partners)
    print(_("created partnership {partnership}").format(partnership=describe_partnership(partnership)), file=sys.stderr)
    return partnership


async def command_sync(arguments):
    async with cli.rapi_session(arguments) as client:
        partnership = await partnership_for_sync(client, arguments)
        options = partnership.load_options()
        if arguments.provider:
            options.provider = arguments.provider
        if arguments.only:
            options.object_types = arguments.only
        if arguments.folder:
            options.provider_settings["folder"] = arguments.folder
        for item in arguments.conflict or []:
            object_type, separator, policy = item.rpartition("=")
            for key in [object_type] if object_type else ["files", "contacts", "calendar", "tasks"]:
                options.conflict[key] = policy
        if arguments.save:
            partnership.save_options(options)
        options.dry_run = arguments.dry_run
        report = await synchronize(client, partnership, options, print_progress,
                                   first_sync=lambda question: arguments.first_sync)
    for action in report.actions:
        if action.action != "match" or arguments.verbose:
            print(_("would {action}").format(action=action) if report.dry_run else str(action))
    for error in report.errors:
        print(_("skipped {error}").format(error=error), file=sys.stderr)
    summary = _("{device}: {summary} (dry run)") if report.dry_run else _("{device}: {summary}")
    print(summary.format(device=report.device, summary=report.summary()))
    for key, choice in sorted(report.first_sync.items()):
        print(_("{type}: first synchronization, {choice}").format(type=key, choice=choice))
    if report.unresolved:
        print(ngettext("{count} unresolved conflict; run again with --conflict device or --conflict desktop",
                       "{count} unresolved conflicts; run again with --conflict device or --conflict desktop",
                       len(report.unresolved)).format(count=len(report.unresolved)))


async def command_sync_status(arguments):
    partnerships = Partnership.list_all()
    if arguments.device:
        partnerships = [partnership for partnership in partnerships if partnership.name.lower() == arguments.device.lower()]
    if not partnerships:
        print(_("no partnerships yet; run 'classicsync partnership create' with a device connected"))
        return
    for partnership in partnerships:
        state = partnership.load_state()
        options = partnership.load_options()
        folder = options.provider_settings.get("folder") or default_folder(partnership.name)
        print(describe_partnership(partnership))
        if options.provider == "folder":
            print("  " + _("provider: {provider} ({folder})").format(provider=options.provider, folder=folder))
        else:
            print("  " + _("provider: {provider}").format(provider=options.provider))
        for key, provider_name in sorted(options.type_providers.items()):
            print("  " + _("{type}: provider {provider}").format(type=key, provider=provider_name))
        print("  " + _("last sync: {stamp}  {result}").format(stamp=state.get("last_sync", _("never")), result=state.get("last_result", "")))
        for key, stored in sorted(state.get("types", {}).items()):
            unresolved = stored.get("unresolved", [])
            item_count = len(stored.get("items", []))
            line = "  " + ngettext("{type}: {count} item", "{type}: {count} items", item_count).format(type=key, count=item_count)
            if unresolved:
                line += ", " + ngettext("{count} unresolved: {items}", "{count} unresolved: {items}", len(unresolved)).format(
                    count=len(unresolved), items=", ".join(entry["description"] for entry in unresolved))
            print(line)


async def command_partnership_list(arguments):
    partnerships = Partnership.list_all()
    if not partnerships:
        print(_("no partnerships"))
    for partnership in partnerships:
        state = partnership.load_state()
        kind = _("partner {partner}").format(partner=partnership.label) if partnership.explicit else _(
            "implicit, converted on next connect")
        print(_("{name}  ({kind})  created {created}  last sync {last_sync}").format(
            name=partnership.name, kind=kind, created=partnership.created or "?", last_sync=state.get("last_sync", _("never"))))
        print(f"  {partnership.directory}")


async def command_partnership_device(arguments):
    async with cli.rapi_session(arguments) as client:
        lookup = await find_partnership(client, migrate=False)
        partners = lookup.partners
        if lookup.partnership:
            print(_("{device}: partnership {partnership}").format(device=lookup.device_name,
                                                                  partnership=describe_partnership(lookup.partnership)))
        else:
            print(_("{device}: guest").format(device=lookup.device_name))
        for partner in partners.partners:
            print(_("  slot {slot}: partner {partner} {desktop}").format(slot=partner.slot, partner=f"{partner.partner_id:08x}",
                                                                         desktop=partner.desktop_name))
        free = len(partners.slots) - len(partners.partners)
        print(ngettext("  {count} free slot", "  {count} free slots", free).format(count=free))


async def command_partnership_create(arguments):
    async with cli.rapi_session(arguments) as client:
        lookup = await find_partnership(client)
        if lookup.partnership:
            print(_("already partnered: {partnership}").format(partnership=describe_partnership(lookup.partnership)))
            return
        partners = lookup.partners
        if arguments.remove_slot:
            await clear_device_partner(client, partners, arguments.remove_slot)
        if arguments.name and arguments.name != lookup.device_name:
            await rename_device(client, arguments.name)
        partnership = await create_partnership(client, arguments.name or lookup.device_name,
                                               exclusive=arguments.only_this_computer, partners=partners)
    print(_("created partnership {partnership}").format(partnership=describe_partnership(partnership)))


async def command_partnership_delete(arguments):
    partnership = find_by_name(arguments.name)
    if partnership is None:
        raise PartnershipError(_("no partnership called {name!r}").format(name=arguments.name))
    if arguments.on_device:
        async with cli.rapi_session(arguments) as client:
            await delete_partnership(partnership, client)
    else:
        await delete_partnership(partnership)
    print(_("deleted partnership {partnership}; desktop copies in the sync folder were kept").format(
        partnership=describe_partnership(partnership)))


def add_device_target(parser):
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--port", help=_("connect directly on this serial port or tcp:HOST:PORT instead of using 'serve'"))
    target.add_argument("--connect", default=cli.DEFAULT_PROXY,
                        help=_("classicsync serve address (default {address})").format(address=cli.DEFAULT_PROXY))
    cli.add_link_arguments(parser)
    return parser


def add_partnership_commands(subparsers):
    partnership = subparsers.add_parser("partnership", help=_("list, create and delete partnerships"))
    actions = partnership.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help=_("list the partnerships on this computer")).set_defaults(handler=command_partnership_list)
    device = add_device_target(actions.add_parser("device", help=_("show the connected device's partnership slots")))
    device.set_defaults(handler=command_partnership_device)
    create = add_device_target(actions.add_parser("create", help=_("set up a partnership with the connected device")))
    create.add_argument("--name", help=_("rename the device first (starts with a letter; A-Z, 0-9 and _)"))
    create.add_argument("--only-this-computer", action="store_true",
                        help=_("remove the device's other partnerships (default: keep them; a device holds two)"))
    create.add_argument("--remove-slot", type=int, choices=(1, 2),
                        help=_("delete the device's partnership in this slot first (see 'partnership device')"))
    create.set_defaults(handler=command_partnership_create)
    delete = add_device_target(actions.add_parser("delete", help=_("delete a partnership from this computer")))
    delete.add_argument("name", help=_("partnership name or partner id"))
    delete.add_argument("--on-device", action="store_true", help=_("also clear the partnership on the connected device"))
    delete.set_defaults(handler=command_partnership_delete)


def add_commands(subparsers, device_command):
    sync = device_command("sync", command_sync, _("synchronize files, contacts, calendar and tasks with this computer"))
    sync.add_argument("--dry-run", action="store_true", help=_("show what would change without changing anything"))
    sync.add_argument("--provider", help=_("sync provider (default: folder, or the saved one)"))
    sync.add_argument("--only", action="append", metavar="TYPE",
                      help=_("synchronize only this type: files, contacts, calendar, tasks or mail (repeatable)"))
    sync.add_argument("--folder", help=_("folder provider: where to keep the desktop copies"))
    sync.add_argument("--conflict", action="append", metavar="[TYPE=]POLICY",
                      help=_("conflict policy, one of {policies}, for all types or one type").format(policies=", ".join(CONFLICT_POLICIES)))
    sync.add_argument("--save", action="store_true", help=_("remember --provider, --only, --folder and --conflict for this device"))
    sync.add_argument("--new-partnership", action="store_true", help=_("set up a partnership first if the device is a guest"))
    sync.add_argument("--first-sync", choices=FIRST_SYNC_CHOICES, default=FIRST_SYNC_COMBINE,
                      help=_("when both sides already have items of a type never synchronized: combine them (default), "
                             "replace the device's items with this computer's, or skip the type"))
    status = subparsers.add_parser("sync-status", help=_("show partnerships and the result of their last sync"))
    status.add_argument("--device", help=_("only this device"))
    status.set_defaults(handler=command_sync_status)
    add_partnership_commands(subparsers)
