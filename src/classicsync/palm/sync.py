from datetime import datetime, timezone

from ..sync.engine import synchronize
from ..sync.objects import CALENDAR, CONTACTS, TASKS, DeviceInfo
from ..sync.state import Partnership
from .source import PalmDatabaseSource
from .users import set_user

PLATFORM = "palm"
PALM_TYPES = (CONTACTS.key, CALENDAR.key, TASKS.key)


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
    options = partnership.load_options()
    options.object_types = list(PALM_TYPES)
    partnership.save_options(options)
    return partnership


def palm_source(client, object_type, options, provider=None):
    if object_type.key not in PALM_TYPES:
        raise ValueError(f"Palm handhelds do not sync {object_type.key}")
    return PalmDatabaseSource(client, object_type)


async def synchronize_handheld(client, partnership, pc_id, options=None, progress=None, providers=None, first_sync=None):
    system = await client.read_sys_info()
    user = await client.read_user_info()
    device = DeviceInfo(name=user.name or partnership.name, os_major=system.rom_version >> 24, os_minor=system.rom_version >> 20 & 0x0F)
    options = options or partnership.load_options()
    options.object_types = [key for key in (options.object_types or PALM_TYPES) if key in PALM_TYPES]
    report = await synchronize(client, partnership, options, progress, providers, first_sync, device=device, source_for=palm_source)
    if not options.dry_run:
        await set_user(client, user.name or partnership.name, pc_id, user_id=partnership.partner_id)
    return report
