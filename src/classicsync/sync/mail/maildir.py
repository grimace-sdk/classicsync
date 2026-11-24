import json
import os
import re
import uuid
from email.parser import BytesParser
from email.policy import default as default_policy

from ...i18n import _
from ..objects import MAIL
from ..provider import Store
from .records import STATUS_READ
from .rfc5322 import content_key, local_datetime_from_filetime, message_from_rfc5322, message_to_rfc5322, sender

MAIL_DIRECTORY = "Mail"
KNOWN_FOLDERS_FILE = ".classicsync-folders.json"
SUBDIRECTORIES = ("cur", "new", "tmp")
INFO_SEPARATOR = "!" if os.name == "nt" else ":"
INFO_PREFIX = "2,"
SEEN = "S"
UNSAFE_FOLDER_CHARACTERS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def split_maildir_name(name):
    for separator in (":", "!"):
        unique, found, info = name.partition(separator)
        if found:
            flags = info[len(INFO_PREFIX):] if info.startswith(INFO_PREFIX) else ""
            return unique, flags
    return name, ""


def maildir_name(unique, flags, subdirectory):
    if subdirectory == "new" and not flags:
        return unique
    return f"{unique}{INFO_SEPARATOR}{INFO_PREFIX}{''.join(sorted(set(flags)))}"


def safe_folder_name(name):
    cleaned = UNSAFE_FOLDER_CHARACTERS.sub("_", name).strip(" .")
    return cleaned or "Folder"


def is_maildir(directory):
    return directory.is_dir() and not directory.name.startswith(".") and any(
        (directory / subdirectory).is_dir() for subdirectory in ("cur", "new"))


class MaildirStore(Store):
    object_type = MAIL

    def __init__(self, root, trash, device_name=""):
        self.root = root
        self.directory = root / MAIL_DIRECTORY
        self.trash = trash
        self.device_name = device_name
        self.paths = {}
        self.parsed = {}
        self.directory.mkdir(parents=True, exist_ok=True)

    def stamp(self, path):
        info = path.stat()
        unique, flags = split_maildir_name(path.name)
        return f"{path.parent.parent.name}|{''.join(sorted(flags))}|{info.st_size}|{info.st_mtime_ns}"

    def list_items(self):
        self.paths = {}
        self.parsed = {}
        found = {}
        for folder in sorted(self.directory.iterdir()):
            if not is_maildir(folder):
                continue
            for subdirectory in ("cur", "new"):
                directory = folder / subdirectory
                if not directory.is_dir():
                    continue
                for path in sorted(directory.iterdir()):
                    if path.name.startswith(".") or not path.is_file():
                        continue
                    unique, _ = split_maildir_name(path.name)
                    if unique in found:
                        continue
                    self.paths[unique] = path
                    found[unique] = self.stamp(path)
        return found

    def folder_of(self, item_id):
        return self.paths[item_id].parent.parent.name

    def flags_of(self, item_id):
        return split_maildir_name(self.paths[item_id].name)[1]

    def read_item(self, item_id, device_id):
        if item_id not in self.parsed:
            message = message_from_rfc5322(self.paths[item_id].read_bytes())
            message.folder = self.folder_of(item_id)
            message.flags = STATUS_READ if SEEN in self.flags_of(item_id) else 0
            self.parsed[item_id] = message
        return self.parsed[item_id]

    def new_unique(self, device_id, message):
        moment = local_datetime_from_filetime(message.date)
        seconds = int(moment.timestamp()) if moment else 0
        suffix = device_id or uuid.uuid4().hex[:12]
        return f"{seconds}.{suffix}.classicsync"

    def write_item(self, item_id, device_id, device_object):
        unique = item_id or self.new_unique(device_id, device_object)
        old_path = self.paths.get(unique)
        flags = set(split_maildir_name(old_path.name)[1]) if old_path else set()
        flags.discard(SEEN)
        if device_object.read:
            flags.add(SEEN)
        subdirectory = "cur" if flags or (old_path and old_path.parent.name == "cur") else "new"
        folder = self.create_folder(device_object.folder)
        target = folder / subdirectory / maildir_name(unique, flags, subdirectory)
        partial = folder / "tmp" / unique
        partial.write_bytes(message_to_rfc5322(device_object))
        moment = local_datetime_from_filetime(device_object.date)
        if moment:
            os.utime(partial, (moment.timestamp(), moment.timestamp()))
        partial.replace(target)
        if old_path and old_path != target and old_path.exists():
            old_path.unlink()
        self.paths[unique] = target
        self.parsed.pop(unique, None)
        return unique, self.stamp(target)

    def delete_item(self, item_id, device_id):
        path = self.paths.pop(item_id, None)
        if path is not None:
            self.trash.move(path)

    def matching_key(self, message):
        return message.folder.lower(), content_key(message)

    def find_match(self, device_id, device_object, unmatched_item_ids):
        wanted = self.matching_key(device_object)
        return next((item_id for item_id in unmatched_item_ids
                     if self.matching_key(self.read_item(item_id, None)) == wanted), None)

    def same_content(self, item_id, device_id, device_object):
        return self.read_item(item_id, device_id).read == device_object.read

    def subject(self, item_id):
        try:
            with self.paths[item_id].open("rb") as handle:
                headers = BytesParser(policy=default_policy).parse(handle, headersonly=True)
            return str(headers.get("Subject", ""))
        except (OSError, KeyError):
            return ""

    def describe(self, item_id):
        if item_id not in self.paths:
            return item_id
        subject = self.subject(item_id) or _("(no subject)")
        return f"{MAIL_DIRECTORY}/{self.folder_of(item_id)}: {subject}"

    def describe_device(self, device_id, device_object):
        return f"{device_object.folder}: {device_object.subject or _('(no subject)')}"

    def summary(self, message):
        lines = [_("Subject: {value}").format(value=message.subject or _("(no subject)"))]
        if sender(message):
            lines.append(_("From: {value}").format(value=sender(message)))
        moment = local_datetime_from_filetime(message.date)
        if moment:
            lines.append(_("Date: {value}").format(value=moment.strftime("%d/%m/%Y %H:%M")))
        lines.append(_("Folder: {value}").format(value=message.folder))
        lines.append(_("Read") if message.read else _("Unread"))
        return lines

    def describe_conflict(self, item_id, device_id, device_object):
        return self.summary(self.read_item(item_id, device_id)), self.summary(device_object)

    def folder_names(self):
        return [folder.name for folder in sorted(self.directory.iterdir()) if is_maildir(folder)]

    def create_folder(self, name):
        folder = self.directory / safe_folder_name(name)
        for subdirectory in SUBDIRECTORIES:
            (folder / subdirectory).mkdir(parents=True, exist_ok=True)
        return folder

    def remove_folder(self, name):
        folder = self.directory / safe_folder_name(name)
        if any(path.is_file() for subdirectory in ("cur", "new") for path in (folder / subdirectory).glob("*")):
            return False
        self.trash.move(folder)
        return True

    def known_folders(self):
        try:
            return json.loads((self.directory / KNOWN_FOLDERS_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def save_known_folders(self, names):
        path = self.directory / KNOWN_FOLDERS_FILE
        partial = path.with_name(path.name + ".new")
        partial.write_text(json.dumps(sorted({safe_folder_name(name) for name in names})) + "\n", encoding="utf-8")
        partial.replace(path)
