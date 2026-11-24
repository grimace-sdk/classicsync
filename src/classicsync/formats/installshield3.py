import struct
from dataclasses import dataclass
from pathlib import Path

SIGNATURE = 0x8C655D13

LITERAL_LENGTHS = [
    11, 124, 8, 7, 28, 7, 188, 13, 76, 4, 10, 8, 12, 10, 12, 10, 8, 23, 8,
    9, 7, 6, 7, 8, 7, 6, 55, 8, 23, 24, 12, 11, 7, 9, 11, 12, 6, 7, 22, 5,
    7, 24, 6, 11, 9, 6, 7, 22, 7, 11, 38, 7, 9, 8, 25, 11, 8, 11, 9, 12,
    8, 12, 5, 38, 5, 38, 5, 11, 7, 5, 6, 21, 6, 10, 53, 8, 7, 24, 10, 27,
    44, 253, 253, 253, 252, 252, 252, 13, 12, 45, 12, 45, 12, 61, 12, 45,
    44, 173,
]
LENGTH_LENGTHS = [2, 35, 36, 53, 38, 23]
DISTANCE_LENGTHS = [2, 20, 53, 230, 247, 151, 248]
LENGTH_BASE = [3, 2, 4, 5, 6, 7, 8, 9, 10, 12, 16, 24, 40, 72, 136, 264]
LENGTH_EXTRA = [0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8]
MAX_BITS = 13
END_OF_STREAM_LENGTH = 519


class InstallShield3Error(ValueError):
    pass


class Huffman:
    def __init__(self, compacted_lengths):
        lengths = []
        for value in compacted_lengths:
            repeat = (value >> 4) + 1
            length = value & 15
            lengths.extend([length] * repeat)
        self.count = [0] * (MAX_BITS + 1)
        for length in lengths:
            self.count[length] += 1
        offsets = [0] * (MAX_BITS + 1)
        for bit_length in range(1, MAX_BITS):
            offsets[bit_length + 1] = offsets[bit_length] + self.count[bit_length]
        self.symbol = [0] * len(lengths)
        for symbol_index, length in enumerate(lengths):
            if length != 0:
                self.symbol[offsets[length]] = symbol_index
                offsets[length] += 1


class BitReader:
    def __init__(self, data):
        self.data = data
        self.position = 0
        self.bit_buffer = 0
        self.bit_count = 0

    def bits(self, needed):
        value = self.bit_buffer
        while self.bit_count < needed:
            if self.position >= len(self.data):
                raise InstallShield3Error("compressed stream ended early")
            value |= self.data[self.position] << self.bit_count
            self.position += 1
            self.bit_count += 8
        self.bit_buffer = value >> needed
        self.bit_count -= needed
        return value & ((1 << needed) - 1)

    def decode(self, huffman):
        code = 0
        first = 0
        index = 0
        for length in range(1, MAX_BITS + 1):
            code |= self.bits(1) ^ 1
            count = huffman.count[length]
            if code < first + count:
                return huffman.symbol[index + (code - first)]
            index += count
            first += count
            first <<= 1
            code <<= 1
        raise InstallShield3Error("bad Huffman code")


LITERAL_CODE = Huffman(LITERAL_LENGTHS)
LENGTH_CODE = Huffman(LENGTH_LENGTHS)
DISTANCE_CODE = Huffman(DISTANCE_LENGTHS)


def explode(data):
    reader = BitReader(data)
    literal_mode = reader.bits(8)
    if literal_mode > 1:
        raise InstallShield3Error("bad literal flag")
    dictionary_bits = reader.bits(8)
    if dictionary_bits < 4 or dictionary_bits > 6:
        raise InstallShield3Error("bad dictionary size")
    output = bytearray()
    while True:
        if reader.bits(1):
            symbol = reader.decode(LENGTH_CODE)
            length = LENGTH_BASE[symbol] + reader.bits(LENGTH_EXTRA[symbol])
            if length == END_OF_STREAM_LENGTH:
                break
            extra_bits = 2 if length == 2 else dictionary_bits
            distance = reader.decode(DISTANCE_CODE) << extra_bits
            distance += reader.bits(extra_bits)
            distance += 1
            if distance > len(output):
                raise InstallShield3Error("distance too far back")
            start = len(output) - distance
            if distance >= length:
                output += output[start:start + length]
            else:
                for offset in range(length):
                    output.append(output[start + offset])
        elif literal_mode:
            output.append(reader.decode(LITERAL_CODE))
        else:
            output.append(reader.bits(8))
    return bytes(output)


@dataclass
class InstallShield3Entry:
    directory: str
    name: str
    uncompressed_size: int
    compressed_size: int
    offset: int
    dos_datetime: int
    attributes: int

    @property
    def path(self):
        directory = self.directory.replace("\\", "/").strip("/")
        return f"{directory}/{self.name}" if directory else self.name

    @property
    def modified(self):
        return dos_datetime_string(self.dos_datetime)


def is_installshield3(data):
    return len(data) >= 4 and struct.unpack_from("<I", data, 0)[0] == SIGNATURE


class InstallShield3Archive:
    def __init__(self, path_or_bytes):
        if isinstance(path_or_bytes, (bytes, bytearray, memoryview)):
            self.data = bytes(path_or_bytes)
        else:
            self.data = Path(path_or_bytes).read_bytes()
        if not is_installshield3(self.data):
            raise InstallShield3Error("not an InstallShield 3 archive")
        self.declared_file_count = struct.unpack_from("<H", self.data, 0x0C)[0]
        self.entries = self.read_table()

    def read_table(self):
        data = self.data
        toc_address = struct.unpack_from("<I", data, 0x29)[0]
        directory_count = struct.unpack_from("<H", data, 0x31)[0]
        position = toc_address
        directories = []
        for _ in range(directory_count):
            count, chunk_size, name_length = struct.unpack_from("<HHH", data, position)
            name = data[position + 6:position + 6 + name_length].decode("latin-1")
            directories.append((name, count))
            position += chunk_size
        entries = []
        for directory_name, count in directories:
            for _ in range(count):
                (uncompressed_size, compressed_size, offset, datetime_value,
                 _, chunk_size, attributes, name_length) = struct.unpack_from("<3xIIIIIHIB", data, position)
                name_start = position + 30
                name = data[name_start:name_start + name_length].decode("latin-1")
                entries.append(InstallShield3Entry(directory_name, name, uncompressed_size, compressed_size,
                                                   offset, datetime_value, attributes))
                position += chunk_size
        return entries

    def names(self):
        return [entry.path for entry in self.entries]

    def getinfo(self, name):
        wanted = name.replace("\\", "/").strip("/").lower()
        for entry in self.entries:
            if entry.path.lower() == wanted:
                return entry
        raise KeyError(name)

    def read(self, name):
        entry = name if isinstance(name, InstallShield3Entry) else self.getinfo(name)
        compressed = self.data[entry.offset:entry.offset + entry.compressed_size]
        content = explode(compressed)
        if len(content) != entry.uncompressed_size:
            raise InstallShield3Error(f"{entry.path}: expanded to {len(content)} bytes, expected {entry.uncompressed_size}")
        return content


def dos_datetime_string(value):
    date_part = value & 0xFFFF
    time_part = value >> 16
    year = 1980 + (date_part >> 9)
    month = (date_part >> 5) & 15
    day = date_part & 31
    hour = time_part >> 11
    minute = (time_part >> 5) & 63
    second = (time_part & 31) * 2
    return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"
