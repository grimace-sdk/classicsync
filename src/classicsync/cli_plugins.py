from pathlib import Path

from .i18n import N_, _
from .sync.partners import PartnershipError, find_by_name
from .sync.plugin_install import KIND_FILE, install_plugin, load_manifest, plugin_present, remove_plugin, update_plugin
from .sync.plugins import (
    ORIGIN_BUILTIN, ORIGIN_FILE, ORIGIN_LABELS, ORIGIN_LIBRARY, discover_plugins, library_tag, normalized_name,
    providers_from_sources,
)
from .sync.settings_schema import (
    SOURCE_DEFAULT, SOURCE_DEVICE, SOURCE_GLOBAL, SettingError, apply_changes, apply_to_options, load_global_settings,
    parse_assignments, provider_schema, save_global_settings, setting_sources,
)
from .sync.state import Partnership

SOURCE_LABELS = {SOURCE_DEFAULT: N_("default"), SOURCE_GLOBAL: N_("all devices"), SOURCE_DEVICE: N_("this device")}


def describe_provider(provider):
    types = ", ".join(object_type.key for object_type in provider.object_types)
    return _("{name}: {display_name} ({types})").format(name=provider.name, display_name=provider.display_name or provider.name,
                                                       types=types)


def manifest_entry_for(manifest, source):
    if source.origin == ORIGIN_LIBRARY:
        wanted = normalized_name(source.name)
        return next((entry for entry in manifest.values() if entry.kind != KIND_FILE and normalized_name(entry.name) == wanted), None)
    if source.origin == ORIGIN_FILE:
        return next((entry for entry in manifest.values() if entry.kind == KIND_FILE and Path(source.location).name == entry.file), None)
    return None


def print_installed_plugins(sources, manifest):
    active = providers_from_sources(sources)
    listed = set()
    for source in sources:
        entry = manifest_entry_for(manifest, source)
        if entry:
            listed.add(entry.name)
        heading = " ".join(part for part in (source.name, source.version) if part)
        where = _(ORIGIN_LABELS[source.origin])
        if entry:
            where = _("{origin}, from {spec}").format(origin=where, spec=entry.spec)
        elif source.origin != ORIGIN_BUILTIN and source.location:
            where = _("{origin}, {location}").format(origin=where, location=source.location)
        print(f"{heading}  ({where})")
        for provider in source.providers:
            line = "  " + describe_provider(provider)
            if active.get(provider.name) is not provider:
                line += "  " + _("(replaced by a later plugin)")
            print(line)
        for error in source.errors:
            print("  " + _("failed to load: {error}").format(error=error))
    for name, entry in sorted(manifest.items()):
        if name in listed:
            continue
        if entry.kind != KIND_FILE and entry.library and entry.library != library_tag():
            print(_("{name} {version}  (installed for {library}; run 'classicsync plugin update {name}' for this Python)").format(
                name=name, version=entry.version, library=entry.library))
        elif not plugin_present(entry):
            print(_("{name} {version}  (missing; run 'classicsync plugin update {name}' or remove it)").format(
                name=name, version=entry.version))


async def command_plugin_list(arguments):
    print_installed_plugins(discover_plugins(), load_manifest())


def print_installed(entries, verb):
    for entry in entries:
        print(verb.format(name=entry.name, version=entry.version or "?", providers=", ".join(entry.providers) or _("none")))
        for error in entry.errors:
            print("  " + _("failed to load: {error}").format(error=error))


async def command_plugin_install(arguments):
    for spec in arguments.specs:
        print_installed(install_plugin(spec), _("installed {name} {version}, providers: {providers}"))


async def command_plugin_remove(arguments):
    entry = remove_plugin(arguments.name)
    print(_("removed {name}").format(name=entry.name))


async def command_plugin_update(arguments):
    names = [arguments.name] if arguments.name else sorted(load_manifest())
    if not names:
        print(_("no plugins installed"))
    for name in names:
        print_installed(update_plugin(name), _("updated {name} {version}, providers: {providers}"))


def chosen_partnership(device):
    if device:
        partnership = find_by_name(device)
        if partnership is None:
            raise PartnershipError(_("no partnership called {name!r}").format(name=device))
        return partnership
    partnerships = Partnership.list_all()
    if len(partnerships) == 1:
        return partnerships[0]
    if not partnerships:
        raise PartnershipError(_("no partnerships yet; run 'classicsync partnership create' with a device connected"))
    raise PartnershipError(_("more than one partnership; choose one with --device: {names}").format(
        names=", ".join(partnership.name for partnership in partnerships)))


def find_provider(name):
    providers = providers_from_sources(discover_plugins())
    if name not in providers:
        raise ValueError(_("no sync provider called {name!r}; have {names}").format(name=name, names=", ".join(sorted(providers))))
    return providers[name]


def print_settings(provider_class, partnership, options):
    schema = provider_schema(provider_class)
    global_values = load_global_settings(provider_class.name)
    if partnership:
        print(_("{provider} settings for {device}").format(provider=provider_class.name, device=partnership.name))
    else:
        print(_("{provider} settings for all devices").format(provider=provider_class.name))
    if not schema:
        values = {**global_values, **(options.provider_settings if options else {})}
        if not values:
            print("  " + _("this provider declares no settings"))
        for key, value in sorted(values.items()):
            print(f"  {key} = {value}")
        return
    for setting, value, source in setting_sources(schema, global_values, options):
        if setting.per_device and partnership is None:
            print("  " + _("{key}: set per device (--device)").format(key=setting.key))
            continue
        print(f"  {setting.key} = {setting.format(value)}  [{_(SOURCE_LABELS[source])}]")
        print(f"      {_(setting.label)}" + (f": {_(setting.help)}" if setting.help else ""))


async def command_plugin_configure(arguments):
    provider_class = find_provider(arguments.provider)
    partnership = chosen_partnership(arguments.device) if arguments.device else None
    options = partnership.load_options() if partnership else None
    if arguments.assignments:
        schema = provider_schema(provider_class)
        changes = parse_assignments(schema, arguments.assignments)
        if partnership:
            apply_to_options(options, changes)
            partnership.save_options(options)
            if options.provider != provider_class.name:
                print(_("note: {device} synchronizes with {current}; run 'classicsync plugin use {provider} --device {device}' "
                        "to switch").format(device=partnership.name, current=options.provider, provider=provider_class.name))
        else:
            per_device = [setting.key for setting in schema if setting.per_device and setting.key in changes]
            if per_device:
                raise SettingError(_("{keys} can only be set for one device; add --device").format(keys=", ".join(per_device)))
            values = apply_changes(load_global_settings(provider_class.name), changes)
            save_global_settings(provider_class.name, values)
    print_settings(provider_class, partnership, options)


async def command_plugin_use(arguments):
    provider_class = find_provider(arguments.provider)
    partnership = chosen_partnership(arguments.device)
    options = partnership.load_options()
    options.provider = provider_class.name
    partnership.save_options(options)
    print(_("{device} now synchronizes with {provider}").format(device=partnership.name,
                                                                provider=provider_class.display_name or provider_class.name))


def add_commands(subparsers):
    plugin = subparsers.add_parser("plugin", help=_("install, list, remove and configure sync plugins"))
    actions = plugin.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help=_("list sync plugins and the providers they offer")).set_defaults(handler=command_plugin_list)
    install = actions.add_parser("install", help=_("install a sync plugin"))
    install.add_argument("specs", nargs="+", metavar="SPEC",
                         help=_("a PyPI requirement, git+https:// URL, project folder, wheel (.whl) or .py file"))
    install.set_defaults(handler=command_plugin_install)
    remove = actions.add_parser("remove", help=_("remove an installed sync plugin and the packages only it needed"))
    remove.add_argument("name", help=_("plugin or provider name"))
    remove.set_defaults(handler=command_plugin_remove)
    update = actions.add_parser("update", help=_("reinstall a sync plugin from where it came from, upgrading it"))
    update.add_argument("name", nargs="?", help=_("plugin or provider name (default: all)"))
    update.set_defaults(handler=command_plugin_update)
    configure = actions.add_parser("configure", help=_("show or change a sync provider's settings"))
    configure.add_argument("provider", help=_("provider name"))
    configure.add_argument("--device", help=_("change the settings for this partnership (default: for all devices)"))
    configure.add_argument("assignments", nargs="*", metavar="KEY=VALUE",
                           help=_("settings to change; an empty value returns to the default; lists are separated by ';'"))
    configure.set_defaults(handler=command_plugin_configure)
    use = actions.add_parser("use", help=_("choose the sync provider for a partnership"))
    use.add_argument("provider", help=_("provider name"))
    use.add_argument("--device", help=_("partnership name (needed when there is more than one)"))
    use.set_defaults(handler=command_plugin_use)
