import struct
import zlib

MSZIP_BLOCK_SIZE = 32768
DOS_DATE = 0x2D21
DOS_TIME = 0x6000


def mszip_blocks(data):
    blocks = []
    for start in range(0, len(data), MSZIP_BLOCK_SIZE):
        chunk = data[start:start + MSZIP_BLOCK_SIZE]
        history = data[max(0, start - MSZIP_BLOCK_SIZE):start]
        if history:
            compressor = zlib.compressobj(9, zlib.DEFLATED, -15, zdict=history)
        else:
            compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
        blocks.append((b"CK" + compressor.compress(chunk) + compressor.flush(), len(chunk)))
    return blocks


def stored_blocks(data):
    return [(data[start:start + MSZIP_BLOCK_SIZE], len(data[start:start + MSZIP_BLOCK_SIZE]))
            for start in range(0, len(data), MSZIP_BLOCK_SIZE)] or [(b"", 0)]


def build_cab(members, compression=0):
    payload = b"".join(data for _, data in members)
    blocks = mszip_blocks(payload) if compression == 1 else stored_blocks(payload)
    header_size = 36
    folder_size = 8
    file_entries = b""
    offset = 0
    for name, data in members:
        file_entries += struct.pack("<IIHHHH", len(data), offset, 0, DOS_DATE, DOS_TIME, 0x20) + name.encode("latin-1") + b"\0"
        offset += len(data)
    data_offset = header_size + folder_size + len(file_entries)
    data_section = b"".join(struct.pack("<IHH", 0, len(block), size) + block for block, size in blocks)
    total_size = data_offset + len(data_section)
    header = b"MSCF" + struct.pack("<IIIIIBBHHHHH", 0, total_size, 0, header_size + folder_size, 0, 3, 1, 1, len(members), 0, 0x1234, 0)
    folder = struct.pack("<IHH", data_offset, len(blocks), compression)
    return header + folder + file_entries + data_section


def build_ce_setup(app_name, provider, processor_type, files, minimum_version=(2, 0), maximum_version=(0, 0), unsupported=""):
    strings = []
    directories = []

    def string_id(text):
        if text not in strings:
            strings.append(text)
        return strings.index(text) + 1

    file_records = []
    for identifier, (name, directory_parts) in enumerate(files, start=1):
        path_ids = [string_id(part) for part in directory_parts]
        if path_ids not in directories:
            directories.append(path_ids)
        file_records.append((identifier, directories.index(path_ids) + 1, name))

    def text_field(text):
        return text.encode("latin-1") + b"\0"

    tail = bytearray()
    base = 0x60
    app_offset = base + len(tail)
    tail += text_field(app_name)
    provider_offset = base + len(tail)
    tail += text_field(provider)
    unsupported_offset = base + len(tail) if unsupported else 0
    if unsupported:
        tail += text_field(unsupported)
    string_offset = base + len(tail)
    for index, text in enumerate(strings, start=1):
        encoded = text_field(text)
        tail += struct.pack("<HH", index, len(encoded)) + encoded
    directory_offset = base + len(tail)
    for index, path_ids in enumerate(directories, start=1):
        encoded = struct.pack(f"<{len(path_ids) + 1}H", *path_ids, 0)
        tail += struct.pack("<HH", index, len(encoded)) + encoded
    file_offset = base + len(tail)
    for identifier, directory, name in file_records:
        encoded = text_field(name)
        tail += struct.pack("<HHHIH", identifier, directory, identifier, 0, len(encoded)) + encoded
    end_offset = base + len(tail)

    header = bytearray(0x60)
    header[0:4] = b"MSCE"
    struct.pack_into("<IIII", header, 4, 0, 0x60 + len(tail), 0, 1)
    struct.pack_into("<I", header, 0x14, processor_type)
    struct.pack_into("<6I", header, 0x18, *minimum_version, *maximum_version, 0, 0)
    struct.pack_into("<6H", header, 0x30, len(strings), len(directories), len(file_records), 0, 0, 0)
    struct.pack_into("<6I", header, 0x3C, string_offset, directory_offset, file_offset, end_offset, end_offset, end_offset)
    struct.pack_into("<6H", header, 0x54, app_offset, len(text_field(app_name)), provider_offset, len(text_field(provider)),
                     unsupported_offset, len(text_field(unsupported)) if unsupported else 0)
    return bytes(header + tail)


def build_ce_cab(app_name, provider, processor_type, files, compression=0, **setup_options):
    setup = build_ce_setup(app_name, provider, processor_type, [(name, parts) for name, parts, _ in files], **setup_options)
    stem = app_name.replace(" ", "")[:8]
    members = [(f"{stem}.000", setup)]
    for identifier, (name, _, data) in enumerate(files, start=1):
        members.append((f"{name.rsplit('.', 1)[0][:8]}.{identifier:03d}", data))
    return build_cab(members, compression)
