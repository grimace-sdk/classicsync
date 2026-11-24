import struct

SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

SECTOR_SIZE = 512
MINI_SECTOR_SIZE = 64
MINI_STREAM_CUTOFF = 4096
DIRECTORY_ENTRY_SIZE = 128
HEADER_DIFAT_ENTRIES = 109
MAX_NAME_LENGTH = 31

MAX_REGULAR_SECTOR = 0xFFFFFFFA
DIFAT_SECTOR = 0xFFFFFFFC
FAT_SECTOR = 0xFFFFFFFD
END_OF_CHAIN = 0xFFFFFFFE
FREE_SECTOR = 0xFFFFFFFF
NO_STREAM = 0xFFFFFFFF

TYPE_EMPTY = 0
TYPE_STORAGE = 1
TYPE_STREAM = 2
TYPE_ROOT = 5

COLOUR_RED = 0
COLOUR_BLACK = 1

ILLEGAL_NAME_CHARACTERS = "/\\:!"


class CompoundFileError(Exception):
    pass


def name_sort_key(name):
    return len(name), name.upper()


class Stream:
    def __init__(self, name, data=b""):
        self.name = name
        self.data = bytes(data)

    def __repr__(self):
        return f"Stream({self.name!r}, {len(self.data)} bytes)"


class Storage:
    def __init__(self, name="Root Entry", clsid=bytes(16)):
        self.name = name
        self.clsid = clsid
        self.state_bits = 0
        self.created = 0
        self.modified = 0
        self.entries = {}

    def __repr__(self):
        return f"Storage({self.name!r}, {len(self.entries)} entries)"

    def __iter__(self):
        return iter(sorted(self.entries.values(), key=lambda entry: name_sort_key(entry.name)))

    def __len__(self):
        return len(self.entries)

    def __contains__(self, name):
        return name.upper() in self.entries

    def get(self, name):
        return self.entries.get(name.upper())

    def storage(self, name):
        entry = self.get(name)
        return entry if isinstance(entry, Storage) else None

    def stream(self, name):
        entry = self.get(name)
        return entry if isinstance(entry, Stream) else None

    def add(self, entry):
        check_name(entry.name)
        self.entries[entry.name.upper()] = entry
        return entry

    def create_storage(self, name):
        return self.add(Storage(name))

    def open_or_create_storage(self, name):
        existing = self.get(name)
        if isinstance(existing, Storage):
            return existing
        return self.create_storage(name)

    def set_stream(self, name, data):
        return self.add(Stream(name, data))

    def remove(self, name):
        return self.entries.pop(name.upper(), None)

    def rename(self, old_name, new_name):
        entry = self.remove(old_name)
        if entry is None:
            raise KeyError(old_name)
        entry.name = new_name
        return self.add(entry)

    def walk(self, prefix=()):
        for entry in self:
            path = prefix + (entry.name,)
            yield path, entry
            if isinstance(entry, Storage):
                yield from entry.walk(path)


def check_name(name):
    if not name or len(name) > MAX_NAME_LENGTH:
        raise CompoundFileError(f"element name {name!r} must be 1 to {MAX_NAME_LENGTH} characters")
    if any(character in ILLEGAL_NAME_CHARACTERS for character in name):
        raise CompoundFileError(f"element name {name!r} contains one of {ILLEGAL_NAME_CHARACTERS!r}")


def read_chain(table, start, limit):
    chain = []
    sector = start
    while sector != END_OF_CHAIN:
        if sector > MAX_REGULAR_SECTOR or sector >= limit or len(chain) > limit:
            raise CompoundFileError(f"broken sector chain at {sector:#x}")
        chain.append(sector)
        sector = table[sector]
    return chain


class CompoundFileReader:
    def __init__(self, data):
        self.data = bytes(data)
        if len(self.data) < SECTOR_SIZE or self.data[:8] != SIGNATURE:
            raise CompoundFileError("not an OLE compound file")
        (minor_version, major_version, byte_order, sector_shift, mini_sector_shift) = struct.unpack_from("<HHHHH", self.data, 0x18)
        if byte_order != 0xFFFE:
            raise CompoundFileError("unexpected byte order mark")
        self.sector_size = 1 << sector_shift
        self.mini_sector_size = 1 << mini_sector_shift
        if (major_version, self.sector_size) not in ((3, 512), (4, 4096)):
            raise CompoundFileError(f"unsupported compound file version {major_version} with {self.sector_size}-byte sectors")
        (fat_sector_count, self.first_directory_sector, _, self.mini_stream_cutoff, first_mini_fat_sector,
         mini_fat_sector_count, first_difat_sector, difat_sector_count) = struct.unpack_from("<IIIIIIII", self.data, 0x2C)
        fat_sectors = list(struct.unpack_from(f"<{HEADER_DIFAT_ENTRIES}I", self.data, 0x4C))
        entries_per_sector = self.sector_size // 4
        sector = first_difat_sector
        for _ in range(difat_sector_count):
            if sector > MAX_REGULAR_SECTOR:
                break
            values = struct.unpack(f"<{entries_per_sector}I", self.sector(sector))
            fat_sectors.extend(values[:-1])
            sector = values[-1]
        fat_sectors = [value for value in fat_sectors[:fat_sector_count] if value <= MAX_REGULAR_SECTOR]
        fat_bytes = b"".join(self.sector(value) for value in fat_sectors)
        self.fat = struct.unpack(f"<{len(fat_bytes) // 4}I", fat_bytes)
        self.mini_fat = ()
        if mini_fat_sector_count and first_mini_fat_sector <= MAX_REGULAR_SECTOR:
            mini_fat_bytes = self.read_regular(first_mini_fat_sector)
            self.mini_fat = struct.unpack(f"<{len(mini_fat_bytes) // 4}I", mini_fat_bytes)
        directory = self.read_regular(self.first_directory_sector)
        self.directory = [directory[offset:offset + DIRECTORY_ENTRY_SIZE]
                          for offset in range(0, len(directory) - DIRECTORY_ENTRY_SIZE + 1, DIRECTORY_ENTRY_SIZE)]
        root_entry = self.entry(0)
        if root_entry["type"] != TYPE_ROOT:
            raise CompoundFileError("first directory entry is not the root storage")
        self.mini_stream = self.read_regular(root_entry["start"], root_entry["size"]) if root_entry["size"] else b""

    def sector(self, index):
        offset = (index + 1) * self.sector_size
        if index > MAX_REGULAR_SECTOR or offset + self.sector_size > len(self.data) + self.sector_size:
            raise CompoundFileError(f"sector {index:#x} is outside the file")
        return self.data[offset:offset + self.sector_size].ljust(self.sector_size, b"\0")

    def read_regular(self, start, size=None):
        chain = read_chain(self.fat, start, len(self.fat))
        data = b"".join(self.sector(index) for index in chain)
        return data if size is None else data[:size]

    def read_mini(self, start, size):
        chain = read_chain(self.mini_fat, start, len(self.mini_fat))
        data = b"".join(self.mini_stream[index * self.mini_sector_size:(index + 1) * self.mini_sector_size] for index in chain)
        return data[:size]

    def entry(self, index):
        if index >= len(self.directory):
            raise CompoundFileError(f"directory entry {index} is outside the directory")
        raw = self.directory[index]
        name_length = struct.unpack_from("<H", raw, 0x40)[0]
        name = raw[:max(0, min(name_length, 64) - 2)].decode("utf-16-le", errors="replace")
        entry_type, colour, left, right, child = struct.unpack_from("<BBIII", raw, 0x42)
        clsid = raw[0x50:0x60]
        state_bits, created, modified, start, size_low, size_high = struct.unpack_from("<IQQIII", raw, 0x60)
        size = size_low if self.sector_size == SECTOR_SIZE else size_low | (size_high << 32)
        return {"name": name, "type": entry_type, "left": left, "right": right, "child": child, "clsid": clsid,
                "state_bits": state_bits, "created": created, "modified": modified, "start": start, "size": size}

    def stream_data(self, entry):
        if entry["size"] == 0:
            return b""
        if entry["size"] < self.mini_stream_cutoff:
            return self.read_mini(entry["start"], entry["size"])
        return self.read_regular(entry["start"], entry["size"])

    def children(self, child_index):
        indices = []
        pending = [child_index]
        visited = set()
        while pending:
            index = pending.pop()
            if index == NO_STREAM:
                continue
            if index in visited:
                raise CompoundFileError("directory tree has a cycle")
            visited.add(index)
            entry = self.entry(index)
            indices.append(index)
            pending.append(entry["left"])
            pending.append(entry["right"])
        return indices

    def build_storage(self, index, storage, depth=0):
        if depth > 64:
            raise CompoundFileError("storages nested too deeply")
        entry = self.entry(index)
        storage.clsid = entry["clsid"]
        storage.state_bits = entry["state_bits"]
        storage.created = entry["created"]
        storage.modified = entry["modified"]
        for child_index in self.children(entry["child"]):
            child = self.entry(child_index)
            if child["type"] in (TYPE_STORAGE, TYPE_ROOT):
                substorage = Storage(child["name"])
                storage.entries[child["name"].upper()] = substorage
                self.build_storage(child_index, substorage, depth + 1)
            elif child["type"] == TYPE_STREAM:
                storage.entries[child["name"].upper()] = Stream(child["name"], self.stream_data(child))

    def root(self):
        root = Storage(self.entry(0)["name"] or "Root Entry")
        self.build_storage(0, root)
        return root


def read_compound_file(source):
    if isinstance(source, (bytes, bytearray, memoryview)):
        data = bytes(source)
    else:
        with open(source, "rb") as handle:
            data = handle.read()
    return CompoundFileReader(data).root()


def is_compound_file(path):
    try:
        with open(path, "rb") as handle:
            return handle.read(8) == SIGNATURE
    except OSError:
        return False


def balanced_tree(sorted_indices, depth, full_levels, tree):
    if not sorted_indices:
        return NO_STREAM
    middle = len(sorted_indices) // 2
    index = sorted_indices[middle]
    left = balanced_tree(sorted_indices[:middle], depth + 1, full_levels, tree)
    right = balanced_tree(sorted_indices[middle + 1:], depth + 1, full_levels, tree)
    tree[index] = (left, right, COLOUR_BLACK if depth < full_levels else COLOUR_RED)
    return index


def subtree_root(child_indices, names, tree):
    ordered = sorted(child_indices, key=lambda index: name_sort_key(names[index]))
    full_levels = (len(ordered) + 1).bit_length() - 1
    return balanced_tree(ordered, 0, full_levels, tree)


def pad(data, size):
    remainder = len(data) % size
    return data if remainder == 0 else data + bytes(size - remainder)


class CompoundFileWriter:
    def __init__(self, root):
        self.root = root
        self.nodes = []
        self.child_lists = []
        self.collect(root)

    def collect(self, root):
        self.nodes.append(root)
        self.child_lists.append([])
        pending = [0]
        while pending:
            parent_index = pending.pop(0)
            for entry in self.nodes[parent_index]:
                index = len(self.nodes)
                self.nodes.append(entry)
                self.child_lists.append([])
                self.child_lists[parent_index].append(index)
                if isinstance(entry, Storage):
                    pending.append(index)

    def build(self):
        names = [node.name for node in self.nodes]
        tree = {}
        child_roots = [subtree_root(children, names, tree) for children in self.child_lists]
        tree[0] = (NO_STREAM, NO_STREAM, COLOUR_BLACK)

        mini_stream = bytearray()
        mini_fat = []
        regular_streams = []
        placement = {}
        for index, node in enumerate(self.nodes):
            if not isinstance(node, Stream) or not node.data:
                continue
            if len(node.data) < MINI_STREAM_CUTOFF:
                first = len(mini_stream) // MINI_SECTOR_SIZE
                count = (len(node.data) + MINI_SECTOR_SIZE - 1) // MINI_SECTOR_SIZE
                mini_fat.extend(list(range(first + 1, first + count)) + [END_OF_CHAIN])
                mini_stream += pad(node.data, MINI_SECTOR_SIZE)
                placement[index] = ("mini", first)
            else:
                regular_streams.append(index)

        sectors = []
        fat = []

        def allocate(data):
            if not data:
                return END_OF_CHAIN
            first = len(sectors)
            padded = pad(data, SECTOR_SIZE)
            count = len(padded) // SECTOR_SIZE
            for offset in range(count):
                sectors.append(padded[offset * SECTOR_SIZE:(offset + 1) * SECTOR_SIZE])
            fat.extend(list(range(first + 1, first + count)) + [END_OF_CHAIN])
            return first

        for index in regular_streams:
            placement[index] = ("regular", allocate(self.nodes[index].data))
        mini_stream_start = allocate(bytes(mini_stream))

        directory = bytearray()
        for index, node in enumerate(self.nodes):
            left, right, colour = tree[index]
            directory += self.directory_entry(node, index, left, right, colour, child_roots[index],
                                              placement, mini_stream_start, len(mini_stream))
        directory = pad(bytes(directory), SECTOR_SIZE)
        empty_entry = bytes(0x42) + struct.pack("<BBIII", TYPE_EMPTY, COLOUR_RED, NO_STREAM, NO_STREAM, NO_STREAM) + bytes(DIRECTORY_ENTRY_SIZE - 0x50)
        used = len(self.nodes) * DIRECTORY_ENTRY_SIZE
        directory = directory[:used] + empty_entry * ((len(directory) - used) // DIRECTORY_ENTRY_SIZE)
        directory_start = allocate(directory)

        mini_fat_bytes = struct.pack(f"<{len(mini_fat)}I", *mini_fat) if mini_fat else b""
        mini_fat_start = allocate(pad(mini_fat_bytes, SECTOR_SIZE)) if mini_fat_bytes else END_OF_CHAIN
        mini_fat_sector_count = len(pad(mini_fat_bytes, SECTOR_SIZE)) // SECTOR_SIZE if mini_fat_bytes else 0

        entries_per_sector = SECTOR_SIZE // 4
        data_sector_count = len(sectors)
        fat_sector_count = 1
        difat_sector_count = 0
        while True:
            total = data_sector_count + fat_sector_count + difat_sector_count
            needed_fat = (total + entries_per_sector - 1) // entries_per_sector
            needed_difat = 0
            if needed_fat > HEADER_DIFAT_ENTRIES:
                needed_difat = (needed_fat - HEADER_DIFAT_ENTRIES + entries_per_sector - 2) // (entries_per_sector - 1)
            if needed_fat == fat_sector_count and needed_difat == difat_sector_count:
                break
            fat_sector_count, difat_sector_count = needed_fat, needed_difat

        fat_sector_indices = list(range(data_sector_count, data_sector_count + fat_sector_count))
        difat_sector_indices = list(range(data_sector_count + fat_sector_count,
                                          data_sector_count + fat_sector_count + difat_sector_count))
        fat.extend([FAT_SECTOR] * fat_sector_count)
        fat.extend([DIFAT_SECTOR] * difat_sector_count)
        fat.extend([FREE_SECTOR] * (fat_sector_count * entries_per_sector - len(fat)))
        fat_bytes = struct.pack(f"<{len(fat)}I", *fat)
        for offset in range(fat_sector_count):
            sectors.append(fat_bytes[offset * SECTOR_SIZE:(offset + 1) * SECTOR_SIZE])

        overflow = fat_sector_indices[HEADER_DIFAT_ENTRIES:]
        for position, sector_index in enumerate(difat_sector_indices):
            values = overflow[position * (entries_per_sector - 1):(position + 1) * (entries_per_sector - 1)]
            values = values + [FREE_SECTOR] * (entries_per_sector - 1 - len(values))
            next_sector = difat_sector_indices[position + 1] if position + 1 < len(difat_sector_indices) else END_OF_CHAIN
            sectors.append(struct.pack(f"<{entries_per_sector}I", *values, next_sector))

        header_difat = fat_sector_indices[:HEADER_DIFAT_ENTRIES]
        header_difat = header_difat + [FREE_SECTOR] * (HEADER_DIFAT_ENTRIES - len(header_difat))
        header = SIGNATURE + bytes(16) + struct.pack(
            "<HHHHH6sIIIIIIIII", 0x003E, 3, 0xFFFE, 9, 6, bytes(6), 0, fat_sector_count, directory_start, 0,
            MINI_STREAM_CUTOFF, mini_fat_start, mini_fat_sector_count,
            difat_sector_indices[0] if difat_sector_indices else END_OF_CHAIN, difat_sector_count,
        ) + struct.pack(f"<{HEADER_DIFAT_ENTRIES}I", *header_difat)
        return header + b"".join(sectors)

    def directory_entry(self, node, index, left, right, colour, child, placement, mini_stream_start, mini_stream_size):
        encoded = node.name.encode("utf-16-le")
        name_field = (encoded + b"\0\0").ljust(64, b"\0")
        if index == 0:
            entry_type, clsid, state_bits, created, modified = TYPE_ROOT, node.clsid, node.state_bits, 0, node.modified
            start = mini_stream_start if mini_stream_size else END_OF_CHAIN
            size = mini_stream_size
        elif isinstance(node, Storage):
            entry_type, clsid, state_bits, created, modified = TYPE_STORAGE, node.clsid, node.state_bits, node.created, node.modified
            start, size = 0, 0
        else:
            entry_type, clsid, state_bits, created, modified = TYPE_STREAM, bytes(16), 0, 0, 0
            start = placement[index][1] if index in placement else END_OF_CHAIN
            size = len(node.data)
            child = NO_STREAM
        return (name_field + struct.pack("<HBBIII", len(encoded) + 2, entry_type, colour, left, right, child)
                + clsid + struct.pack("<IQQIII", state_bits, created, modified, start, size, 0))


def write_compound_file(root, destination=None):
    data = CompoundFileWriter(root).build()
    if destination is not None:
        with open(destination, "wb") as handle:
            handle.write(data)
    return data
