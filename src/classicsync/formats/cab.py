import struct
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .cab_lzx import LzxError, decompress_lzx_folder

CAB_SIGNATURE = b"MSCF"

FLAG_PREV_CABINET = 0x0001
FLAG_NEXT_CABINET = 0x0002
FLAG_RESERVE_PRESENT = 0x0004

COMPRESSION_NONE = 0
COMPRESSION_MSZIP = 1
COMPRESSION_QUANTUM = 2
COMPRESSION_LZX = 3

COMPRESSION_NAMES = {
    COMPRESSION_NONE: "none",
    COMPRESSION_MSZIP: "MSZIP",
    COMPRESSION_QUANTUM: "Quantum",
    COMPRESSION_LZX: "LZX",
}

FOLDER_CONTINUED_FROM_PREV = 0xFFFD
FOLDER_CONTINUED_TO_NEXT = 0xFFFE
FOLDER_CONTINUED_PREV_AND_NEXT = 0xFFFF

ATTRIBUTE_NAME_IS_UTF8 = 0x80

MSZIP_SIGNATURE = b"CK"
MSZIP_HISTORY_SIZE = 32768


class CabError(Exception):
    pass


@dataclass
class CabFile:
    name: str
    size: int
    folder_index: int
    folder_offset: int
    attributes: int
    dos_date: int
    dos_time: int

    @property
    def modified(self):
        try:
            return datetime(
                1980 + (self.dos_date >> 9),
                (self.dos_date >> 5) & 0x0F,
                self.dos_date & 0x1F,
                self.dos_time >> 11,
                (self.dos_time >> 5) & 0x3F,
                (self.dos_time & 0x1F) * 2,
            )
        except ValueError:
            return None


@dataclass
class CabFolder:
    data_offset: int
    block_count: int
    compression: int

    @property
    def compression_type(self):
        return self.compression & 0x000F

    @property
    def compression_name(self):
        return COMPRESSION_NAMES.get(self.compression_type, f"unknown ({self.compression_type})")


def _read_zstring(data, offset):
    end = data.index(b"\x00", offset)
    return data[offset:end], end + 1


class CabArchive:
    def __init__(self, path_or_bytes):
        if isinstance(path_or_bytes, (bytes, bytearray, memoryview)):
            self.data = bytes(path_or_bytes)
        else:
            self.data = Path(path_or_bytes).read_bytes()
        self.folders = []
        self.files = []
        self.set_id = 0
        self.cabinet_index = 0
        self.previous_cabinet = None
        self.next_cabinet = None
        self._folder_cache = {}
        self._parse()

    def _parse(self):
        data = self.data
        if len(data) < 36 or data[:4] != CAB_SIGNATURE:
            raise CabError("not a cabinet file")
        (
            _,
            cabinet_size,
            _,
            files_offset,
            _,
            version_minor,
            version_major,
            folder_count,
            file_count,
            flags,
            self.set_id,
            self.cabinet_index,
        ) = struct.unpack_from("<IIIIIBBHHHHH", data, 4)
        self.version = (version_major, version_minor)
        offset = 36
        header_reserve_size = folder_reserve_size = 0
        self.data_reserve_size = 0
        if flags & FLAG_RESERVE_PRESENT:
            header_reserve_size, folder_reserve_size, self.data_reserve_size = struct.unpack_from("<HBB", data, offset)
            offset += 4 + header_reserve_size
        if flags & FLAG_PREV_CABINET:
            previous_name, offset = _read_zstring(data, offset)
            _, offset = _read_zstring(data, offset)
            self.previous_cabinet = previous_name.decode("latin-1")
        if flags & FLAG_NEXT_CABINET:
            next_name, offset = _read_zstring(data, offset)
            _, offset = _read_zstring(data, offset)
            self.next_cabinet = next_name.decode("latin-1")
        for _ in range(folder_count):
            data_offset, block_count, compression = struct.unpack_from("<IHH", data, offset)
            self.folders.append(CabFolder(data_offset, block_count, compression))
            offset += 8 + folder_reserve_size
        offset = files_offset
        for _ in range(file_count):
            size, folder_offset, folder_index, dos_date, dos_time, attributes = struct.unpack_from("<IIHHHH", data, offset)
            raw_name, offset = _read_zstring(data, offset + 16)
            encoding = "utf-8" if attributes & ATTRIBUTE_NAME_IS_UTF8 else "cp1252"
            name = raw_name.decode(encoding, errors="replace")
            if folder_index in (FOLDER_CONTINUED_FROM_PREV, FOLDER_CONTINUED_PREV_AND_NEXT):
                folder_index = 0
            elif folder_index == FOLDER_CONTINUED_TO_NEXT:
                folder_index = folder_count - 1
            self.files.append(CabFile(name, size, folder_index, folder_offset, attributes, dos_date, dos_time))

    def names(self):
        return [entry.name for entry in self.files]

    def getinfo(self, name):
        for entry in self.files:
            if entry.name == name:
                return entry
        lowered = name.lower()
        for entry in self.files:
            if entry.name.lower() == lowered:
                return entry
        raise KeyError(name)

    def read(self, name):
        entry = name if isinstance(name, CabFile) else self.getinfo(name)
        folder_data = self._folder_data(entry.folder_index)
        end = entry.folder_offset + entry.size
        if end > len(folder_data):
            raise CabError(f"{entry.name}: data extends past the end of its folder (split cabinet?)")
        return folder_data[entry.folder_offset:end]

    def extract_all(self, destination):
        destination = Path(destination)
        written = []
        for entry in self.files:
            relative = Path(*entry.name.replace("\\", "/").split("/"))
            if relative.is_absolute() or ".." in relative.parts:
                raise CabError(f"unsafe path in cabinet: {entry.name}")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.read(entry))
            written.append(target)
        return written

    def _blocks(self, folder):
        offset = folder.data_offset
        for _ in range(folder.block_count):
            _, compressed_size, uncompressed_size = struct.unpack_from("<IHH", self.data, offset)
            offset += 8 + self.data_reserve_size
            yield self.data[offset:offset + compressed_size], uncompressed_size
            offset += compressed_size

    def _folder_data(self, index):
        if index in self._folder_cache:
            return self._folder_cache[index]
        if index >= len(self.folders):
            raise CabError(f"folder {index} out of range")
        folder = self.folders[index]
        kind = folder.compression_type
        if kind == COMPRESSION_NONE:
            output = b"".join(block for block, _ in self._blocks(folder))
        elif kind == COMPRESSION_MSZIP:
            output = self._inflate_mszip(folder)
        elif kind == COMPRESSION_LZX:
            try:
                output = decompress_lzx_folder(self._blocks(folder), (folder.compression >> 8) & 0x1F)
            except (LzxError, IndexError, KeyError) as error:
                raise CabError(f"LZX: {error}") from error
        else:
            raise CabError(f"unsupported compression: {folder.compression_name}")
        self._folder_cache[index] = output
        return output

    def _inflate_mszip(self, folder):
        output = bytearray()
        for block, uncompressed_size in self._blocks(folder):
            if block[:2] != MSZIP_SIGNATURE:
                raise CabError("bad MSZIP block signature")
            history = bytes(output[-MSZIP_HISTORY_SIZE:])
            if history:
                decompressor = zlib.decompressobj(-15, zdict=history)
            else:
                decompressor = zlib.decompressobj(-15)
            try:
                inflated = decompressor.decompress(block[2:]) + decompressor.flush()
            except zlib.error as error:
                raise CabError(f"MSZIP block: {error}") from error
            if len(inflated) != uncompressed_size:
                raise CabError(f"MSZIP block inflated to {len(inflated)} bytes, expected {uncompressed_size}")
            output += inflated
        return bytes(output)
