from dataclasses import dataclass, field
from pathlib import Path

from .formats.cab import CabArchive
from .formats.installshield3 import InstallShield3Archive, is_installshield3
from .formats.pe_resources import PeResourceError, extract_artwork, is_pe
from .formats.sfx import embedded_cabinets
from .paths import data_directory

PRODUCT_MARKERS = [
    ("activesync-3.1", "wcesmgr.exe"),
    ("hpc-explorer-1.1", "hpcexpl.exe"),
    ("ce-services-2.2", "syncmgr.exe"),
]
MAXIMUM_NESTING = 4


class ArtworkImportError(ValueError):
    pass


@dataclass
class ImportedProduct:
    installer: Path
    product: str = None
    directory: Path = None
    modules: list = field(default_factory=list)
    resource_count: int = 0
    sounds: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


@dataclass
class ImportSummary:
    products: list = field(default_factory=list)
    unrecognised: list = field(default_factory=list)


def artwork_root():
    return data_directory() / "artwork"


def base_name(path):
    return path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def archive_members(data, depth=0):
    if depth > MAXIMUM_NESTING:
        return
    if is_installshield3(data):
        archive = InstallShield3Archive(data)
        for entry in archive.entries:
            yield from expand_member(entry.path, archive.read(entry), depth)
        return
    for cabinet_data in embedded_cabinets(data):
        archive = CabArchive(cabinet_data)
        for name in archive.names():
            yield from expand_member(name, archive.read(name), depth)


def expand_member(name, content, depth):
    if is_installshield3(content) or content[:4] == b"MSCF":
        yield from archive_members(content, depth + 1)
    else:
        yield name, content


def detect_product(names):
    lowered = {base_name(name).lower() for name in names}
    for product, marker in PRODUCT_MARKERS:
        if marker in lowered:
            return product
    return None


def write_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def import_installer(installer, destination, progress):
    result = ImportedProduct(Path(installer))
    progress(f"Reading {result.installer.name}")
    members = list(archive_members(result.installer.read_bytes()))
    result.product = detect_product(name for name, _ in members)
    if result.product is None:
        return result
    result.directory = destination / result.product
    seen = set()
    for name, content in members:
        module = base_name(name)
        if not module or module in (".", "..") or module.lower() in seen:
            continue
        if module.lower().endswith(".wav"):
            seen.add(module.lower())
            write_file(result.directory / module, content)
            result.sounds.append(module)
        elif is_pe(content):
            seen.add(module.lower())
            try:
                artwork = extract_artwork(content)
            except PeResourceError as error:
                result.skipped.append(f"{module}: {error}")
                continue
            if not artwork:
                continue
            progress(f"{result.product}: {module} ({len(artwork)} resources)")
            for resource_name, resource in artwork.items():
                write_file(result.directory / module / resource_name, resource)
            result.modules.append(module)
            result.resource_count += len(artwork)
    return result


def import_artwork(installer_paths, destination=None, progress=None):
    destination = Path(destination) if destination else artwork_root()
    progress = progress or (lambda message: None)
    summary = ImportSummary()
    for installer in installer_paths:
        result = import_installer(installer, destination, progress)
        if result.product:
            summary.products.append(result)
        else:
            summary.unrecognised.append(result.installer)
    return summary
