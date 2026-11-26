from datetime import datetime, timezone

from ..sync.engine import synchronize
from ..sync.objects import DeviceInfo
from ..sync.plugins import discover_plugins, conduits_from_sources, providers_from_sources
from ..sync.providers.notes.provider import NOTES, NotesProvider, TEXT_NOTES_PLATFORM
from ..sync.state import Partnership
from .conduit import ConduitContext, FreeformConduit, RecordConduit
from .users import set_user

PLATFORM = TEXT_NOTES_PLATFORM


def palm_partnerships(base=None):
    return [partnership for partnership in Partnership.list_all(base) if partnership.platform == PLATFORM]


def find_palm_partnership(user, base=None):
    if not user.synced:
        return None
    return next((partnership for partnership in palm_partnerships(base) if partnership.partner_id == user.user_id), None)


def create_palm_partnership(name, user_id, base=None):
    partnership = Partnership(name, Partnership.new_directory(name, base), user_id,
                              datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), platform=PLATFORM)
    partnership.save_info()
    return partnership


def ordered_conduits(conduit_classes):
    return sorted((conduit_class() for conduit_class in conduit_classes.values()), key=lambda conduit: conduit.priority)


def record_conduits(conduits):
    return {conduit.object_type.key: conduit for conduit in conduits if isinstance(conduit, RecordConduit)}


def palm_options(options, providers, by_type):
    primary = providers.get(options.provider)
    handles_notes = primary is not None and any(object_type.key == NOTES.key for object_type in primary.object_types)
    if NOTES.key in by_type and not handles_notes and NOTES.key not in options.type_providers:
        options.type_providers = {**options.type_providers, NOTES.key: NotesProvider.name}
    wanted = options.object_types or list(by_type)
    options.object_types = [key for key in wanted if key in by_type]
    return options


async def synchronize_handheld(client, partnership, pc_id, options=None, progress=None, providers=None, first_sync=None,
                               conduits=None, log=None):
    if providers is None or conduits is None:
        sources = discover_plugins()
        providers = providers if providers is not None else providers_from_sources(sources)
        conduits = conduits if conduits is not None else conduits_from_sources(sources)
    active = ordered_conduits(conduits)
    by_type = record_conduits(active)
    system = await client.read_sys_info()
    user = await client.read_user_info()
    device = DeviceInfo(name=user.name or partnership.name, os_major=system.rom_version >> 24, os_minor=system.rom_version >> 20 & 0x0F,
                        extra={"platform": PLATFORM})
    options = palm_options(options or partnership.load_options(), providers, by_type)

    def palm_source(source_client, object_type, source_options, provider=None):
        return by_type[object_type.key].source(source_client)

    report = await synchronize(client, partnership, options, progress, providers, first_sync, device=device, source_for=palm_source)
    context = ConduitContext(client, partnership, user, partnership.directory, log or (lambda text: None), options.dry_run)
    for conduit in active:
        if isinstance(conduit, FreeformConduit):
            try:
                await conduit.run(context)
            except (OSError, ValueError, ConnectionError) as error:
                report.errors.append(f"{conduit.display_name}: {error}")
    if not options.dry_run:
        await set_user(client, user.name or partnership.name, pc_id, user_id=partnership.partner_id)
    return report
