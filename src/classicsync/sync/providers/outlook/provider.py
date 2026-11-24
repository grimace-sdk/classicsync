from datetime import date, timedelta

import pythoncom
import pywintypes
import win32com.client

from ....i18n import N_, _
from ...objects import CALENDAR, CONTACTS, TASKS
from ...provider import Provider, ProviderError
from ...settings_schema import Setting
from ..pim_store import RemotePimStore
from .mapping import DEFAULT_FOLDERS, ITEM_CLASSES, ITEM_TYPES, apply_text, item_in_range, item_stamp, item_text, resolve_folder

FOLDER_SETTINGS = {CONTACTS.key: "outlook_contacts_folder", CALENDAR.key: "outlook_calendar_folder", TASKS.key: "outlook_tasks_folder"}


class OutlookStore(RemotePimStore):
    vcard_version = "4.0"

    def __init__(self, object_type, cache_directory, os_major, namespace, folder, past_days, future_days):
        super().__init__(object_type, cache_directory, os_major)
        self.namespace = namespace
        self.folder = folder
        self.earliest = date.today() - timedelta(days=past_days)
        self.latest = date.today() + timedelta(days=future_days)
        self.items = {}

    def item(self, item_id):
        if item_id not in self.items:
            try:
                self.items[item_id] = self.namespace.GetItemFromID(item_id)
            except pywintypes.com_error as error:
                raise ProviderError(_("Outlook item {item} could not be opened: {error}").format(item=item_id, error=error)) from None
        return self.items[item_id]

    def list_remote(self):
        wanted_class = ITEM_CLASSES[self.object_type.key]
        self.items = {}
        try:
            for item in self.folder.Items:
                if item.Class != wanted_class or not item_in_range(self.object_type.key, item, self.earliest, self.latest):
                    continue
                self.items[item.EntryID] = item
        except pywintypes.com_error as error:
            raise ProviderError(_("Outlook could not list {folder}: {error}").format(folder=self.folder.Name, error=error)) from None
        return {item_id: item_stamp(item) for item_id, item in self.items.items()}

    def fetch_text(self, item_id):
        return item_text(self.object_type.key, self.item(item_id))

    def put_text(self, item_id, text, uid):
        try:
            item = self.item(item_id) if item_id else self.folder.Items.Add(ITEM_TYPES[self.object_type.key])
            apply_text(self.object_type.key, item, text, new=item_id is None)
            item.Save()
        except pywintypes.com_error as error:
            raise ProviderError(_("Outlook could not save an item: {error}").format(error=error)) from None
        self.items[item.EntryID] = item
        return item.EntryID, item_stamp(item)

    def delete_remote(self, item_id):
        try:
            self.item(item_id).Delete()
        except pywintypes.com_error as error:
            raise ProviderError(_("Outlook could not delete an item: {error}").format(error=error)) from None
        self.items.pop(item_id, None)


class OutlookProvider(Provider):
    name = "outlook"
    display_name = N_("Microsoft Outlook")
    object_types = (CONTACTS, CALENDAR, TASKS)
    settings_schema = (
        Setting("outlook_contacts_folder", N_("Contacts folder"), "string", "",
                help=N_("Outlook folder for contacts, such as Contacts\\Handheld or Mailbox\\Contacts. Empty: the default Contacts folder.")),
        Setting("outlook_calendar_folder", N_("Calendar folder"), "string", "",
                help=N_("Outlook folder for appointments. Empty: the default Calendar folder.")),
        Setting("outlook_tasks_folder", N_("Tasks folder"), "string", "",
                help=N_("Outlook folder for tasks. Empty: the default Tasks folder.")),
        Setting("outlook_past_days", N_("Past appointments (days)"), "int", 30, minimum=0,
                help=N_("Appointments that ended more than this many days ago are not synchronized.")),
        Setting("outlook_future_days", N_("Future appointments (days)"), "int", 365, minimum=0,
                help=N_("Appointments starting more than this many days ahead are not synchronized.")),
    )

    def __init__(self, context):
        super().__init__(context)
        pythoncom.CoInitialize()
        try:
            self.application = win32com.client.Dispatch("Outlook.Application")
            self.namespace = self.application.GetNamespace("MAPI")
        except pywintypes.com_error as error:
            pythoncom.CoUninitialize()
            raise ProviderError(_("Outlook is not available: {error}").format(error=error)) from None

    def open_store(self, object_type):
        settings = self.context.settings
        default_folder = self.namespace.GetDefaultFolder(DEFAULT_FOLDERS[object_type.key])
        path = settings.get(FOLDER_SETTINGS[object_type.key]) or ""
        try:
            folder = resolve_folder(self.namespace, default_folder, path)
        except LookupError:
            raise ProviderError(_("Outlook has no folder {path}").format(path=path)) from None
        return OutlookStore(object_type, self.context.partnership_directory / "outlook", self.context.device.os_major,
                            self.namespace, folder, settings.get("outlook_past_days", 30), settings.get("outlook_future_days", 365))

    def close(self):
        self.namespace = None
        self.application = None
        pythoncom.CoUninitialize()


PROVIDERS = [OutlookProvider]
