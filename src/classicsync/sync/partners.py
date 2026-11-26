import random
import re
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..i18n import _
from ..rapi.client import HKEY_LOCAL_MACHINE, REG_DWORD, REG_SZ, RapiError
from .device import read_device_info
from .state import Partnership

SERVICES_KEY = "Software\\Microsoft\\Windows CE Services"
PARTNERS_KEY = SERVICES_KEY + "\\Partners"
PARTNER_ID_VALUE = "PId"
PARTNER_NAME_VALUE = "PName"
CURRENT_PARTNER_VALUE = "PCur"
SERVICES_VERSION_VALUE = "Version"
SUPPORTED_SERVICES_VERSION = 0x20000
LEGACY_PARTNER_KEY = "Ident"
LEGACY_PARTNER_ID_VALUE = "PartnerId"
DEVICE_NAME_KEY = "Ident"
DEVICE_NAME_VALUE = "Name"
DEVICE_DESCRIPTION_VALUE = "Desc"
PARTNER_SLOTS = (1, 2)
LEGACY_PARTNER_SLOTS = (1,)
MAX_PARTNER_NAME = 15
MAX_DEVICE_NAME = 15
VALID_DEVICE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class PartnershipError(Exception):
    pass


class NoPartnership(PartnershipError):
    pass


@dataclass
class DevicePartner:
    slot: int
    partner_id: int
    desktop_name: str = ""


@dataclass
class DevicePartners:
    legacy: bool = False
    partners: list = field(default_factory=list)
    services_version: int = None

    @property
    def slots(self):
        return LEGACY_PARTNER_SLOTS if self.legacy else PARTNER_SLOTS

    @property
    def partner_ids(self):
        return [partner.partner_id for partner in self.partners]

    @property
    def full(self):
        return self.free_slot() is None

    def free_slot(self):
        used = {partner.slot for partner in self.partners}
        return next((slot for slot in self.slots if slot not in used), None)

    def slot_of(self, partner_id):
        return next((partner.slot for partner in self.partners if partner.partner_id == partner_id), None)

    @property
    def services_supported(self):
        return self.services_version == SUPPORTED_SERVICES_VERSION


@dataclass
class PartnerLookup:
    partnership: Partnership = None
    partners: DevicePartners = None
    device_name: str = ""
    migrated: bool = False


def desktop_computer_name():
    return (socket.gethostname().split(".")[0] or "DESKTOP").upper()[:MAX_PARTNER_NAME]


def valid_device_name(name):
    return bool(VALID_DEVICE_NAME.match(name)) and len(name) <= MAX_DEVICE_NAME


def new_partner_id(taken=()):
    generator = random.SystemRandom()
    while True:
        partner_id = generator.getrandbits(32)
        if partner_id and partner_id not in taken:
            return partner_id


async def read_value(client, subkey, name):
    try:
        key = await client.reg_open_key(HKEY_LOCAL_MACHINE, subkey)
    except RapiError:
        return None
    try:
        return (await client.reg_query_value(key, name))[1]
    except RapiError:
        return None
    finally:
        await client.reg_close_key(key)


async def write_values(client, subkey, values):
    key, disposition = await client.reg_create_key(HKEY_LOCAL_MACHINE, subkey)
    try:
        for name, value_type, value in values:
            await client.reg_set_value(key, name, value_type, value)
    finally:
        await client.reg_close_key(key)


def slot_key(slot):
    return f"{PARTNERS_KEY}\\P{slot}"


async def read_device_partners(client):
    version = client.version or await client.get_version()
    if version.major < 2:
        partner_id = await read_value(client, LEGACY_PARTNER_KEY, LEGACY_PARTNER_ID_VALUE)
        partners = [DevicePartner(LEGACY_PARTNER_SLOTS[0], partner_id)] if isinstance(partner_id, int) and partner_id else []
        return DevicePartners(legacy=True, partners=partners)
    partners = []
    for slot in PARTNER_SLOTS:
        partner_id = await read_value(client, slot_key(slot), PARTNER_ID_VALUE)
        if isinstance(partner_id, int) and partner_id:
            desktop_name = await read_value(client, slot_key(slot), PARTNER_NAME_VALUE)
            partners.append(DevicePartner(slot, partner_id, desktop_name if isinstance(desktop_name, str) else ""))
    services_version = await read_value(client, SERVICES_KEY, SERVICES_VERSION_VALUE)
    return DevicePartners(partners=partners, services_version=services_version if isinstance(services_version, int) else None)


async def write_device_partner(client, partners, slot, partner_id, desktop_name):
    if partners.legacy:
        await write_values(client, LEGACY_PARTNER_KEY, [(LEGACY_PARTNER_ID_VALUE, REG_DWORD, partner_id)])
    else:
        await write_values(client, slot_key(slot), [
            (PARTNER_ID_VALUE, REG_DWORD, partner_id), (PARTNER_NAME_VALUE, REG_SZ, desktop_name[:MAX_PARTNER_NAME]),
        ])
        await write_values(client, PARTNERS_KEY, [(CURRENT_PARTNER_VALUE, REG_DWORD, slot)])
    partners.partners = [partner for partner in partners.partners if partner.slot != slot]
    partners.partners.append(DevicePartner(slot, partner_id, desktop_name))
    partners.partners.sort(key=lambda partner: partner.slot)


async def clear_device_partner(client, partners, slot):
    if partners.legacy:
        await write_values(client, LEGACY_PARTNER_KEY, [(LEGACY_PARTNER_ID_VALUE, REG_DWORD, 0)])
    else:
        await write_values(client, slot_key(slot), [(PARTNER_ID_VALUE, REG_DWORD, 0), (PARTNER_NAME_VALUE, REG_SZ, "")])
        try:
            key = await client.reg_open_key(HKEY_LOCAL_MACHINE, PARTNERS_KEY)
            try:
                await client.reg_delete_key(key, f"P{slot}")
            finally:
                await client.reg_close_key(key)
        except RapiError:
            pass
    partners.partners = [partner for partner in partners.partners if partner.slot != slot]


async def read_device_name(client):
    return (await read_device_info(client)).name


async def rename_device(client, name):
    if not valid_device_name(name):
        raise PartnershipError(_("Enter a unique name that starts with a letter and contains the characters _, A-Z, or 0-9."))
    await write_values(client, DEVICE_NAME_KEY, [(DEVICE_NAME_VALUE, REG_SZ, name)])


async def describe_device(client, description):
    await write_values(client, DEVICE_NAME_KEY, [(DEVICE_DESCRIPTION_VALUE, REG_SZ, description)])


def match_partnership(partner_ids, partnerships):
    wanted = {partner_id for partner_id in partner_ids if partner_id}
    return next((partnership for partnership in partnerships
                 if partnership.explicit and not partnership.platform and partnership.partner_id in wanted), None)


def implicit_partnership(device_name, partnerships):
    wanted = device_name.lower()
    return next((partnership for partnership in partnerships
                 if not partnership.explicit and not partnership.platform and partnership.name.lower() == wanted
                 and partnership.state_path.exists()), None)


async def find_partnership(client, announced_ids=(), base=None, migrate=True):
    partners = await read_device_partners(client)
    device_name = await read_device_name(client)
    partnerships = Partnership.list_all(base)
    partnership = match_partnership(set(announced_ids) | set(partners.partner_ids), partnerships)
    if partnership:
        return PartnerLookup(partnership, partners, device_name)
    implicit = implicit_partnership(device_name, partnerships)
    if implicit and migrate and not partners.full:
        await adopt_partnership(client, implicit, partners)
        return PartnerLookup(implicit, partners, device_name, migrated=True)
    return PartnerLookup(None, partners, device_name)


async def adopt_partnership(client, partnership, partners, slot=None):
    slot = slot or partners.free_slot()
    if slot is None:
        raise PartnershipError(_("This mobile device already has the maximum number of partnerships."))
    taken = set(partners.partner_ids) | {other.partner_id for other in Partnership.list_all(partnership.directory.parent)}
    partner_id = new_partner_id(taken)
    desktop_name = desktop_computer_name()
    await write_device_partner(client, partners, slot, partner_id, desktop_name)
    partnership.partner_id = partner_id
    partnership.desktop_name = desktop_name
    partnership.created = partnership.created or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    partnership.save_info()
    return partnership


async def create_partnership(client, name=None, exclusive=False, base=None, partners=None):
    partners = partners or await read_device_partners(client)
    name = name or await read_device_name(client)
    if exclusive:
        for partner in list(partners.partners):
            await clear_device_partner(client, partners, partner.slot)
    if partners.full:
        raise PartnershipError(_("This mobile device already has the maximum number of partnerships. Delete one first."))
    partnerships = Partnership.list_all(base)
    implicit = implicit_partnership(name, partnerships)
    partnership = implicit or Partnership(name, Partnership.new_directory(name, base))
    partnership.directory.mkdir(parents=True, exist_ok=True)
    return await adopt_partnership(client, partnership, partners)


async def delete_partnership(partnership, client=None):
    if client is not None and partnership.explicit:
        partners = await read_device_partners(client)
        slot = partners.slot_of(partnership.partner_id)
        if slot is not None:
            await clear_device_partner(client, partners, slot)
    partnership.remove()


def find_by_name(name, base=None):
    wanted = name.lower()
    for partnership in Partnership.list_all(base):
        if partnership.name.lower() == wanted or partnership.label == wanted or partnership.directory.name.lower() == wanted:
            return partnership
    return None
