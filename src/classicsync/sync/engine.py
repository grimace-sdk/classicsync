import inspect
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..i18n import N_, _
from ..rapi.client import RapiError
from .device import DeviceDatabase, DeviceFolder, read_device_info
from .mail.device import DeviceMailbox
from .objects import KIND_FILES, KIND_MAIL
from .plugins import load_providers
from .provider import ProviderContext, ProviderError
from .settings_schema import effective_settings
from .state import SyncOptions
from .partners import NoPartnership, find_partnership

log = logging.getLogger("classicsync.sync")

CONFLICT_POLICIES = ("skip", "device", "desktop", "keep_both")
RESOLUTION_CHOICES = ("skip", "device", "desktop")

FIRST_SYNC_COMBINE = "combine"
FIRST_SYNC_REPLACE = "replace"
FIRST_SYNC_SKIP = "skip"
FIRST_SYNC_CHOICES = (FIRST_SYNC_COMBINE, FIRST_SYNC_REPLACE, FIRST_SYNC_SKIP)

TO_DESKTOP = "to desktop"
TO_DEVICE = "to device"

ADD = "add"
UPDATE = "update"
DELETE = "delete"
CONFLICT = "conflict"
MATCH = "match"


RESOLVED_DIRECTIONS = {"device": TO_DESKTOP, "desktop": TO_DEVICE}
COUNT_LABELS = {
    "add to desktop": N_("{count} add to desktop"), "add to device": N_("{count} add to device"),
    "update to desktop": N_("{count} update to desktop"), "update to device": N_("{count} update to device"),
    "delete to desktop": N_("{count} delete to desktop"), "delete to device": N_("{count} delete to device"),
    "conflict": N_("{count} conflict"), "conflict kept both": N_("{count} conflict kept both"),
}


class SyncError(Exception):
    pass


@dataclass
class SyncProgress:
    phase: str
    object_type: str = ""
    done: int = 0
    total: int = 0
    message: str = ""


@dataclass
class SyncAction:
    object_type: str
    action: str
    direction: str = ""
    device_id: str = None
    desktop_id: str = None
    description: str = ""
    resolution: str = ""
    applied: bool = False
    error: str = ""

    @property
    def count_key(self):
        if self.action == CONFLICT and self.resolution in RESOLVED_DIRECTIONS:
            return f"{UPDATE} {RESOLVED_DIRECTIONS[self.resolution]}"
        if self.action == CONFLICT and self.resolution == "keep_both":
            return "conflict kept both"
        return f"{self.action} {self.direction}".strip()

    def __str__(self):
        text = f"{self.object_type}: {self.action}"
        if self.direction:
            text += f" {self.direction}"
        if self.resolution:
            text += f" ({self.resolution})"
        text += f": {self.description}"
        if self.error:
            text += f" [failed: {self.error}]"
        return text


@dataclass
class SyncReport:
    device: str = ""
    provider: str = ""
    dry_run: bool = False
    actions: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    skipped_types: list = field(default_factory=list)
    first_sync: dict = field(default_factory=dict)

    @property
    def unresolved(self):
        return [action for action in self.actions if action.action == CONFLICT and action.resolution == "skip"]

    def counts(self):
        totals = {}
        for action in self.actions:
            if action.action == MATCH or action.error:
                continue
            totals[action.count_key] = totals.get(action.count_key, 0) + 1
        return totals

    def summary(self):
        parts = [_(COUNT_LABELS[name]).format(count=count) if name in COUNT_LABELS else f"{count} {name}"
                 for name, count in sorted(self.counts().items())]
        failures = sum(1 for action in self.actions if action.error) + len(self.errors)
        if failures:
            parts.append(_("{count} failed").format(count=failures))
        return ", ".join(parts) or _("nothing to do")


@dataclass
class FirstSync:
    object_type: object
    device_count: int
    desktop_count: int


async def answer(callback, *arguments):
    result = callback(*arguments)
    if inspect.isawaitable(result):
        result = await result
    return result


def conflict_key(device_id, desktop_id):
    return f"{device_id or ''}|{desktop_id or ''}"


def entry_for(device_id, desktop_id, device_stamp, desktop_stamp):
    return {"device_id": device_id, "desktop_id": desktop_id, "device_stamp": device_stamp, "desktop_stamp": desktop_stamp}


class TypeSync:
    def __init__(self, object_type, device_source, store, policy, report, progress, dry_run, resolutions=None):
        self.object_type = object_type
        self.resolutions = resolutions or {}
        self.device = device_source
        self.store = store
        self.policy = policy
        self.report = report
        self.progress = progress
        self.dry_run = dry_run
        self.device_items = {}
        self.desktop_items = {}
        self.mapping = []
        self.unresolved = []
        self.read_ahead = {}

    def describe(self, device_id, desktop_id):
        if desktop_id:
            return self.store.describe(desktop_id)
        return device_id or ""

    def action(self, kind, direction, device_id, desktop_id, resolution=""):
        return SyncAction(self.object_type.key, kind, direction, device_id, desktop_id,
                          self.describe(device_id, desktop_id), resolution)

    def conflict_resolution(self, device_id, desktop_id):
        return self.resolutions.get(conflict_key(device_id, desktop_id), self.policy)

    async def list_both(self):
        self.device_items = await self.device.list()
        self.desktop_items = self.store.list_items()

    async def plan(self, previous_entries, mode=FIRST_SYNC_COMBINE):
        planned = []
        mapped_device = set()
        mapped_desktop = set()
        for entry in previous_entries:
            device_id, desktop_id = entry["device_id"], entry["desktop_id"]
            mapped_device.add(device_id)
            mapped_desktop.add(desktop_id)
            on_device = device_id in self.device_items
            on_desktop = desktop_id in self.desktop_items
            device_changed = on_device and self.device_items[device_id] != entry["device_stamp"]
            desktop_changed = on_desktop and self.desktop_items[desktop_id] != entry["desktop_stamp"]
            if not on_device and not on_desktop:
                continue
            if not on_device:
                if desktop_changed:
                    planned.append((self.action(ADD, TO_DEVICE, None, desktop_id), entry))
                else:
                    planned.append((self.action(DELETE, TO_DESKTOP, device_id, desktop_id), entry))
            elif not on_desktop:
                if device_changed:
                    planned.append((self.action(ADD, TO_DESKTOP, device_id, None), entry))
                else:
                    planned.append((self.action(DELETE, TO_DEVICE, device_id, desktop_id), entry))
            elif device_changed and desktop_changed:
                planned.append((self.action(CONFLICT, "", device_id, desktop_id,
                                            self.conflict_resolution(device_id, desktop_id)), entry))
            elif device_changed:
                planned.append((self.action(UPDATE, TO_DESKTOP, device_id, desktop_id), entry))
            elif desktop_changed:
                planned.append((self.action(UPDATE, TO_DEVICE, device_id, desktop_id), entry))
            else:
                self.mapping.append(entry)
        unmatched_desktop = [item_id for item_id in self.desktop_items if item_id not in mapped_desktop]
        for device_id in self.device_items:
            if device_id in mapped_device:
                continue
            device_object = await self.device.read(device_id)
            self.read_ahead[device_id] = device_object
            match = self.store.find_match(device_id, device_object, list(unmatched_desktop))
            if match is not None and match in unmatched_desktop:
                unmatched_desktop.remove(match)
                if self.store.same_content(match, device_id, device_object):
                    planned.append((self.action(MATCH, "", device_id, match), None))
                elif mode == FIRST_SYNC_REPLACE:
                    planned.append((self.action(UPDATE, TO_DEVICE, device_id, match), None))
                else:
                    planned.append((self.action(CONFLICT, "", device_id, match, self.conflict_resolution(device_id, match)), None))
            elif mode == FIRST_SYNC_REPLACE:
                planned.append((SyncAction(self.object_type.key, DELETE, TO_DEVICE, device_id, None,
                                           self.describe_device(device_id, device_object)), None))
            else:
                planned.append((self.action(ADD, TO_DESKTOP, device_id, None), None))
        for desktop_id in unmatched_desktop:
            planned.append((self.action(ADD, TO_DEVICE, None, desktop_id), None))
        return planned

    def describe_device(self, device_id, device_object):
        return self.store.describe_device(device_id, device_object) or device_id

    async def read_device(self, device_id):
        return self.read_ahead.pop(device_id, None) or await self.device.read(device_id)

    async def copy_to_desktop(self, device_id, desktop_id):
        device_object = await self.read_device(device_id)
        desktop_id, desktop_stamp = self.store.write_item(desktop_id, device_id, device_object)
        self.desktop_items[desktop_id] = desktop_stamp
        return entry_for(device_id, desktop_id, self.device_items[device_id], desktop_stamp)

    async def copy_to_device(self, desktop_id, device_id):
        device_object = self.store.read_item(desktop_id, device_id)
        if device_object is None:
            raise SyncError(f"{self.store.describe(desktop_id)} can't be converted for the device")
        device_id, device_stamp = await self.device.write(device_id, device_object)
        self.device_items[device_id] = device_stamp
        written = await self.device.written(device_id, device_object)
        new_stamp = self.store.device_updated(desktop_id, device_id, written)
        if new_stamp:
            self.desktop_items[desktop_id] = new_stamp
        return entry_for(device_id, desktop_id, device_stamp, self.desktop_items[desktop_id])

    async def keep_both(self, device_id, desktop_id):
        device_object = await self.read_device(device_id)
        copy_id, copy_stamp = self.store.write_item(None, None, device_object)
        self.desktop_items[copy_id] = copy_stamp
        entries = [await self.copy_to_device(desktop_id, device_id), await self.copy_to_device(copy_id, None)]
        return entries

    async def resolve(self, action, entry):
        device_id, desktop_id = action.device_id, action.desktop_id
        if action.resolution == "device":
            return [await self.copy_to_desktop(device_id, desktop_id)]
        if action.resolution == "desktop":
            return [await self.copy_to_device(desktop_id, device_id)]
        if action.resolution == "keep_both":
            return await self.keep_both(device_id, desktop_id)
        await self.leave_unresolved(action)
        return [entry] if entry else []

    async def leave_unresolved(self, action):
        device_id, desktop_id = action.device_id, action.desktop_id
        device_object = self.read_ahead.get(device_id) or await self.device.read(device_id)
        self.read_ahead[device_id] = device_object
        desktop_details, device_details = self.store.describe_conflict(desktop_id, device_id, device_object)
        self.unresolved.append({
            "device_id": device_id, "desktop_id": desktop_id, "description": action.description,
            "desktop": list(desktop_details), "device": list(device_details),
            "detected": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    async def perform(self, action, entry):
        if action.action == MATCH:
            return [entry_for(action.device_id, action.desktop_id, self.device_items[action.device_id],
                              self.desktop_items[action.desktop_id])]
        if action.action == CONFLICT:
            return await self.resolve(action, entry)
        if action.action == DELETE and action.direction == TO_DESKTOP:
            self.store.delete_item(action.desktop_id, action.device_id)
            return []
        if action.action == DELETE:
            await self.device.delete(action.device_id)
            return []
        if action.direction == TO_DESKTOP:
            return [await self.copy_to_desktop(action.device_id, action.desktop_id)]
        return [await self.copy_to_device(action.desktop_id, action.device_id)]

    async def apply(self, planned):
        total = len(planned)
        for index, (action, entry) in enumerate(planned):
            self.report.actions.append(action)
            self.progress(SyncProgress("apply", self.object_type.key, index, total, str(action)))
            if self.dry_run:
                continue
            try:
                self.mapping.extend(await self.perform(action, entry))
                action.applied = True
            except ConnectionError:
                self.mapping.extend(pending for _, pending in planned[index:] if pending)
                raise
            except (RapiError, OSError, ValueError, SyncError, ProviderError) as error:
                log.info("%s failed: %s", action, error)
                action.error = str(error)
                if entry:
                    self.mapping.append(entry)
        self.progress(SyncProgress("apply", self.object_type.key, total, total, ""))


def device_source_for(client, object_type, options, provider=None):
    if object_type.kind == KIND_FILES:
        folders = provider.device_folders(object_type) if provider is not None else None
        if folders is not None:
            return DeviceFolder(client, folders.folders, folders.depth, folders.extensions)
        return DeviceFolder(client, options.file_folders, options.file_depth)
    if object_type.kind == KIND_MAIL:
        return DeviceMailbox(client)
    return DeviceDatabase(client, object_type.database)


def selected_types(provider_class, options):
    available = list(provider_class.object_types)
    if options.object_types is None:
        return available
    wanted = list(options.object_types)
    unknown = [key for key in wanted if key not in {object_type.key for object_type in available}]
    if unknown:
        raise ValueError(f"provider {provider_class.name} does not handle {', '.join(unknown)}")
    return [object_type for object_type in available if object_type.key in wanted]


def type_assignments(providers, options):
    if options.provider not in providers:
        raise ValueError(f"no sync provider called {options.provider!r}; have {', '.join(sorted(providers))}")
    primary = providers[options.provider]
    assignments = {object_type.key: (primary, object_type) for object_type in primary.object_types}
    for key, name in (options.type_providers or {}).items():
        if name not in providers:
            raise ValueError(f"no sync provider called {name!r} for {key}; have {', '.join(sorted(providers))}")
        provider_class = providers[name]
        object_type = next((candidate for candidate in provider_class.object_types if candidate.key == key), None)
        if object_type is None:
            raise ValueError(f"provider {name} does not handle {key}")
        assignments[key] = (provider_class, object_type)
    if options.object_types is None:
        return list(assignments.values())
    unknown = [key for key in options.object_types if key not in assignments]
    if unknown:
        raise ValueError(f"provider {primary.name} does not handle {', '.join(unknown)}")
    return [assignment for key, assignment in assignments.items() if key in options.object_types]


def available_object_types(providers, options):
    try:
        return [object_type for _, object_type in type_assignments(providers, SyncOptions.from_dict(
            {**options.to_dict(), "object_types": None}))]
    except ValueError:
        return []


def report_progress(progress):
    def emit(update):
        if progress:
            progress(update)
    return emit


async def synchronize(client, partnership=None, options=None, progress=None, providers=None, first_sync=None):
    emit = report_progress(progress)
    device = await read_device_info(client)
    if partnership is None:
        partnership = (await find_partnership(client)).partnership
        if partnership is None:
            raise NoPartnership(_("{device} is connected as a guest; set up a partnership before synchronizing").format(
                device=device.name))
    options = options or partnership.load_options()
    for key, policy in options.conflict.items():
        if policy not in CONFLICT_POLICIES:
            raise ValueError(f"conflict policy for {key} must be one of {', '.join(CONFLICT_POLICIES)}")
    providers = providers or load_providers()
    assignments = type_assignments(providers, options)
    provider_class = providers[options.provider]
    report = SyncReport(device=device.name, provider=options.provider, dry_run=options.dry_run)
    instances = {}
    state = partnership.load_state()
    emit(SyncProgress("start", message=_("Synchronizing {device} with {provider}").format(
        device=device.name, provider=_(provider_class.display_name or provider_class.name))))
    try:
        for assigned_class, object_type in assignments:
            provider = instances.get(assigned_class.name)
            if provider is None:
                try:
                    provider = open_provider(assigned_class, device, partnership, options, emit)
                except (OSError, ValueError, ProviderError) as error:
                    report.skipped_types.append(object_type.key)
                    report.errors.append(f"{object_type.display_name}: {error}")
                    continue
                instances[assigned_class.name] = provider
            try:
                await synchronize_type(client, provider, object_type, options, state, report, emit, first_sync)
            except ProviderError as error:
                report.skipped_types.append(object_type.key)
                report.errors.append(f"{object_type.display_name}: {error}")
    finally:
        for provider in instances.values():
            provider.close()
        if not options.dry_run:
            state["device"] = device.name
            state["last_sync"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            state["last_result"] = report.summary()
            partnership.save_state(state)
    emit(SyncProgress("done", message=report.summary()))
    return report


def open_provider(provider_class, device, partnership, options, emit):
    settings = effective_settings(provider_class, options)
    context = ProviderContext(device, partnership.directory, settings,
                              lambda text: emit(SyncProgress("message", message=text)))
    return provider_class(context)


async def first_sync_mode(sync, stored, provider, first_sync, report):
    if stored.get("provider") == provider.name or not first_sync:
        return FIRST_SYNC_COMBINE
    if not sync.device_items or not sync.desktop_items:
        return FIRST_SYNC_COMBINE
    choice = await answer(first_sync, FirstSync(sync.object_type, len(sync.device_items), len(sync.desktop_items)))
    if choice not in FIRST_SYNC_CHOICES:
        choice = FIRST_SYNC_SKIP
    report.first_sync[sync.object_type.key] = choice
    return choice


async def synchronize_type(client, provider, object_type, options, state, report, emit, first_sync=None):
    emit(SyncProgress("scan", object_type.key, message=_("Checking {type}").format(type=_(object_type.display_name))))
    source = device_source_for(client, object_type, options, provider)
    try:
        await source.open()
    except RapiError as error:
        report.skipped_types.append(object_type.key)
        report.errors.append(f"{object_type.display_name}: {error}")
        return
    try:
        store = provider.open_store(object_type)
    except BaseException:
        await source.close()
        raise
    stored = state["types"].get(object_type.key, {})
    same_provider = stored.get("provider") == provider.name
    previous = stored.get("items", []) if same_provider else []
    resolutions = stored.get("resolutions", {}) if same_provider else {}
    sync = TypeSync(object_type, source, store, options.conflict_policy(object_type), report, emit, options.dry_run,
                    resolutions)
    try:
        await sync.list_both()
        mode = await first_sync_mode(sync, stored, provider, first_sync, report)
        if mode == FIRST_SYNC_SKIP:
            report.skipped_types.append(object_type.key)
            return
        planned = await sync.plan(previous, mode)
        try:
            await sync.apply(planned)
            finish = getattr(source, "finish", None)
            if finish is not None and not options.dry_run:
                await finish(store)
        finally:
            if not options.dry_run:
                state["types"][object_type.key] = {
                    "provider": provider.name, "items": sync.mapping, "unresolved": sync.unresolved,
                }
    finally:
        store.close()
        await source.close()


@dataclass
class UnresolvedItem:
    object_type: str
    device_id: str
    desktop_id: str
    description: str = ""
    desktop: list = field(default_factory=list)
    device: list = field(default_factory=list)
    resolution: str = "skip"


def unresolved_items(partnership):
    items = []
    for key, stored in sorted(partnership.load_state().get("types", {}).items()):
        resolutions = stored.get("resolutions", {})
        for entry in stored.get("unresolved", []):
            device_id, desktop_id = entry["device_id"], entry["desktop_id"]
            description = entry.get("description", "")
            items.append(UnresolvedItem(key, device_id, desktop_id, description, entry.get("desktop") or [description],
                                        entry.get("device") or [device_id],
                                        resolutions.get(conflict_key(device_id, desktop_id), "skip")))
    return items


def set_resolutions(partnership, items):
    state = partnership.load_state()
    for item in items:
        if item.resolution not in RESOLUTION_CHOICES:
            raise ValueError(f"resolution must be one of {', '.join(RESOLUTION_CHOICES)}")
        stored = state["types"].get(item.object_type)
        if stored is None:
            continue
        resolutions = stored.setdefault("resolutions", {})
        key = conflict_key(item.device_id, item.desktop_id)
        if item.resolution == "skip":
            resolutions.pop(key, None)
        else:
            resolutions[key] = item.resolution
    partnership.save_state(state)
