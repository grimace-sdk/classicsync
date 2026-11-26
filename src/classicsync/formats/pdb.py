import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta

HEADER = struct.Struct(">32sHHIIIIII4s4sIIH")
RECORD_ENTRY = struct.Struct(">IB3s")
RESOURCE_ENTRY = struct.Struct(">4sHI")
FILLER = b"\0\0"
NAME_LENGTH = 32
PALM_EPOCH = datetime(1904, 1, 1)

ATTRIBUTE_RESOURCE = 0x0001
ATTRIBUTE_OPEN = 0x8000


class PdbError(ValueError):
    pass


def palm_seconds(moment):
    if moment is None:
        return 0
    return max(0, int((moment - PALM_EPOCH).total_seconds()))


def from_palm_seconds(seconds):
    return PALM_EPOCH + timedelta(seconds=seconds) if seconds else None


@dataclass
class PdbRecord:
    data: bytes
    attributes: int = 0
    unique_id: int = 0


@dataclass
class PdbResource:
    type: str
    id: int
    data: bytes


@dataclass
class PalmDatabase:
    name: str
    type: str
    creator: str
    attributes: int = 0
    version: int = 0
    created: datetime = None
    modified: datetime = None
    backed_up: datetime = None
    modification_number: int = 0
    app_info: bytes = b""
    sort_info: bytes = b""
    records: list = field(default_factory=list)
    resources: list = field(default_factory=list)

    @property
    def is_resource(self):
        return bool(self.attributes & ATTRIBUTE_RESOURCE)

    @property
    def extension(self):
        return ".prc" if self.is_resource else ".pdb"


def four_cc(text):
    return text.encode("latin-1")[:4].ljust(4, b"\0")


def write_pdb(database):
    resource = database.is_resource
    entries = database.resources if resource else database.records
    entry_size = RESOURCE_ENTRY.size if resource else RECORD_ENTRY.size
    offset = HEADER.size + len(entries) * entry_size + len(FILLER)
    app_info_offset = sort_info_offset = 0
    if not resource and database.app_info:
        app_info_offset = offset
        offset += len(database.app_info)
    if not resource and database.sort_info:
        sort_info_offset = offset
        offset += len(database.sort_info)
    header = HEADER.pack(database.name.encode("latin-1")[:NAME_LENGTH - 1].ljust(NAME_LENGTH, b"\0"),
                         database.attributes & ~ATTRIBUTE_OPEN, database.version, palm_seconds(database.created),
                         palm_seconds(database.modified), palm_seconds(database.backed_up), database.modification_number,
                         app_info_offset, sort_info_offset, four_cc(database.type), four_cc(database.creator), 0, 0, len(entries))
    table = bytearray()
    for entry in entries:
        if resource:
            table += RESOURCE_ENTRY.pack(four_cc(entry.type), entry.id, offset)
        else:
            table += RECORD_ENTRY.pack(offset, entry.attributes, entry.unique_id.to_bytes(3, "big"))
        offset += len(entry.data)
    body = b"" if resource else database.app_info + database.sort_info
    return header + bytes(table) + FILLER + body + b"".join(entry.data for entry in entries)


def read_pdb(data):
    if len(data) < HEADER.size:
        raise PdbError("too short for a Palm database")
    (name, attributes, version, created, modified, backed_up, modification_number, app_info_offset, sort_info_offset,
     kind, creator, _seed, _next_list, count) = HEADER.unpack_from(data)
    database = PalmDatabase(name.split(b"\0")[0].decode("latin-1"), kind.decode("latin-1"), creator.decode("latin-1"),
                            attributes, version, from_palm_seconds(created), from_palm_seconds(modified),
                            from_palm_seconds(backed_up), modification_number)
    resource = database.is_resource
    entry = RESOURCE_ENTRY if resource else RECORD_ENTRY
    if HEADER.size + count * entry.size > len(data):
        raise PdbError("entry list runs past the end of the file")
    entries = [entry.unpack_from(data, HEADER.size + index * entry.size) for index in range(count)]
    offsets = [values[2] if resource else values[0] for values in entries]
    boundaries = [offset for offset in (app_info_offset, sort_info_offset) if offset] + offsets + [len(data)]
    if boundaries != sorted(boundaries) or boundaries[-1] > len(data):
        raise PdbError("data offsets are out of order")

    def block(start):
        following = [boundary for boundary in boundaries if boundary > start]
        return data[start:following[0] if following else len(data)]

    if app_info_offset:
        database.app_info = block(app_info_offset)
    if sort_info_offset:
        database.sort_info = block(sort_info_offset)
    for index, values in enumerate(entries):
        end = offsets[index + 1] if index + 1 < len(offsets) else len(data)
        payload = data[offsets[index]:end]
        if resource:
            database.resources.append(PdbResource(values[0].decode("latin-1"), values[1], payload))
        else:
            database.records.append(PdbRecord(payload, values[1], int.from_bytes(values[2], "big")))
    return database
