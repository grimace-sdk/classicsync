import struct
from dataclasses import dataclass, field
from datetime import date, time

ENCODING = "cp1252"
NO_DATE = 0xFFFF
NO_TIME = 0xFFFF
EPOCH_YEAR = 1904

CATEGORY_COUNT = 16
CATEGORY_NAME_SIZE = 16
CATEGORY_NAME_LIMIT = 15
CATEGORY_BLOCK_SIZE = 276
CATEGORY_NAMES_OFFSET = 2
CATEGORY_IDS_OFFSET = 2 + CATEGORY_COUNT * CATEGORY_NAME_SIZE
LAST_UNIQUE_ID_OFFSET = CATEGORY_IDS_OFFSET + CATEGORY_COUNT
DESKTOP_CATEGORY_ID_FIRST = 0x80
UNFILED = 0

ADDRESS_FIELD_COUNT = 19
ADDRESS_LAST_NAME, ADDRESS_FIRST_NAME, ADDRESS_COMPANY = 0, 1, 2
ADDRESS_PHONE_FIRST = 3
ADDRESS_PHONE_COUNT = 5
ADDRESS_STREET, ADDRESS_CITY, ADDRESS_STATE, ADDRESS_ZIP, ADDRESS_COUNTRY, ADDRESS_TITLE = 8, 9, 10, 11, 12, 13
ADDRESS_CUSTOM_FIRST = 14
ADDRESS_NOTE = 18
ADDRESS_LABEL_COUNT = 22
ADDRESS_LABELS_OFFSET = 282

PHONE_WORK, PHONE_HOME, PHONE_FAX, PHONE_OTHER, PHONE_EMAIL, PHONE_MAIN, PHONE_PAGER, PHONE_MOBILE = range(8)

DATEBOOK_ALARM = 0x4000
DATEBOOK_REPEAT = 0x2000
DATEBOOK_NOTE = 0x1000
DATEBOOK_EXCEPTIONS = 0x0800
DATEBOOK_DESCRIPTION = 0x0400

REPEAT_NONE, REPEAT_DAILY, REPEAT_WEEKLY, REPEAT_MONTHLY_BY_DAY, REPEAT_MONTHLY_BY_DATE, REPEAT_YEARLY = range(6)
ALARM_MINUTES, ALARM_HOURS, ALARM_DAYS = range(3)

TODO_COMPLETED = 0x80
TODO_PRIORITY_MASK = 0x7F


def decode_text(raw):
    return raw.decode(ENCODING, errors="replace")


def encode_text(text):
    return text.encode(ENCODING, errors="replace") + b"\0"


def split_strings(data, count=None):
    strings = []
    offset = 0
    while offset < len(data) and (count is None or len(strings) < count):
        end = data.find(b"\0", offset)
        if end < 0:
            end = len(data)
        strings.append(decode_text(data[offset:end]))
        offset = end + 1
    return strings, offset


def decode_date(value):
    if value == NO_DATE:
        return None
    try:
        return date((value >> 9) + EPOCH_YEAR, value >> 5 & 0x0F, value & 0x1F)
    except ValueError:
        return None


def encode_date(day):
    if day is None:
        return NO_DATE
    return (day.year - EPOCH_YEAR) << 9 | day.month << 5 | day.day


def decode_time(value):
    if value == NO_TIME:
        return None
    return time(min(value >> 8, 23), min(value & 0xFF, 59))


def encode_time(moment):
    return NO_TIME if moment is None else moment.hour << 8 | moment.minute


@dataclass
class Categories:
    names: list
    unique_ids: list
    renamed: int = 0
    last_unique_id: int = 0

    def name_of(self, index):
        return self.names[index] if 0 <= index < CATEGORY_COUNT else ""

    def index_of(self, name):
        wanted = name.strip().lower()
        for index, existing in enumerate(self.names):
            if existing and existing.lower() == wanted:
                return index
        return None

    def add(self, name):
        found = self.index_of(name)
        if found is not None:
            return found
        for index in range(1, CATEGORY_COUNT):
            if not self.names[index]:
                taken = set(self.unique_ids)
                unique_id = next(candidate for candidate in range(DESKTOP_CATEGORY_ID_FIRST, 0x100) if candidate not in taken)
                self.names[index] = name.strip()[:CATEGORY_NAME_LIMIT]
                self.unique_ids[index] = unique_id
                self.renamed |= 1 << index
                return index
        return None


def parse_categories(app_info):
    if len(app_info) < CATEGORY_BLOCK_SIZE:
        return Categories([""] * CATEGORY_COUNT, list(range(CATEGORY_COUNT)))
    renamed = struct.unpack_from(">H", app_info)[0]
    names = [decode_text(app_info[CATEGORY_NAMES_OFFSET + index * CATEGORY_NAME_SIZE:
                                  CATEGORY_NAMES_OFFSET + (index + 1) * CATEGORY_NAME_SIZE].split(b"\0")[0])
             for index in range(CATEGORY_COUNT)]
    unique_ids = list(app_info[CATEGORY_IDS_OFFSET:CATEGORY_IDS_OFFSET + CATEGORY_COUNT])
    return Categories(names, unique_ids, renamed, app_info[LAST_UNIQUE_ID_OFFSET])


def build_categories(categories, app_info):
    block = bytearray(app_info.ljust(CATEGORY_BLOCK_SIZE, b"\0"))
    struct.pack_into(">H", block, 0, categories.renamed)
    for index, name in enumerate(categories.names):
        encoded = name.encode(ENCODING, errors="replace")[:CATEGORY_NAME_LIMIT].ljust(CATEGORY_NAME_SIZE, b"\0")
        block[CATEGORY_NAMES_OFFSET + index * CATEGORY_NAME_SIZE:CATEGORY_NAMES_OFFSET + (index + 1) * CATEGORY_NAME_SIZE] = encoded
    block[CATEGORY_IDS_OFFSET:CATEGORY_IDS_OFFSET + CATEGORY_COUNT] = bytes(categories.unique_ids)
    block[LAST_UNIQUE_ID_OFFSET] = categories.last_unique_id
    return bytes(block)


@dataclass
class Address:
    fields: list = field(default_factory=lambda: [None] * ADDRESS_FIELD_COUNT)
    phone_labels: list = field(default_factory=lambda: [PHONE_WORK, PHONE_HOME, PHONE_FAX, PHONE_OTHER, PHONE_EMAIL])
    display_phone: int = 0

    def phones(self):
        return [(self.phone_labels[slot], self.fields[ADDRESS_PHONE_FIRST + slot]) for slot in range(ADDRESS_PHONE_COUNT)
                if self.fields[ADDRESS_PHONE_FIRST + slot]]


def parse_address(data):
    options, present = struct.unpack_from(">II", data)
    address = Address()
    address.phone_labels = [options >> (4 * slot) & 0x0F for slot in range(ADDRESS_PHONE_COUNT)]
    address.display_phone = options >> 20 & 0x0F
    strings, _ = split_strings(data[9:])
    values = iter(strings)
    for index in range(ADDRESS_FIELD_COUNT):
        if present & 1 << index:
            address.fields[index] = next(values, "")
    return address


def build_address(address):
    options = sum((label & 0x0F) << (4 * slot) for slot, label in enumerate(address.phone_labels[:ADDRESS_PHONE_COUNT]))
    options |= (address.display_phone & 0x0F) << 20
    present = 0
    body = bytearray()
    company_offset = 0
    for index, value in enumerate(address.fields):
        if not value:
            continue
        if index == ADDRESS_COMPANY:
            company_offset = len(body) + 1
        present |= 1 << index
        body += encode_text(value)
    return struct.pack(">IIB", options, present, company_offset) + bytes(body)


def parse_address_labels(app_info):
    return [decode_text(app_info[ADDRESS_LABELS_OFFSET + index * CATEGORY_NAME_SIZE:
                                 ADDRESS_LABELS_OFFSET + (index + 1) * CATEGORY_NAME_SIZE].split(b"\0")[0])
            for index in range(ADDRESS_LABEL_COUNT) if len(app_info) >= ADDRESS_LABELS_OFFSET + (index + 1) * CATEGORY_NAME_SIZE]


@dataclass
class Repeat:
    kind: int
    end: date = None
    frequency: int = 1
    repeat_on: int = 0
    start_of_week: int = 0


@dataclass
class Appointment:
    day: date
    start: time = None
    end: time = None
    description: str = ""
    note: str = ""
    alarm: tuple = None
    repeat: Repeat = None
    exceptions: list = field(default_factory=list)

    @property
    def untimed(self):
        return self.start is None


def parse_appointment(data):
    start, end, day, flags = struct.unpack_from(">HHHH", data)
    appointment = Appointment(decode_date(day), decode_time(start), decode_time(end))
    offset = 8
    if flags & DATEBOOK_ALARM:
        advance, unit = struct.unpack_from(">bB", data, offset)
        appointment.alarm = (advance, unit)
        offset += 2
    if flags & DATEBOOK_REPEAT:
        kind, _pad, repeat_end, frequency, repeat_on, start_of_week, _pad2 = struct.unpack_from(">BBHBBBB", data, offset)
        appointment.repeat = Repeat(kind, decode_date(repeat_end), frequency, repeat_on, start_of_week)
        offset += 8
    if flags & DATEBOOK_EXCEPTIONS:
        count = struct.unpack_from(">H", data, offset)[0]
        appointment.exceptions = [decode_date(value) for value in struct.unpack_from(f">{count}H", data, offset + 2)]
        offset += 2 + 2 * count
    wanted = [flag for flag in (DATEBOOK_DESCRIPTION, DATEBOOK_NOTE) if flags & flag]
    strings, _ = split_strings(data[offset:], len(wanted))
    for flag, text in zip(wanted, strings):
        if flag == DATEBOOK_DESCRIPTION:
            appointment.description = text
        else:
            appointment.note = text
    return appointment


def build_appointment(appointment):
    flags = 0
    body = bytearray()
    if appointment.alarm is not None:
        flags |= DATEBOOK_ALARM
        body += struct.pack(">bB", *appointment.alarm)
    if appointment.repeat is not None and appointment.repeat.kind != REPEAT_NONE:
        repeat = appointment.repeat
        flags |= DATEBOOK_REPEAT
        body += struct.pack(">BBHBBBB", repeat.kind, 0, encode_date(repeat.end), repeat.frequency, repeat.repeat_on,
                            repeat.start_of_week, 0)
    if appointment.exceptions:
        flags |= DATEBOOK_EXCEPTIONS
        body += struct.pack(f">H{len(appointment.exceptions)}H", len(appointment.exceptions),
                            *(encode_date(day) for day in appointment.exceptions))
    flags |= DATEBOOK_DESCRIPTION
    body += encode_text(appointment.description)
    if appointment.note:
        flags |= DATEBOOK_NOTE
        body += encode_text(appointment.note)
    start = encode_time(appointment.start)
    end = encode_time(appointment.end) if appointment.start is not None else NO_TIME
    return struct.pack(">HHHH", start, end, encode_date(appointment.day), flags) + bytes(body)


@dataclass
class ToDo:
    description: str = ""
    note: str = ""
    due: date = None
    priority: int = 1
    completed: bool = False


def parse_todo(data):
    due, packed = struct.unpack_from(">HB", data)
    strings, _ = split_strings(data[3:], 2)
    strings += [""] * (2 - len(strings))
    return ToDo(strings[0], strings[1], decode_date(due), packed & TODO_PRIORITY_MASK, bool(packed & TODO_COMPLETED))


def build_todo(todo):
    packed = (TODO_COMPLETED if todo.completed else 0) | (todo.priority & TODO_PRIORITY_MASK)
    return struct.pack(">HB", encode_date(todo.due), packed) + encode_text(todo.description) + encode_text(todo.note)


def parse_memo(data):
    return split_strings(data, 1)[0][0] if data else ""


def build_memo(text):
    return encode_text(text)
