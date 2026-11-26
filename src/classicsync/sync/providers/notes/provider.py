import hashlib
import json
import posixpath
from datetime import datetime, timezone
from pathlib import Path

from ....convert.errors import ConversionError, Report
from ....convert.rtf_reader import read_rtf
from ....convert.rtf_writer import write_pocket_word
from ....i18n import N_, _
from ....rapi.structures import datetime_to_filetime
from ...folder import Trash, default_folder, write_file_atomically
from ...objects import KIND_FILES, DeviceFile, ObjectType
from ...provider import DeviceFolders, Provider, Store
from ...settings_schema import Setting
from .markdown import document_from_markdown, markdown_from_document, markdown_from_text
from .pwi import is_pwi, pwi_text

NOTES = ObjectType("notes", "Note", N_("Notes"), KIND_FILES, conflict_default="keep_both")
MARKDOWN_EXTENSION = ".md"
INK_EXTENSION = ".pwi"
WORD_EXTENSION = ".pwd"
KIND_INK = "ink"
KIND_WORD = "word"
KIND_TEXT = "text"
TEXT_EXTENSION = ".txt"
TEXT_NOTES_PLATFORM = "palm"
CACHE_FOLDER = "notes"
INDEX_NAME = "index.json"
EDITED_SUFFIX = N_("edited")


def text_hash(data):
    return hashlib.sha1(data).hexdigest()


def root_name(folder):
    return folder.strip("\\").split("\\")[-1]


def device_markdown(device_object):
    data = device_object.data
    if is_pwi(data):
        return markdown_from_text(pwi_text(data))
    return markdown_from_document(read_rtf(data, Report()))


def note_kind(device_id):
    return KIND_INK if device_id.lower().endswith(INK_EXTENSION) else KIND_WORD


class NoteStore(Store):
    object_type = NOTES

    def __init__(self, root, cache_directory, folders, depth, os_major, report, word_documents=True, text_notes=False):
        self.root = root
        self.word_documents = word_documents
        self.text_notes = text_notes
        self.cache_directory = cache_directory
        self.raw_directory = cache_directory / "raw"
        self.index_path = cache_directory / INDEX_NAME
        self.root_names = [root_name(folder) for folder in folders]
        self.depth = depth
        self.version = 1 if os_major <= 1 else 2
        self.report = report
        self.trash = Trash(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.index = self.load_index()

    def load_index(self):
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_index(self):
        write_file_atomically(self.index_path, json.dumps(self.index, indent=1, sort_keys=True).encode("utf-8"))

    def kind_of(self, device_id):
        return KIND_TEXT if self.text_notes else note_kind(device_id)

    def device_markdown(self, device_object):
        return device_object.data.decode("utf-8", errors="replace") if self.text_notes else device_markdown(device_object)

    def device_name(self, device_id, device_object):
        return device_object.path if self.text_notes else device_id

    def path_for(self, item_id):
        return self.root.joinpath(*item_id.split("/"))

    def raw_path(self, device_id):
        return self.raw_directory.joinpath(*device_id.split("/"))

    def raw_data(self, device_id):
        if not device_id:
            return None
        path = self.raw_path(device_id)
        return path.read_bytes() if path.exists() else None

    def scan(self):
        found = {}
        for path in sorted(self.root.rglob("*" + MARKDOWN_EXTENSION)):
            relative = path.relative_to(self.root)
            if any(part.startswith(".") for part in relative.parts) or not path.is_file():
                continue
            found[relative.as_posix()] = path
        return found

    def unique_item_id(self, wanted):
        folder, _, name = wanted.rpartition("/")
        stem = name[:-len(MARKDOWN_EXTENSION)]
        candidate = wanted
        counter = 2
        while self.path_for(candidate).exists() or candidate in self.index:
            candidate = f"{folder}/{stem} {counter}{MARKDOWN_EXTENSION}" if folder else f"{stem} {counter}{MARKDOWN_EXTENSION}"
            counter += 1
        return candidate

    def keep_ink_edits(self):
        for item_id, entry in list(self.index.items()):
            if entry.get("kind") != KIND_INK:
                continue
            path = self.path_for(item_id)
            raw = self.raw_data(entry.get("device"))
            if not path.exists() or raw is None or text_hash(path.read_bytes()) == entry.get("hash"):
                continue
            stem = item_id[:-len(MARKDOWN_EXTENSION)]
            copy_id = self.unique_item_id(f"{stem} ({_(EDITED_SUFFIX)}){MARKDOWN_EXTENSION}")
            path.replace(self.path_for(copy_id))
            self.write_markdown(item_id, markdown_from_text(pwi_text(raw)).encode("utf-8"))
            entry["hash"] = text_hash(self.path_for(item_id).read_bytes())
            self.report(_("{name} is an ink note, which is kept as it is on the device; your changes were saved as {copy}").format(
                name=item_id, copy=copy_id))
            self.save_index()

    def list_items(self):
        self.keep_ink_edits()
        found = self.scan()
        stale = [item_id for item_id in self.index if item_id not in found]
        for item_id in stale:
            self.index.pop(item_id)
        if stale:
            self.save_index()
        return {item_id: text_hash(path.read_bytes()) for item_id, path in found.items()
                if self.word_documents or self.text_notes or item_id in self.index}

    def device_id_for(self, item_id):
        stem = item_id[:-len(MARKDOWN_EXTENSION)]
        first = stem.split("/")[0]
        if first not in self.root_names or "/" not in stem:
            stem = f"{self.root_names[0]}/{stem}"
        return stem + WORD_EXTENSION

    def read_item(self, item_id, device_id):
        markdown = self.path_for(item_id).read_bytes()
        if self.text_notes:
            return DeviceFile(item_id[:-len(MARKDOWN_EXTENSION)] + TEXT_EXTENSION, markdown, self.modified(item_id))
        raw = self.raw_data(device_id)
        if raw is not None and (is_pwi(raw) or self.index.get(item_id, {}).get("hash") == text_hash(markdown)):
            return DeviceFile(device_id, raw, self.modified(item_id))
        if device_id and note_kind(device_id) == KIND_INK:
            return None
        document = document_from_markdown(markdown.decode("utf-8", errors="replace"))
        data = write_pocket_word(document, Report(), self.version)
        return DeviceFile(device_id or self.device_id_for(item_id), data, self.modified(item_id))

    def modified(self, item_id):
        seconds = self.path_for(item_id).stat().st_mtime
        return datetime_to_filetime(datetime.fromtimestamp(seconds, timezone.utc))

    def write_markdown(self, item_id, data):
        write_file_atomically(self.path_for(item_id), data)

    def item_id_for(self, device_id):
        return self.unique_item_id(posixpath.splitext(device_id)[0] + MARKDOWN_EXTENSION)

    def remember(self, item_id, device_id, device_object):
        write_file_atomically(self.raw_path(device_id), device_object.data)
        self.index[item_id] = {"device": device_id, "kind": self.kind_of(device_id),
                               "hash": text_hash(self.path_for(item_id).read_bytes())}
        self.save_index()

    def write_item(self, item_id, device_id, device_object):
        try:
            markdown = self.device_markdown(device_object).encode("utf-8")
        except (ConversionError, ValueError) as error:
            raise ValueError(_("{name} could not be read: {error}").format(name=device_object.path, error=error)) from error
        device_id = device_id or device_object.path
        item_id = item_id or self.item_id_for(self.device_name(device_id, device_object))
        self.write_markdown(item_id, markdown)
        self.remember(item_id, device_id, device_object)
        return item_id, text_hash(markdown)

    def device_updated(self, item_id, device_id, device_object):
        write_file_atomically(self.raw_path(device_id), device_object.data)
        self.index[item_id] = {"device": device_id, "kind": self.kind_of(device_id),
                               "hash": text_hash(self.path_for(item_id).read_bytes())}
        self.save_index()

    def delete_item(self, item_id, device_id):
        self.trash.move(self.path_for(item_id))
        self.index.pop(item_id, None)
        if device_id:
            self.raw_path(device_id).unlink(missing_ok=True)
        self.save_index()

    def find_match(self, device_id, device_object, unmatched_item_ids):
        wanted = (posixpath.splitext(self.device_name(device_id, device_object))[0] + MARKDOWN_EXTENSION).lower()
        return next((item_id for item_id in unmatched_item_ids if item_id.lower() == wanted), None)

    def same_content(self, item_id, device_id, device_object):
        try:
            return self.device_markdown(device_object).encode("utf-8") == self.path_for(item_id).read_bytes()
        except (ConversionError, ValueError):
            return False

    def describe_device(self, device_id, device_object):
        return self.device_name(device_id, device_object)


def notes_root(settings, device_name):
    if settings.get("notes_folder"):
        return Path(settings["notes_folder"]).expanduser()
    base = Path(settings["folder"]).expanduser() if settings.get("folder") else default_folder(device_name)
    return base / "Notes"


class NotesProvider(Provider):
    name = "notes"
    display_name = N_("Notes as Markdown")
    object_types = (NOTES,)
    settings_schema = (
        Setting("notes_folder", N_("Markdown folder"), "path", per_device=True,
                help=N_("Where the Markdown copies of notes are kept. Empty: a Notes folder in the device's synchronization folder.")),
        Setting("notes_device_folders", N_("Device folders"), "list", ["\\My Documents"],
                help=N_("Device folders holding notes.")),
        Setting("notes_depth", N_("Subfolder depth"), "int", 1, minimum=0,
                help=N_("How many levels of subfolders to include below each device folder.")),
        Setting("notes_word_documents", N_("Include Pocket Word files"), "bool", True,
                help=N_("Also synchronize Pocket Word (.pwd) files as notes. New Markdown files become Pocket Word files, "
                        "so without this they stay on this computer.")),
    )

    def __init__(self, context):
        super().__init__(context)
        settings = context.settings
        self.root = notes_root(settings, context.device.name)
        self.folders = list(settings.get("notes_device_folders") or ["\\My Documents"])
        self.depth = settings.get("notes_depth", 1)
        self.word_documents = settings.get("notes_word_documents", True)

    def device_folders(self, object_type):
        extensions = (INK_EXTENSION, WORD_EXTENSION) if self.word_documents else (INK_EXTENSION,)
        return DeviceFolders(self.folders, self.depth, extensions)

    def open_store(self, object_type):
        if object_type.key != NOTES.key:
            raise ValueError(f"notes provider does not handle {object_type.key}")
        return NoteStore(self.root, self.context.partnership_directory / CACHE_FOLDER, self.folders, self.depth,
                         self.context.device.os_major, self.context.message, self.word_documents,
                         self.context.device.extra.get("platform") == TEXT_NOTES_PLATFORM)


PROVIDERS = [NotesProvider]
