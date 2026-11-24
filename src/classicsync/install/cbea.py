import struct
from dataclasses import dataclass, field
from pathlib import Path

from ..i18n import _, ngettext
from .package import InstallError

HEADER_SIZE = 0x100
COUNT_OFFSET = 2
PLATFORM_OFFSET = 8
PLATFORM_LIMIT = 0x40
MEMBER_FIXED_SIZE = 9
MEMBER_MINIMUM_SIZE = 12
PLATFORM_PREFIX = "Casio "
INSTALL_SCRIPT = "install.inf"
APP_INFORMATION_SECTION = "app information"
TEXT_ENCODINGS = ("shift_jis", "utf-8")
STAGING_DIRECTORY = "\\Temp"
STAGING_PATH = "\\Temp\\install.cbea"
INSTALL_PROGRAM = "CoInstall.exe"
MAIN_MEMORY_SWITCH = "_M"


@dataclass
class CbeaMember:
    name: str
    member_type: int
    data: bytes


@dataclass
class CbeaPackage:
    file_name: str
    data: bytes
    platform: str
    members: list
    info: dict = field(default_factory=dict)

    @property
    def program(self):
        return self.info.get("program") or Path(self.file_name).stem

    @property
    def version(self):
        return self.info.get("version", "")

    @property
    def install_directory(self):
        return self.info.get("installdir", "")

    def describe(self):
        details = [self.platform, ngettext("{count} file", "{count} files", len(self.members)).format(count=len(self.members))]
        if self.install_directory:
            details.append(self.install_directory)
        name = f"{self.program} {self.version}".strip()
        return f"{name} ({', '.join(details)})"


def decode_text(data):
    for encoding in TEXT_ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def platform_name(data):
    text = bytes(data[PLATFORM_OFFSET:PLATFORM_LIMIT]).decode("utf-16-le", errors="replace")
    end = text.find("\0")
    return text if end < 0 else text[:end]


def looks_like_cbea(data):
    return len(data) >= HEADER_SIZE and platform_name(data).startswith(PLATFORM_PREFIX)


def unquote(value):
    value = value.strip()
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == '"' else value


def parse_app_information(script):
    info = {}
    section = None
    for raw_line in decode_text(script).splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            continue
        if section == APP_INFORMATION_SECTION and "=" in line:
            key, value = line.split("=", 1)
            info[key.strip().lower()] = unquote(value)
    return info


def read_cbea(path_or_bytes, file_name=None):
    if isinstance(path_or_bytes, (bytes, bytearray)):
        data = bytes(path_or_bytes)
        file_name = file_name or "package.cbea"
    else:
        path = Path(path_or_bytes)
        data = path.read_bytes()
        file_name = file_name or path.name
    if not looks_like_cbea(data):
        raise InstallError(_("{name} is not a Casio .cbea package").format(name=file_name))
    expected_count = struct.unpack("<H", data[COUNT_OFFSET:COUNT_OFFSET + 2])[0]
    members = []
    position = HEADER_SIZE
    while position + MEMBER_MINIMUM_SIZE <= len(data):
        size = struct.unpack("<I", data[position:position + 4])[0]
        if not size or position + 4 + size > len(data):
            break
        member_type = data[position + 6]
        name_length = data[position + 7]
        name = data[position + 8:position + 8 + name_length].decode("latin-1")
        data_length = struct.unpack("<I", data[position + 9 + name_length:position + 13 + name_length])[0]
        if size != name_length + MEMBER_FIXED_SIZE + data_length:
            break
        start = position + 13 + name_length
        members.append(CbeaMember(name, member_type, data[start:start + data_length]))
        position += 4 + size
    if len(members) != expected_count:
        raise InstallError(_("{name}: the package header lists {expected} files but the package holds {found}; CoInstall would not "
                             "install them all").format(name=file_name, expected=expected_count, found=len(members)))
    checksum = 0
    for value in data[:position]:
        checksum ^= value
    if position >= len(data) or data[position] != checksum:
        raise InstallError(_("{name}: the package checksum does not match; the file is damaged").format(name=file_name))
    script = next((member for member in members if member.name.lower() == INSTALL_SCRIPT), None)
    info = parse_app_information(script.data) if script else {}
    return CbeaPackage(file_name, data, platform_name(data), members, info)
