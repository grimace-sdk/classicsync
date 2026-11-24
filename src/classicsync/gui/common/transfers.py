import os
from dataclasses import dataclass, field
from pathlib import Path

REPLACE_OVERWRITE = "replace"
REPLACE_KEEP_BOTH = "keep both"
REPLACE_SKIP = "skip"
REPLACE_CANCEL = "cancel"


def device_join(folder, *names):
    path = folder
    for name in names:
        path = path.rstrip("\\") + "\\" + name
    return path


@dataclass
class TransferTree:
    files: list = field(default_factory=list)
    folders: list = field(default_factory=list)


async def device_tree(client, folder, relative=()):
    tree = TransferTree()
    for child in sorted(await client.find_all_files(device_join(folder, "*.*")), key=lambda entry: entry.name.lower()):
        path = device_join(folder, child.name)
        child_relative = relative + (child.name,)
        if child.is_directory:
            tree.folders.append(child_relative)
            below = await device_tree(client, path, child_relative)
            tree.files += below.files
            tree.folders += below.folders
        else:
            tree.files.append((path, child_relative, child.size))
    return tree


def is_hidden(name):
    return name.startswith(".")


def local_tree(paths):
    tree = TransferTree()
    for path in (Path(item) for item in paths):
        if path.is_file():
            tree.files.append((path, (path.name,), path.stat().st_size))
        elif path.is_dir():
            tree.folders.append((path.name,))
            for root, folders, files in os.walk(path):
                folders[:] = sorted(name for name in folders if not is_hidden(name))
                base = (path.name,) + Path(root).relative_to(path).parts
                tree.folders += [base + (name,) for name in folders]
                tree.files += [(Path(root) / name, base + (name,), (Path(root) / name).stat().st_size)
                               for name in sorted(files) if not is_hidden(name)]
    return tree


def unused_path(path, taken=()):
    counter = 2
    candidate = path
    while candidate.exists() or candidate in taken:
        candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
        counter += 1
    return candidate
