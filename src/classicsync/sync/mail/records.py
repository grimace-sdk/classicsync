from dataclasses import dataclass, field

from ...rapi.cedb import CEVT_BLOB, CEVT_FILETIME, CEVT_LPWSTR, CEVT_UI2, CEVT_UI4, PropertyValue

MESSAGE_DATABASE = "\\PMAILDB"
HELPER_DATABASE = "\\PMAILDB2"

VERSION_1 = 0x0102
VERSION_2 = 0x0200
VERSION_3 = 0x0300

FOLDER_MASK = 0x000000FF
TARGET_MASK = 0x0000FF00
FOLDER_SENT = 0xFC
FOLDER_OUTBOX = 0xFD
FOLDER_INBOX = 0xFE
SPECIAL_FOLDERS = (FOLDER_INBOX, FOLDER_OUTBOX, FOLDER_SENT)
LAST_USER_FOLDER_V1 = 0x14
LAST_USER_FOLDER_V2 = 0xF8

STATUS_FREE = 0x00010000
STATUS_DELETE = 0x00020000
STATUS_COPY = 0x00040000
STATUS_MOVE = 0x00080000
STATUS_READ = 0x00100000
STATUS_SERVICE = 0x00200000
STATUS_COMPOSED = 0x00400000
STATUS_REMOTE = 0x00800000
STATUS_ATTACHMENTS = 0x40000000

ID_FOLDER = 0x40000000
ID_MESSAGE = 0x80000000
ID_KIND_MASK = 0xC0000000

V1_ID = (0x0000, CEVT_UI4)
V1_FLAGS = (0x0001, CEVT_UI4)
V1_MESSAGE_LENGTH = (0x0002, CEVT_UI4)
V1_BODY_LENGTH = (0x0003, CEVT_UI2)
V1_DATE = (0x0004, CEVT_FILETIME)
V1_SERVICE_ID = (0x0005, CEVT_LPWSTR)
V1_SERVICE_NAME = (0x0006, CEVT_LPWSTR)
V1_HEADERS = (0x0007, CEVT_BLOB)
V1_BODY = (0x0008, CEVT_LPWSTR)
V1_VERSION = (0x0009, CEVT_UI2)
V1_LAST_ID = (0x000A, CEVT_UI4)
V1_FOLDER_NAME = (0x000B, CEVT_LPWSTR)

V2_ID = (0x0000, CEVT_UI4)
V2_FLAGS = (0x0001, CEVT_UI4)
V2_MESSAGE_LENGTH = (0x0002, CEVT_UI4)
V2_BODY_LENGTH = (0x0003, CEVT_UI2)
V2_DATE = (0x0004, CEVT_FILETIME)
V2_FROM = (0x0005, CEVT_LPWSTR)
V2_PRESUBJECT = (0x0006, CEVT_LPWSTR)
V2_SUBJECT = (0x0007, CEVT_LPWSTR)
V2_HEADERS = (0x0008, CEVT_BLOB)
V2_SERVICE_OID = (0x0009, CEVT_UI4)
V2_BODY = (0x000A, CEVT_LPWSTR)
V2_VERSION = (0x000B, CEVT_UI2)
V2_LAST_ID = (0x000C, CEVT_UI4)
V2_ATTACHMENT_INFO = (0x000C, CEVT_UI4)
V2_ATTACHMENT_STRINGS = (0x000D, CEVT_BLOB)

V2_FOLDER_ID = (0x0000, CEVT_UI2)
V2_FOLDER_NAME = (0x0001, CEVT_LPWSTR)
V2_SERVICE_NAME = (0x0002, CEVT_LPWSTR)
V2_SERVICE_ID = (0x0003, CEVT_LPWSTR)
V2_SERVICE_MESSAGE_ID = (0x0004, CEVT_UI4)
V2_SERVICE_MESSAGE_OID = (0x0005, CEVT_UI4)
V3_FOLDER_PARENT = (0x0006, CEVT_UI2)

SUBJECT_PREFIXES = ("RE:", "FW:")
MAXIMUM_BODY_CHARACTERS = 0x7FE0
FROM = "From"
SUBJECT = "Subject"


@dataclass
class MailMessage:
    folder: str = ""
    flags: int = 0
    date: int = 0
    headers: list = field(default_factory=list)
    body: str = ""
    message_length: int = 0
    service_name: str = ""
    service_id: str = ""
    message_id: int = 0
    folder_id: int = 0
    oid: int = 0

    def header(self, name):
        return header_value(self.headers, name)

    @property
    def subject(self):
        return self.header(SUBJECT)

    @property
    def read(self):
        return bool(self.flags & STATUS_READ)

    @property
    def deleted(self):
        return bool(self.flags & STATUS_DELETE)


def values_by_key(properties):
    return {(prop.identifier, prop.value_type): prop.value for prop in properties if not prop.missing}


def header_value(headers, name):
    wanted = name.lower()
    return next((value for key, value in headers if key.lower() == wanted), "")


def without_headers(headers, names):
    unwanted = {name.lower() for name in names}
    return [(key, value) for key, value in headers if key.lower() not in unwanted]


def decode_headers(blob):
    if not blob:
        return []
    text = bytes(blob[:len(blob) - len(blob) % 2]).decode("utf-16-le", errors="replace")
    parts = text.split("\0")
    headers = []
    index = 0
    while index + 1 < len(parts) and parts[index]:
        headers.append((parts[index], parts[index + 1]))
        index += 2
    return headers


def encode_headers(headers):
    text = "".join(f"{name}\0{value}\0" for name, value in headers if name) + "\0"
    return text.encode("utf-16-le")


def split_subject(subject):
    for prefix in SUBJECT_PREFIXES:
        if subject[:len(prefix)].upper() == prefix:
            rest = subject[len(prefix):]
            stripped = rest.lstrip(" ")
            return subject[:len(subject) - len(stripped)], stripped
    return "", subject


def device_body(body):
    text = body.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    return text[:MAXIMUM_BODY_CHARACTERS]


def is_head_v1(values):
    return values.get(V1_ID) == 0 and V1_VERSION in values


def folder_from_v1(values):
    record_id = values.get(V1_ID)
    if record_id is None or record_id & ID_KIND_MASK != ID_FOLDER or V1_FOLDER_NAME not in values:
        return None
    return record_id & FOLDER_MASK, values[V1_FOLDER_NAME]


def is_message_v1(values):
    record_id = values.get(V1_ID)
    return record_id is not None and record_id & ID_MESSAGE != 0 and V1_FLAGS in values


def message_from_v1(properties, oid=0):
    values = values_by_key(properties)
    flags = values.get(V1_FLAGS, 0)
    return MailMessage(
        flags=flags & ~(FOLDER_MASK | TARGET_MASK), date=values.get(V1_DATE, 0),
        headers=decode_headers(values.get(V1_HEADERS, b"")), body=values.get(V1_BODY, ""),
        message_length=values.get(V1_MESSAGE_LENGTH, 0), service_name=values.get(V1_SERVICE_NAME, ""),
        service_id=values.get(V1_SERVICE_ID, ""), message_id=values.get(V1_ID, 0) & ~ID_MESSAGE,
        folder_id=flags & FOLDER_MASK, oid=oid,
    )


def flags_value(message):
    return (message.flags & ~(FOLDER_MASK | TARGET_MASK)) | (message.folder_id & FOLDER_MASK)


def v1_properties(message):
    body = device_body(message.body)
    return [
        PropertyValue(*V1_ID, (message.message_id | ID_MESSAGE) & 0xFFFFFFFF),
        PropertyValue(*V1_FLAGS, flags_value(message)),
        PropertyValue(*V1_MESSAGE_LENGTH, message.message_length or len(body)),
        PropertyValue(*V1_BODY_LENGTH, len(body)),
        PropertyValue(*V1_DATE, message.date),
        PropertyValue(*V1_SERVICE_ID, message.service_id),
        PropertyValue(*V1_SERVICE_NAME, message.service_name),
        PropertyValue(*V1_HEADERS, encode_headers(message.headers)),
        PropertyValue(*V1_BODY, body),
    ]


def v1_head_properties(version, last_id):
    return [PropertyValue(*V1_ID, 0), PropertyValue(*V1_VERSION, version), PropertyValue(*V1_LAST_ID, last_id)]


def v1_folder_properties(folder_id, name):
    return [PropertyValue(*V1_ID, ID_FOLDER | folder_id), PropertyValue(*V1_FOLDER_NAME, name)]


def is_head_v2(values):
    return values.get(V2_ID) == 0 and V2_VERSION in values


def is_message_v2(values):
    return V2_FLAGS in values and not is_head_v2(values)


def folder_from_v2(values):
    if V2_FOLDER_ID not in values or V2_FOLDER_NAME not in values:
        return None
    return values[V2_FOLDER_ID], values[V2_FOLDER_NAME]


def is_service_v2(values):
    return V2_SERVICE_NAME in values or V2_SERVICE_MESSAGE_OID in values


def message_from_v2(properties, service_properties=(), oid=0):
    values = values_by_key(properties)
    service = values_by_key(service_properties)
    flags = values.get(V2_FLAGS, 0)
    headers = decode_headers(values.get(V2_HEADERS, b""))
    subject = values.get(V2_PRESUBJECT, "") + values.get(V2_SUBJECT, "")
    leading = []
    if values.get(V2_FROM):
        leading.append((FROM, values[V2_FROM]))
    if subject:
        leading.append((SUBJECT, subject))
    return MailMessage(
        flags=flags & ~(FOLDER_MASK | TARGET_MASK), date=values.get(V2_DATE, 0),
        headers=leading + without_headers(headers, (FROM, SUBJECT)), body=values.get(V2_BODY, ""),
        message_length=values.get(V2_MESSAGE_LENGTH, 0), service_name=service.get(V2_SERVICE_NAME, ""),
        service_id=service.get(V2_SERVICE_ID, ""), message_id=values.get(V2_ID, 0),
        folder_id=flags & FOLDER_MASK, oid=oid,
    )


def v2_properties(message, service_oid=0):
    body = device_body(message.body)
    presubject, subject = split_subject(message.subject)
    properties = [
        PropertyValue(*V2_ID, message.message_id),
        PropertyValue(*V2_FLAGS, flags_value(message)),
        PropertyValue(*V2_MESSAGE_LENGTH, message.message_length or len(body)),
        PropertyValue(*V2_BODY_LENGTH, len(body)),
        PropertyValue(*V2_DATE, message.date),
        PropertyValue(*V2_FROM, message.header(FROM)),
        PropertyValue(*V2_PRESUBJECT, presubject),
        PropertyValue(*V2_SUBJECT, subject),
        PropertyValue(*V2_HEADERS, encode_headers(without_headers(message.headers, (FROM, SUBJECT)))),
        PropertyValue(*V2_BODY, body),
    ]
    if service_oid:
        properties.append(PropertyValue(*V2_SERVICE_OID, service_oid))
    return properties


def v2_head_properties(version, last_id):
    return [PropertyValue(*V2_ID, 0), PropertyValue(*V2_VERSION, version), PropertyValue(*V2_LAST_ID, last_id)]


def v2_folder_properties(folder_id, name, parent=None):
    properties = [PropertyValue(*V2_FOLDER_ID, folder_id), PropertyValue(*V2_FOLDER_NAME, name)]
    if parent is not None:
        properties.append(PropertyValue(*V3_FOLDER_PARENT, parent))
    return properties


def v2_service_properties(message, message_oid=0):
    properties = [
        PropertyValue(*V2_SERVICE_NAME, message.service_name),
        PropertyValue(*V2_SERVICE_ID, message.service_id),
        PropertyValue(*V2_SERVICE_MESSAGE_ID, message.message_id),
    ]
    if message_oid:
        properties.append(PropertyValue(*V2_SERVICE_MESSAGE_OID, message_oid))
    return properties

