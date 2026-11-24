from dataclasses import dataclass
from pathlib import Path

from ..formats.cab import CabArchive, CabError
from ..rapi.structures import PROCESSOR_NAMES
from .cesetup import PROCESSOR_ANY, CeSetupError, is_setup, parse_setup

SETUP_MEMBER_SUFFIX = ".000"

MIPS_PROCESSORS = (3000, 3910, 3912, 4000, 4100, 4111, 4121, 4200, 4300)
SH3_PROCESSORS = (10003, 10004, 103)
SH4_PROCESSORS = (10005, 104)
ARM_PROCESSORS = (1824, 2080, 2336, 2577, 70001)
PROCESSOR_FAMILIES = (MIPS_PROCESSORS, SH3_PROCESSORS, SH4_PROCESSORS, ARM_PROCESSORS)


class InstallError(ValueError):
    pass


def processor_family(processor_type):
    for family in PROCESSOR_FAMILIES:
        if processor_type in family:
            return family
    return (processor_type,)


def processor_name(processor_type):
    if processor_type == PROCESSOR_ANY:
        return "any processor"
    return PROCESSOR_NAMES.get(processor_type, f"processor type {processor_type}")


@dataclass
class CabPackage:
    path: Path
    file_name: str
    data: bytes
    setup_member: str
    setup: object
    installed_size: int

    @property
    def app_name(self):
        return self.setup.app_name

    @property
    def uninstall_name(self):
        return self.setup.uninstall_name

    @property
    def processor_type(self):
        return self.setup.processor_type

    @property
    def size(self):
        return len(self.data)

    def describe(self):
        parts = [self.app_name or self.file_name]
        if self.setup.provider:
            parts.append(f"by {self.setup.provider}")
        parts.append(f"for {processor_name(self.processor_type)}")
        minimum = self.setup.minimum_version
        if any(minimum):
            parts.append(f"Windows CE {minimum[0]}.{minimum[1]:02d} or later")
        return ", ".join(parts)


def find_setup_member(archive):
    for entry in archive.files:
        if entry.name.lower().endswith(SETUP_MEMBER_SUFFIX):
            data = archive.read(entry)
            if is_setup(data):
                return entry.name, data
    return None, None


def read_cab_package(path_or_bytes, file_name=None):
    if isinstance(path_or_bytes, (bytes, bytearray)):
        path = None
        data = bytes(path_or_bytes)
    else:
        path = Path(path_or_bytes)
        data = path.read_bytes()
    file_name = file_name or (path.name if path else "package.cab")
    try:
        archive = CabArchive(data)
        member, setup_data = find_setup_member(archive)
    except CabError as error:
        raise InstallError(f"{file_name}: {error}") from error
    if member is None:
        raise InstallError(f"\"{file_name}\" contains invalid Windows CE CAB header data.")
    try:
        setup = parse_setup(setup_data)
    except CeSetupError as error:
        raise InstallError(f"{file_name}: {error}") from error
    installed_size = sum(entry.size for entry in archive.files if entry.name != member)
    return CabPackage(path, file_name, data, member, setup, installed_size)


@dataclass
class DeviceProfile:
    os_major: int
    os_minor: int
    os_build: int
    processor_type: int
    platform: str = ""

    @property
    def version(self):
        return (self.os_major, self.os_minor)

    def describe(self):
        return f"Windows CE {self.os_major}.{self.os_minor:02d} on {processor_name(self.processor_type)}"


def compatibility_problem(package, profile):
    setup = package.setup
    if setup.processor_type != PROCESSOR_ANY and profile.processor_type not in processor_family(setup.processor_type):
        return f"{package.app_name or package.file_name} is built for {processor_name(setup.processor_type)}; the device has {processor_name(profile.processor_type)}."
    if any(setup.minimum_version) and profile.version < setup.minimum_version:
        major, minor = setup.minimum_version
        return f"{package.app_name or package.file_name} needs Windows CE {major}.{minor:02d} or later; the device runs {profile.os_major}.{profile.os_minor:02d}."
    if any(setup.maximum_version) and profile.version > setup.maximum_version:
        major, minor = setup.maximum_version
        return f"{package.app_name or package.file_name} supports Windows CE up to {major}.{minor:02d}; the device runs {profile.os_major}.{profile.os_minor:02d}."
    if setup.minimum_build and profile.os_build < setup.minimum_build:
        return f"{package.app_name or package.file_name} needs Windows CE build {setup.minimum_build} or later."
    if setup.maximum_build and profile.os_build > setup.maximum_build:
        return f"{package.app_name or package.file_name} supports Windows CE builds up to {setup.maximum_build}."
    platform = profile.platform.lower()
    if platform and any(name.lower() == platform for name in setup.unsupported):
        return f"{package.app_name or package.file_name} does not support {profile.platform} devices."
    return None


def is_exact_processor(package, profile):
    return package.setup.processor_type != PROCESSOR_ANY and profile.processor_type in processor_family(package.setup.processor_type)
