import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from ....i18n import N_, _
from ...objects import CALENDAR, CONTACTS, TASKS
from ...pim.text import parse_line, unfold
from ...provider import Provider, ProviderError
from ...settings_schema import Setting
from ...state import write_json_atomically
from ..pim_store import RemotePimStore
from .dav import (
    D, KIND_ADDRESS_BOOK, KIND_CALENDAR, AuthenticationError, DavClient, DavError, PreconditionFailed, calendar_query_body,
    normalized_href, same_resource,
)

CACHE_FOLDER = "caldav"
STATE_VERSION = 1
CONTENT_TYPES = {"VCARD": "text/vcard", "VEVENT": "text/calendar", "VTODO": "text/calendar"}
EXTENSIONS = {"VCARD": ".vcf", "VEVENT": ".ics", "VTODO": ".ics"}
CALENDAR_COMPONENTS = ("VEVENT", "VTODO", "VJOURNAL")
INVALID_SYNC_TOKEN_STATUSES = (400, 403, 409, 412, 507)
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.@-]{1,120}$")


def component_of(text, kind):
    if kind == KIND_ADDRESS_BOOK:
        return "VCARD"
    for raw in unfold(text):
        line = parse_line(raw)
        if line.name == "BEGIN" and line.value.strip().upper() in CALENDAR_COMPONENTS:
            return line.value.strip().upper()
    return ""


def resource_name(uid, component):
    stem = uid if SAFE_NAME.match(uid or "") else hashlib.sha1((uid or "").encode("utf-8")).hexdigest()
    return stem + EXTENSIONS[component]


def utc_text(moment):
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class DavStore(RemotePimStore):
    def __init__(self, object_type, client, collection, cache_directory, os_major, past_days=0, vcard_version="3.0"):
        super().__init__(object_type, cache_directory / "raw", os_major)
        self.client = client
        self.collection = collection
        self.past_days = past_days
        self.vcard_version = vcard_version
        self.state_path = cache_directory / f"{object_type.key}.json"
        self.state = self.load_state()

    def load_state(self):
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        if state.get("version") != STATE_VERSION or state.get("collection") != self.collection.url:
            state = {"version": STATE_VERSION, "collection": self.collection.url, "sync_token": "", "items": {}}
        return state

    def save_state(self):
        write_json_atomically(self.state_path, self.state)

    @property
    def items(self):
        return self.state["items"]

    def collection_href(self):
        return normalized_href(self.collection.url)

    def list_remote(self):
        try:
            if self.collection.sync_supported and not self.window_start():
                self.synchronize_listing()
            else:
                self.full_listing()
        except AuthenticationError as error:
            raise ProviderError(_("{error}; check caldav_username and caldav_password").format(error=error)) from None
        except DavError as error:
            raise ProviderError(str(error)) from None
        self.save_state()
        return {href: entry["etag"] for href, entry in self.items.items() if entry.get("component") == self.codec.component}

    def window_start(self):
        if self.object_type.key != CALENDAR.key or not self.past_days:
            return None
        return utc_text(datetime.now(timezone.utc) - timedelta(days=self.past_days))

    def synchronize_listing(self):
        try:
            entries, token = self.client.sync_collection(self.collection.url, self.state["sync_token"])
        except DavError as error:
            if error.status not in INVALID_SYNC_TOKEN_STATUSES:
                raise
            if not self.state["sync_token"]:
                self.collection.sync_supported = False
                self.full_listing()
                return
            self.state["sync_token"] = ""
            self.state["items"] = {}
            entries, token = self.client.sync_collection(self.collection.url, "")
        changed = []
        for entry in entries:
            href = normalized_href(entry.href)
            if href.rstrip("/") == self.collection_href().rstrip("/") or href.endswith("/"):
                continue
            if entry.status == 404:
                self.items.pop(href, None)
                continue
            etag = entry.text(D + "getetag")
            known = self.items.get(href)
            if known and known.get("etag") == etag and known.get("component"):
                continue
            self.items[href] = {"etag": etag, "component": ""}
            changed.append(href)
        self.fetch_many(changed)
        self.state["sync_token"] = token

    def full_listing(self):
        if self.collection.kind == KIND_CALENDAR:
            entries, _sync_token = self.client.report(self.collection.url, calendar_query_body(self.codec.component,
                                                                                               self.window_start()), 1)
        else:
            entries, _final_url = self.client.propfind(self.collection.url, "<d:getetag/><d:resourcetype/>", 1)
        listed = {}
        for entry in entries:
            href = normalized_href(entry.href)
            if href.endswith("/") or entry.resource_types() or entry.status != 200:
                continue
            listed[href] = entry.text(D + "getetag")
        changed = [href for href, etag in listed.items() if self.items.get(href, {}).get("etag") != etag]
        self.state["items"] = {href: {"etag": etag, "component": self.codec.component} for href, etag in listed.items()}
        self.fetch_many(changed)

    def fetch_many(self, hrefs):
        if not hrefs:
            return
        try:
            fetched = self.client.multiget(self.collection.url, self.collection.kind, hrefs)
        except DavError:
            fetched = {}
        for href in hrefs:
            if href in fetched:
                text, etag = fetched[href]
            else:
                try:
                    text, etag = self.client.get(href)
                except DavError as error:
                    if error.status == 404:
                        self.items.pop(href, None)
                        continue
                    raise
            self.texts[href] = text
            self.items[href] = {"etag": etag or self.items.get(href, {}).get("etag", ""),
                                "component": component_of(text, self.collection.kind)}

    def fetch_text(self, item_id):
        try:
            return self.client.get(item_id)[0]
        except DavError as error:
            raise ProviderError(str(error)) from None

    def put_text(self, item_id, text, uid):
        component = self.codec.component
        if item_id:
            url = self.client.absolute(item_id, self.collection.url)
            etag = self.items.get(item_id, {}).get("etag") or None
        else:
            url = self.collection.url + resource_name(uid, component)
            etag = None
        try:
            new_etag = self.client.put(url, text, CONTENT_TYPES[component], etag)
        except PreconditionFailed:
            raise ProviderError(_("{name} was changed on the server meanwhile; it will be compared again at the next sync").format(
                name=self.describe(item_id) if item_id else url)) from None
        except DavError as error:
            raise ProviderError(str(error)) from None
        href = normalized_href(url)
        self.items[href] = {"etag": new_etag, "component": component}
        self.save_state()
        return href, new_etag or hashlib.sha1(text.encode("utf-8")).hexdigest()

    def delete_remote(self, item_id):
        etag = self.items.get(item_id, {}).get("etag") or None
        try:
            self.client.delete(self.client.absolute(item_id, self.collection.url), etag)
        except PreconditionFailed:
            raise ProviderError(_("{name} was changed on the server meanwhile; it was not deleted").format(
                name=self.describe(item_id))) from None
        except DavError as error:
            raise ProviderError(str(error)) from None
        self.items.pop(item_id, None)
        self.save_state()

    def close(self):
        self.save_state()


class CalDavProvider(Provider):
    name = "caldav"
    display_name = N_("CalDAV and CardDAV")
    object_types = (CONTACTS, CALENDAR, TASKS)
    settings_schema = (
        Setting("caldav_url", N_("Server address"), "string",
                help=N_("For example https://caldav.icloud.com, https://caldav.fastmail.com, "
                        "https://cloud.example.com/remote.php/dav or http://localhost:5232. A calendar's own address works too.")),
        Setting("caldav_contacts_url", N_("Contacts server address"), "string",
                help=N_("Where the address books are, if not on the same server: https://contacts.icloud.com, "
                        "https://carddav.fastmail.com. Empty: the server address.")),
        Setting("caldav_username", N_("User name"), "string"),
        Setting("caldav_password", N_("Password"), "string", secret=True,
                help=N_("Use an app password where the service offers one. Saved in the system keyring when the keyring "
                        "package is installed; otherwise saved unencrypted in the settings file.")),
        Setting("caldav_address_book", N_("Address book"), "string",
                help=N_("Name or address of the address book for contacts. Empty: the first one.")),
        Setting("caldav_calendar", N_("Calendar"), "string",
                help=N_("Name or address of the calendar for appointments. Empty: the first one.")),
        Setting("caldav_task_list", N_("Task list"), "string",
                help=N_("Name or address of the calendar or list for tasks. Empty: the first one that holds tasks.")),
        Setting("caldav_past_days", N_("Past appointments (days)"), "int", 0, minimum=0,
                help=N_("Only synchronize appointments from this many days ago onwards. 0: all of them.")),
        Setting("caldav_vcard_version", N_("vCard version for new contacts"), "choice", "3.0",
                choices=[("3.0", "vCard 3.0"), ("4.0", "vCard 4.0")],
                help=N_("3.0 suits iCloud and most servers. Existing contacts keep their version.")),
    )

    def __init__(self, context):
        super().__init__(context)
        self.clients = {}
        self.collections = {}
        self.cache_directory = context.partnership_directory / CACHE_FOLDER

    def client_for(self, url):
        if not url:
            raise ProviderError(_("set the server address first: classicsync plugin configure caldav caldav_url=..."))
        if url not in self.clients:
            settings = self.context.settings
            try:
                self.clients[url] = DavClient(url, settings.get("caldav_username") or "", settings.get("caldav_password") or "")
            except DavError as error:
                raise ProviderError(str(error)) from None
        return self.clients[url]

    def available_collections(self, client, kind):
        key = (client.base_url, kind)
        if key not in self.collections:
            try:
                self.collections[key] = client.collections(kind)
            except AuthenticationError as error:
                raise ProviderError(_("{error}; check caldav_username and caldav_password").format(error=error)) from None
            except DavError as error:
                raise ProviderError(str(error)) from None
        return self.collections[key]

    def choose_collection(self, client, kind, component, wanted, setting_key):
        collections = [collection for collection in self.available_collections(client, kind) if collection.holds(component)]
        if wanted:
            for collection in collections:
                if collection.name.lower() == wanted.lower() or same_resource(client.absolute(wanted), collection.url):
                    return collection
            names = ", ".join(collection.label() for collection in collections) or _("none")
            raise ProviderError(_("no collection called {wanted!r} on {server} ({key}); found: {names}").format(
                wanted=wanted, server=client.base_url, key=setting_key, names=names))
        if not collections:
            raise ProviderError(_("found nothing on {server} that holds {component}").format(
                server=client.base_url, component=component))
        if component == "VTODO":
            exclusive = [collection for collection in collections if collection.components == frozenset({"VTODO"})]
            collections = exclusive or collections
        return collections[0]

    def open_store(self, object_type):
        settings = self.context.settings
        if object_type.key == CONTACTS.key:
            client = self.client_for(settings.get("caldav_contacts_url") or settings.get("caldav_url"))
            collection = self.choose_collection(client, KIND_ADDRESS_BOOK, "VCARD", settings.get("caldav_address_book"),
                                                "caldav_address_book")
        elif object_type.key == CALENDAR.key:
            client = self.client_for(settings.get("caldav_url"))
            collection = self.choose_collection(client, KIND_CALENDAR, "VEVENT", settings.get("caldav_calendar"), "caldav_calendar")
        elif object_type.key == TASKS.key:
            client = self.client_for(settings.get("caldav_url"))
            collection = self.choose_collection(client, KIND_CALENDAR, "VTODO", settings.get("caldav_task_list"), "caldav_task_list")
        else:
            raise ValueError(f"caldav provider does not handle {object_type.key}")
        self.context.message(_("{type}: {collection}").format(type=_(object_type.display_name), collection=collection.label()))
        return DavStore(object_type, client, collection, self.cache_directory, self.context.device.os_major,
                        settings.get("caldav_past_days") or 0, settings.get("caldav_vcard_version") or "3.0")

    def close(self):
        for client in self.clients.values():
            client.close()


PROVIDERS = [CalDavProvider]
