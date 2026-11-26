import re

from ..i18n import N_, _
from ..sync.objects import CALENDAR, CONTACTS, TASKS, DeviceFile, DeviceRecord
from ..sync.providers.notes.provider import NOTES, TEXT_EXTENSION
from . import convert, records
from .backup import backup_handheld
from .conduit import PRIORITY_LAST, FreeformConduit, RecordConduit

MEMO_LIMIT = 4095
TITLE_LIMIT = 40
UNSAFE_TITLE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
BACKUP_FOLDER = "Backup"


class PimConduit(RecordConduit):
    to_properties = None
    from_properties = None

    def to_desktop(self, record, category, secret):
        return DeviceRecord(self.to_properties(record, category, secret))

    def from_desktop(self, device_object, base):
        record = self.from_properties(device_object.properties, base)
        category, secret = convert.category_and_secret(device_object.properties)
        return record, category, secret


class AddressConduit(PimConduit):
    name = "address"
    display_name = N_("Address Book")
    creators = ("addr",)
    database = "AddressDB"
    object_type = CONTACTS
    parse = staticmethod(records.parse_address)
    build = staticmethod(records.build_address)
    to_properties = staticmethod(convert.address_to_properties)
    from_properties = staticmethod(convert.properties_to_address)


class DatebookConduit(PimConduit):
    name = "datebook"
    display_name = N_("Date Book")
    creators = ("date",)
    database = "DatebookDB"
    object_type = CALENDAR
    parse = staticmethod(records.parse_appointment)
    build = staticmethod(records.build_appointment)
    to_properties = staticmethod(convert.appointment_to_properties)
    from_properties = staticmethod(convert.properties_to_appointment)


class ToDoConduit(PimConduit):
    name = "todo"
    display_name = N_("To Do List")
    creators = ("todo",)
    database = "ToDoDB"
    object_type = TASKS
    parse = staticmethod(records.parse_todo)
    build = staticmethod(records.build_todo)
    to_properties = staticmethod(convert.todo_to_properties)
    from_properties = staticmethod(convert.properties_to_todo)


def memo_title(text):
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    title = UNSAFE_TITLE.sub(" ", first).strip(" .")
    return title[:TITLE_LIMIT].rstrip() or "Memo"


class MemoConduit(RecordConduit):
    name = "memo"
    display_name = N_("Memo Pad")
    creators = ("memo",)
    database = "MemoDB"
    object_type = NOTES
    parse = staticmethod(records.parse_memo)
    build = staticmethod(records.build_memo)

    def to_desktop(self, record, category, secret):
        name = memo_title(record) + TEXT_EXTENSION
        return DeviceFile(f"{category}/{name}" if category else name, record.encode("utf-8"))

    def from_desktop(self, device_object, base):
        text = device_object.data.decode("utf-8", errors="replace").replace("\r\n", "\n")[:MEMO_LIMIT]
        folder = device_object.path.rpartition("/")[0]
        return text, folder.split("/")[0] if folder else "", None


class BackupConduit(FreeformConduit):
    name = "backup"
    display_name = N_("Backup")
    priority = PRIORITY_LAST

    def claims(self, database):
        return False

    async def run(self, context):
        if context.dry_run:
            return
        result = await backup_handheld(context.client, context.folder / BACKUP_FOLDER)
        if result.written:
            context.log(_("Backed up {count} databases").format(count=len(result.written)))


CONDUITS = [AddressConduit, DatebookConduit, ToDoConduit, MemoConduit, BackupConduit]
