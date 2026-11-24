import struct
from dataclasses import dataclass, field

SETUP_SIGNATURES = (b"MSCE", b"CE4+")
HEADER_SIZE = 0x60

PROCESSOR_ANY = 0


class CeSetupError(Exception):
    pass


@dataclass
class CeSetupFile:
    identifier: int
    directory: int
    flags: int
    name: str


@dataclass
class CeSetupRegistryHive:
    identifier: int
    hive: int
    path: list


@dataclass
class CeSetupRegistryKey:
    hive: int
    flags: int
    data: bytes


@dataclass
class CeSetupLink:
    fields: list
    path: list


@dataclass
class CeSetup:
    signature: bytes
    processor_type: int
    minimum_version: tuple
    maximum_version: tuple
    minimum_build: int
    maximum_build: int
    app_name: str
    provider: str
    unsupported: list
    strings: dict = field(default_factory=dict)
    directories: dict = field(default_factory=dict)
    files: dict = field(default_factory=dict)
    hives: dict = field(default_factory=dict)
    registry_keys: list = field(default_factory=list)
    links: list = field(default_factory=list)

    @property
    def uninstall_name(self):
        return f"{self.provider} {self.app_name}".strip() if self.provider else self.app_name

    def resolve_path(self, string_identifiers):
        return "\\".join(self.strings.get(identifier, f"?{identifier}") for identifier in string_identifiers)

    def file_paths(self):
        return {
            entry.name: self.resolve_path(self.directories.get(entry.directory, []))
            for entry in self.files.values()
        }


def is_setup(data):
    return data[:4] in SETUP_SIGNATURES


def _ensure_available(data, offset, size):
    if offset < 0 or offset + size > len(data):
        raise CeSetupError("setup file is truncated")


def _words(data, offset, count):
    _ensure_available(data, offset, count * 2)
    return list(struct.unpack_from(f"<{count}H", data, offset))


def _dwords(data, offset, count):
    _ensure_available(data, offset, count * 4)
    return list(struct.unpack_from(f"<{count}I", data, offset))


def _text(data, offset, length):
    _ensure_available(data, offset, length)
    return data[offset:offset + length].split(b"\0", 1)[0].decode("cp1252", errors="replace")


def _identifier_list(data, offset, length):
    return [value for value in _words(data, offset, length // 2) if value]


def parse_setup(data):
    data = bytes(data)
    if not is_setup(data):
        raise CeSetupError("not a Windows CE setup file (no MSCE header)")
    _ensure_available(data, 0, HEADER_SIZE)
    processor_type = _dwords(data, 0x14, 1)[0]
    minimum_major, minimum_minor, maximum_major, maximum_minor, minimum_build, maximum_build = _dwords(data, 0x18, 6)
    string_count, directory_count, file_count, hive_count, key_count, link_count = _words(data, 0x30, 6)
    string_offset, directory_offset, file_offset, hive_offset, key_offset, link_offset = _dwords(data, 0x3C, 6)
    app_offset, app_length, provider_offset, provider_length, unsupported_offset, unsupported_length = _words(data, 0x54, 6)
    unsupported_text = _text(data, unsupported_offset, unsupported_length) if unsupported_length else ""

    setup = CeSetup(
        signature=data[:4],
        processor_type=processor_type,
        minimum_version=(minimum_major, minimum_minor),
        maximum_version=(maximum_major, maximum_minor),
        minimum_build=minimum_build,
        maximum_build=maximum_build,
        app_name=_text(data, app_offset, app_length),
        provider=_text(data, provider_offset, provider_length),
        unsupported=[name.strip() for name in unsupported_text.replace(";", ",").split(",") if name.strip()],
    )

    position = string_offset
    for _ in range(string_count):
        identifier, length = _words(data, position, 2)
        setup.strings[identifier] = _text(data, position + 4, length)
        position += 4 + length

    position = directory_offset
    for _ in range(directory_count):
        identifier, length = _words(data, position, 2)
        setup.directories[identifier] = _identifier_list(data, position + 4, length)
        position += 4 + length

    position = file_offset
    for _ in range(file_count):
        identifier, directory, _ = _words(data, position, 3)
        flags = _dwords(data, position + 6, 1)[0]
        length = _words(data, position + 10, 1)[0]
        setup.files[identifier] = CeSetupFile(identifier, directory, flags, _text(data, position + 12, length))
        position += 12 + length

    position = hive_offset
    for _ in range(hive_count):
        identifier, hive, _, length = _words(data, position, 4)
        setup.hives[identifier] = CeSetupRegistryHive(identifier, hive, _identifier_list(data, position + 8, length))
        position += 8 + length

    position = key_offset
    for _ in range(key_count):
        _, hive, _ = _words(data, position, 3)
        flags = _dwords(data, position + 6, 1)[0]
        length = _words(data, position + 10, 1)[0]
        _ensure_available(data, position + 12, length)
        setup.registry_keys.append(CeSetupRegistryKey(hive, flags, data[position + 12:position + 12 + length]))
        position += 12 + length

    position = link_offset
    for _ in range(link_count):
        fields = _words(data, position, 6)
        setup.links.append(CeSetupLink(fields[:5], _identifier_list(data, position + 12, fields[5])))
        position += 12 + fields[5]

    return setup
