import struct
from dataclasses import dataclass

CAB_SIGNATURE = b"MSCF"
CAB_HEADER_SIZE = 36


@dataclass
class EmbeddedCabinet:
    offset: int
    size: int
    folder_count: int
    file_count: int

    def slice(self, data):
        return data[self.offset:self.offset + self.size]


def cabinet_header_at(data, offset):
    if offset + CAB_HEADER_SIZE > len(data) or data[offset:offset + 4] != CAB_SIGNATURE:
        return None
    (reserved1, size, reserved2, files_offset, reserved3,
     version_minor, version_major, folder_count, file_count) = struct.unpack_from("<IIIIIBBHH", data, offset + 4)
    if reserved1 or reserved2 or reserved3 or version_major != 1:
        return None
    if size < CAB_HEADER_SIZE or offset + size > len(data):
        return None
    if files_offset >= size or folder_count == 0 or file_count == 0:
        return None
    return EmbeddedCabinet(offset, size, folder_count, file_count)


def find_cabinets(data):
    cabinets = []
    position = data.find(CAB_SIGNATURE)
    while position >= 0:
        cabinet = cabinet_header_at(data, position)
        if cabinet:
            cabinets.append(cabinet)
            position = data.find(CAB_SIGNATURE, position + cabinet.size)
        else:
            position = data.find(CAB_SIGNATURE, position + 1)
    return cabinets


def embedded_cabinets(data):
    return [cabinet.slice(data) for cabinet in find_cabinets(data)]
