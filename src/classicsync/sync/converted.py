import hashlib
import json
import logging

from ..convert import DESKTOP_DEFAULTS, FORMATS, ConversionError, converter, format_for_extension
from ..i18n import _

log = logging.getLogger("classicsync.sync.converted")

CONVERTED_FOLDER = "Converted"
INDEX_NAME = ".classicsync-converted.json"
DEVICE_EXTENSIONS = {name: FORMATS[name].extensions[0] for name in DESKTOP_DEFAULTS}


def file_hash(data):
    return hashlib.sha1(data).hexdigest()


def stamp(path):
    info = path.stat()
    return [info.st_mtime_ns, info.st_size]


class ConvertedMirror:
    def __init__(self, root, folders, os_major, report):
        self.root = root
        self.folders = folders
        self.version = 1 if os_major == 1 else 2
        self.report = report
        self.directory = root / CONVERTED_FOLDER
        self.index_path = self.directory / INDEX_NAME
        self.index = self._load_index()

    def _load_index(self):
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_index(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(self.index, indent=1, sort_keys=True), encoding="utf-8")

    def device_format(self, item_id):
        name = format_for_extension("." + item_id.rpartition(".")[2]) if "." in item_id else None
        return name if name in DESKTOP_DEFAULTS else None

    def converted_path_for(self, item_id, device_format):
        folder, _, name = item_id.rpartition("/")
        stem = name.rpartition(".")[0] or name
        extension = FORMATS[DESKTOP_DEFAULTS[device_format]].extensions[0]
        candidate = self.directory.joinpath(*folder.split("/"), stem + extension) if folder else self.directory / (stem + extension)
        owner = next((raw for raw, entry in self.index.items() if entry["converted"] == self._relative(candidate)), None)
        if owner not in (None, item_id):
            candidate = candidate.with_name(name + extension)
        return candidate

    def _relative(self, path):
        return path.relative_to(self.directory).as_posix()

    def _warn(self, name, warnings):
        for warning in warnings:
            self.report(_("{name}: {warning}").format(name=name, warning=warning))

    def update_from_raw(self, item_id, raw_path):
        device_format = self.device_format(item_id)
        if not device_format:
            return
        data = raw_path.read_bytes()
        target = self.converted_path_for(item_id, device_format)
        try:
            conversion = converter(device_format, DESKTOP_DEFAULTS[device_format])(data)
        except (ConversionError, ValueError) as error:
            log.info("could not convert %s: %s", item_id, error)
            self.report(_("{name} could not be converted: {error}").format(name=item_id, error=error))
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(conversion.data)
        self._warn(item_id, conversion.warnings)
        self.index[item_id] = {"raw_hash": file_hash(data), "converted": self._relative(target), "stamp": stamp(target)}
        self._save_index()

    def remove(self, item_id, trash):
        entry = self.index.pop(item_id, None)
        if entry:
            path = self.directory / entry["converted"]
            if path.exists():
                trash.move(path)
            self._save_index()

    def refresh(self, path_for):
        changed = False
        for item_id, entry in list(self.index.items()):
            converted = self.directory / entry["converted"]
            raw = path_for(item_id)
            if not raw.exists():
                continue
            if not converted.exists():
                self.update_from_raw(item_id, raw)
                continue
            if stamp(converted) != entry["stamp"]:
                changed |= self._write_back(item_id, raw, converted, entry)
            elif file_hash(raw.read_bytes()) != entry["raw_hash"]:
                self.update_from_raw(item_id, raw)
        changed |= self._adopt_new_files(path_for)
        self._regenerate_missing(path_for)
        if changed:
            self._save_index()

    def _write_back(self, item_id, raw, converted, entry):
        device_format = self.device_format(item_id)
        try:
            conversion = converter(DESKTOP_DEFAULTS[device_format], device_format)(converted.read_bytes(), version=self.version)
        except (ConversionError, ValueError) as error:
            self.report(_("{name} could not be converted back: {error}").format(name=entry["converted"], error=error))
            return False
        raw.write_bytes(conversion.data)
        self._warn(entry["converted"], conversion.warnings)
        entry.update(raw_hash=file_hash(conversion.data), stamp=stamp(converted))
        return True

    def _adopt_new_files(self, path_for):
        known = {entry["converted"] for entry in self.index.values()}
        desktop_formats = {FORMATS[name].extensions[0]: device for device, name in DESKTOP_DEFAULTS.items()
                           if self.version == 1 or device != "2bp"}
        adopted = False
        for folder in self.folders:
            base = self.directory / folder
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if not path.is_file() or path.name.startswith(".") or self._relative(path) in known:
                    continue
                device_format = desktop_formats.get(path.suffix.lower())
                if not device_format:
                    continue
                relative = self._relative(path)
                item_id = relative.rpartition(".")[0] + DEVICE_EXTENSIONS[device_format]
                raw = path_for(item_id)
                if raw.exists():
                    continue
                try:
                    conversion = converter(DESKTOP_DEFAULTS[device_format], device_format)(path.read_bytes(), version=self.version)
                except (ConversionError, ValueError) as error:
                    self.report(_("{name} could not be converted: {error}").format(name=relative, error=error))
                    continue
                raw.parent.mkdir(parents=True, exist_ok=True)
                raw.write_bytes(conversion.data)
                self._warn(relative, conversion.warnings)
                self.index[item_id] = {"raw_hash": file_hash(conversion.data), "converted": relative, "stamp": stamp(path)}
                adopted = True
        return adopted

    def _regenerate_missing(self, path_for):
        for folder in self.folders:
            base = path_for(folder)
            if not base.is_dir():
                continue
            for raw in sorted(base.rglob("*")):
                if not raw.is_file() or raw.name.startswith("."):
                    continue
                item_id = raw.relative_to(base.parent).as_posix()
                if item_id not in self.index and self.device_format(item_id):
                    self.update_from_raw(item_id, raw)
