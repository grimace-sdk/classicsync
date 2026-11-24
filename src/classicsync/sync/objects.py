from dataclasses import dataclass, field

from ..i18n import N_

KIND_DATABASE = "database"
KIND_FILES = "files"
KIND_MAIL = "mail"


@dataclass(frozen=True)
class ObjectType:
    key: str
    name: str
    display_name: str
    kind: str = KIND_DATABASE
    database: str = ""
    conflict_default: str = "skip"


FILES = ObjectType("files", "File", N_("Files"), KIND_FILES, conflict_default="keep_both")
CONTACTS = ObjectType("contacts", "Contact", N_("Contacts"), database="Contacts Database")
CALENDAR = ObjectType("calendar", "Appointment", N_("Calendar"), database="Appointments Database")
TASKS = ObjectType("tasks", "Task", N_("Tasks"), database="Tasks Database")
MAIL = ObjectType("mail", "Inbox", N_("Inbox"), KIND_MAIL, database="\\PMAILDB", conflict_default="device")

BUILTIN_OBJECT_TYPES = {object_type.key: object_type for object_type in (FILES, CONTACTS, CALENDAR, TASKS)}


@dataclass
class DeviceRecord:
    properties: list
    oid: int = 0


@dataclass
class DeviceFile:
    path: str
    data: bytes
    modified: int = 0
    attributes: int = 0


@dataclass
class DeviceInfo:
    name: str = ""
    os_major: int = 0
    os_minor: int = 0
    extra: dict = field(default_factory=dict)
