import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ...i18n import _, format_message
from ...rapi.structures import filetime_to_datetime

REPLACE_OVERWRITE = "replace"
REPLACE_ALL = "replace all"
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
    modified: dict = field(default_factory=dict)

    def add(self, other):
        self.files += other.files
        self.folders += other.folders
        self.modified.update(other.modified)


def device_moment(filetime):
    moment = filetime_to_datetime(filetime) if filetime else None
    return moment.replace(tzinfo=timezone.utc) if moment and moment.tzinfo is None else moment


def local_moment(path):
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


async def device_tree(client, folder, relative=()):
    tree = TransferTree()
    for child in sorted(await client.find_all_files(device_join(folder, "*.*")), key=lambda entry: entry.name.lower()):
        path = device_join(folder, child.name)
        child_relative = relative + (child.name,)
        if child.is_directory:
            tree.folders.append(child_relative)
            tree.add(await device_tree(client, path, child_relative))
        else:
            tree.files.append((path, child_relative, child.size))
            tree.modified[child_relative] = device_moment(child.last_write_time)
    return tree


def is_hidden(name):
    return name.startswith(".")


def local_tree(paths):
    tree = TransferTree()
    for path in (Path(item) for item in paths):
        if path.is_file():
            tree.files.append((path, (path.name,), path.stat().st_size))
            tree.modified[(path.name,)] = local_moment(path)
        elif path.is_dir():
            tree.folders.append((path.name,))
            for root, folders, files in os.walk(path):
                folders[:] = sorted(name for name in folders if not is_hidden(name))
                base = (path.name,) + Path(root).relative_to(path).parts
                tree.folders += [base + (name,) for name in folders]
                for name in sorted(files):
                    if is_hidden(name):
                        continue
                    file_path = Path(root) / name
                    tree.files.append((file_path, base + (name,), file_path.stat().st_size))
                    tree.modified[base + (name,)] = local_moment(file_path)
    return tree


def copy_name(name, existing):
    candidate = format_message(_("%1Copy of %2"), "", name)
    counter = 2
    while candidate.lower() in existing:
        candidate = format_message(_("%1Copy (%3!d!) of %2"), "", name, counter)
        counter += 1
    return candidate


def shortcut_name(name, existing):
    base = name if "." not in name else os.path.splitext(name)[0]
    candidate = format_message(_("%1Shortcut to %2.lnk"), "", base)
    counter = 2
    while candidate.lower() in existing:
        candidate = format_message(_("%1Shortcut (%3!d!) to %2.lnk"), "", base, counter)
        counter += 1
    return candidate


def unused_path(path, taken=()):
    counter = 2
    candidate = path
    while candidate.exists() or candidate in taken:
        candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
        counter += 1
    return candidate


def lower_key(relative):
    return tuple(part.lower() for part in relative)


@dataclass
class TransferPlan:
    jobs: list = field(default_factory=list)
    folders: list = field(default_factory=list)
    outcomes: dict = field(default_factory=lambda: {"replaced": 0, "renamed": 0, "skipped": 0})
    cancelled: bool = False


def plan_transfer(tree, prompt, destination, existing_file, existing_folder, incoming_facts, keep_both=None):
    plan = TransferPlan()
    skipped_folders = []
    for relative in tree.folders:
        if any(relative[:len(skipped)] == skipped for skipped in skipped_folders):
            continue
        target = destination(relative)
        if len(relative) == 1 and existing_folder(target):
            choice = prompt.ask_folder(target[-1])
            if choice == REPLACE_CANCEL:
                plan.cancelled = True
                return plan
            if choice == REPLACE_SKIP:
                skipped_folders.append(relative)
                continue
        plan.folders.append(target)
    taken = set()
    for source, relative, size in tree.files:
        if any(relative[:len(skipped)] == skipped for skipped in skipped_folders):
            continue
        target = destination(relative)
        existing = existing_file(target)
        if existing is not None or lower_key(target) in taken:
            choice = prompt.ask_file(target[-1], existing, incoming_facts(source, relative, size))
            if choice == REPLACE_CANCEL:
                plan.cancelled = True
                return plan
            if choice == REPLACE_SKIP:
                plan.outcomes["skipped"] += 1
                continue
            if choice == REPLACE_KEEP_BOTH and keep_both:
                target = keep_both(target, taken)
                plan.outcomes["renamed"] += 1
            else:
                plan.outcomes["replaced"] += 1
        taken.add(lower_key(target))
        plan.jobs.append((source, target, size))
    return plan
