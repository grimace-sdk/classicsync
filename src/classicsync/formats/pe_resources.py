import struct

RESOURCE_TYPE_NAMES = {
    1: "CURSOR",
    2: "BITMAP",
    3: "ICON",
    12: "GROUP_CURSOR",
    14: "GROUP_ICON",
}


class PeResourceError(ValueError):
    pass


class MissingDependencyError(RuntimeError):
    pass


def load_pefile():
    try:
        import pefile
    except ImportError as error:
        raise MissingDependencyError(
            "reading installer artwork needs the pefile package: pip install 'classicsync[artwork]'") from error
    return pefile


def build_bitmap_file(data):
    header_size = struct.unpack_from("<I", data, 0)[0]
    if header_size == 12:
        bit_count = struct.unpack_from("<H", data, 10)[0]
        palette_size = (1 << bit_count) * 3 if bit_count <= 8 else 0
    else:
        bit_count, compression = struct.unpack_from("<HI", data, 14)
        colors_used = struct.unpack_from("<I", data, 32)[0]
        if colors_used:
            palette_size = colors_used * 4
        elif bit_count <= 8:
            palette_size = (1 << bit_count) * 4
        else:
            palette_size = 0
        if compression == 3:
            palette_size += 12
    pixel_offset = 14 + header_size + palette_size
    return struct.pack("<2sIHHI", b"BM", 14 + len(data), 0, 0, pixel_offset) + data


def build_icon_file(group_data, image_lookup, is_cursor=False):
    count = struct.unpack_from("<HHH", group_data, 0)[2]
    entries = []
    images = []
    for index in range(count):
        offset = 6 + index * 14
        if is_cursor:
            width, height, planes, bit_count, size, image_id = struct.unpack_from("<HHHHIH", group_data, offset)
            image = image_lookup.get(image_id)
            if image is None:
                continue
            hotspot_x, hotspot_y = struct.unpack_from("<HH", image, 0)
            image = image[4:]
            entries.append((width & 0xFF, (height // 2) & 0xFF, 0, 0, hotspot_x, hotspot_y, len(image)))
        else:
            width, height, colors, _, planes, bit_count, size, image_id = struct.unpack_from("<BBBBHHIH", group_data, offset)
            image = image_lookup.get(image_id)
            if image is None:
                continue
            entries.append((width, height, colors, 0, planes, bit_count, len(image)))
        images.append(image)
    header = struct.pack("<HHH", 0, 2 if is_cursor else 1, len(images))
    directory = b""
    data_offset = 6 + 16 * len(images)
    for entry, image in zip(entries, images):
        directory += struct.pack("<BBBBHHII", *entry, data_offset)
        data_offset += len(image)
    return header + directory + b"".join(images)


def resource_label(entry):
    if entry.name is not None:
        return str(entry.name)
    return str(entry.id)


def walk_resources(pe):
    if not hasattr(pe, "DIRECTORY_ENTRY_RESOURCE"):
        return
    for type_entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if type_entry.name is not None:
            type_name = str(type_entry.name)
        else:
            type_name = RESOURCE_TYPE_NAMES.get(type_entry.id, str(type_entry.id))
        if not hasattr(type_entry, "directory"):
            continue
        for name_entry in type_entry.directory.entries:
            if not hasattr(name_entry, "directory"):
                continue
            for language_entry in name_entry.directory.entries:
                data_entry = language_entry.data.struct
                data = pe.get_data(data_entry.OffsetToData, data_entry.Size)
                yield type_name, name_entry, data


def parse_pe(data):
    pefile = load_pefile()
    try:
        pe = pefile.PE(data=data, fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
    except pefile.PEFormatError as error:
        raise PeResourceError(str(error)) from error
    return pe


def is_pe(data):
    if len(data) < 0x40 or data[:2] != b"MZ":
        return False
    header_offset = struct.unpack_from("<I", data, 0x3C)[0]
    return data[header_offset:header_offset + 4] == b"PE\x00\x00"


def media_extension(data):
    if data[:4] == b"RIFF" and data[8:12] == b"AVI ":
        return "avi"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:6] in (b"GIF89a", b"GIF87a"):
        return "gif"
    return None


def extract_artwork(data):
    pe = parse_pe(data)
    artwork = {}
    icon_images = {}
    cursor_images = {}
    groups = []
    for type_name, name_entry, resource_data in walk_resources(pe):
        label = resource_label(name_entry)
        if type_name == "ICON":
            icon_images[name_entry.id] = resource_data
        elif type_name == "CURSOR":
            cursor_images[name_entry.id] = resource_data
        elif type_name in ("GROUP_ICON", "GROUP_CURSOR"):
            groups.append((type_name, label, resource_data))
        elif type_name == "BITMAP":
            artwork[f"bitmap_{label}.bmp"] = build_bitmap_file(resource_data)
        else:
            extension = media_extension(resource_data)
            if extension:
                artwork[f"{type_name.lower()}_{label}.{extension}"] = resource_data
    for type_name, label, group_data in groups:
        is_cursor = type_name == "GROUP_CURSOR"
        content = build_icon_file(group_data, cursor_images if is_cursor else icon_images, is_cursor)
        extension = "cur" if is_cursor else "ico"
        artwork[f"{type_name.lower()}_{label}.{extension}"] = content
    pe.close()
    return artwork

