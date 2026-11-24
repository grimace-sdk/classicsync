import hashlib
import json
import logging
import sys
from pathlib import Path

from ..convert import DESKTOP_DEFAULTS, FORMATS, Conversion, ConversionError, converter, format_for_extension
from ..convert.errors import Report
from ..convert.registry import DOCUMENT, IMAGE, SPREADSHEET
from ..convert.workbook import Cell, CellStyle, display_value
from ..i18n import N_, _

log = logging.getLogger("classicsync.sync.converted")

CONVERTED_FOLDER = "Converted"
INDEX_NAME = ".classicsync-converted.json"
DEVICE_EXTENSIONS = {name: FORMATS[name].extensions[0] for name in DESKTOP_DEFAULTS}
APPLICATIONS_FOLDER = Path("/Applications")
SPREADSHEET_APPLICATIONS = ("Numbers.app", "Microsoft Excel.app")
DESKTOP_CHOICES = {
    DOCUMENT: (("rtf", N_("Rich Text (.rtf)")), ("docx", N_("Word (.docx)")), ("odt", N_("OpenDocument (.odt)")),
               ("html", N_("Web page (.html)")), ("txt", N_("Plain text (.txt)"))),
    SPREADSHEET: (("xlsx", N_("Excel (.xlsx)")), ("ods", N_("OpenDocument (.ods)")),
                  ("csv", N_("Comma-separated values (.csv, first sheet only)"))),
    IMAGE: (("png", N_("PNG (.png)")), ("bmp", N_("Bitmap (.bmp)"))),
}


def default_formats(platform=None, applications=None):
    platform = platform or sys.platform
    applications = applications or APPLICATIONS_FOLDER
    if platform == "darwin":
        has_spreadsheet_application = any((applications / name).exists() for name in SPREADSHEET_APPLICATIONS)
        return {DOCUMENT: "rtf", SPREADSHEET: "xlsx" if has_spreadsheet_application else "csv", IMAGE: "png"}
    return {DOCUMENT: "docx", SPREADSHEET: "xlsx", IMAGE: "png"}


def desktop_choices(kind):
    return [name for name, _ in DESKTOP_CHOICES[kind]]


def file_hash(data):
    return hashlib.sha1(data).hexdigest()


def stamp(path):
    info = path.stat()
    return [info.st_mtime_ns, info.st_size]


def merge_first_sheet(original, edited):
    for key in set(original.cells) | set(edited.cells):
        old = original.cells.get(key)
        new = edited.cells.get(key)
        if new is None:
            if old is not None and (old.value is not None or old.formula):
                del original.cells[key]
        elif old is None:
            original.cells[key] = new
        elif display_value(old) != display_value(new) or (old.formula is None and new.formula):
            style = new.style if new.style != CellStyle() else old.style
            original.cells[key] = Cell(new.value, new.formula, style)


class ConvertedMirror:
    def __init__(self, root, folders, os_major, report, formats=None, trash=None):
        self.root = root
        self.folders = folders
        self.version = 1 if os_major == 1 else 2
        self.report = report
        self.formats = {**default_formats(), **(formats or {})}
        self.trash = trash
        self.directory = root / CONVERTED_FOLDER
        self.index_path = self.directory / INDEX_NAME
        self.index = self._load_index()

    def _load_index(self):
        try:
            index = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        for entry in index.values():
            if "format" not in entry:
                entry["format"] = format_for_extension(Path(entry["converted"]).suffix) or ""
            entry.setdefault("chosen", entry["format"])
        return index

    def _save_index(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(self.index, indent=1, sort_keys=True), encoding="utf-8")

    def device_format(self, item_id):
        name = format_for_extension("." + item_id.rpartition(".")[2]) if "." in item_id else None
        return name if name in DESKTOP_DEFAULTS else None

    def desktop_format(self, device_format):
        kind = FORMATS[device_format].kind
        chosen = self.formats.get(kind)
        return chosen if chosen in desktop_choices(kind) else DESKTOP_DEFAULTS[device_format]

    def accepted_formats(self, device_format):
        kind = FORMATS[device_format].kind
        return desktop_choices(kind)

    def converted_path_for(self, item_id, device_format):
        folder, _, name = item_id.rpartition("/")
        stem = name.rpartition(".")[0] or name
        extension = FORMATS[self.desktop_format(device_format)].extensions[0]
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

    def _discard(self, path):
        if not path.exists():
            return
        if self.trash is not None:
            self.trash.move(path)
        else:
            path.unlink()

    def update_from_raw(self, item_id, raw_path):
        device_format = self.device_format(item_id)
        if not device_format:
            return
        data = raw_path.read_bytes()
        desktop_format = self.desktop_format(device_format)
        target = self.converted_path_for(item_id, device_format)
        try:
            conversion = converter(device_format, desktop_format)(data)
        except (ConversionError, ValueError) as error:
            log.info("could not convert %s: %s", item_id, error)
            self.report(_("{name} could not be converted: {error}").format(name=item_id, error=error))
            return
        previous = self.index.get(item_id)
        if previous and previous["converted"] != self._relative(target):
            self._discard(self.directory / previous["converted"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(conversion.data)
        self._warn(item_id, conversion.warnings)
        self.index[item_id] = {"raw_hash": file_hash(data), "converted": self._relative(target), "stamp": stamp(target),
                               "format": desktop_format, "chosen": desktop_format}
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
                continue
            device_format = self.device_format(item_id)
            if device_format and entry.get("chosen") != self.desktop_format(device_format):
                self.update_from_raw(item_id, raw)
        changed |= self._adopt_new_files(path_for)
        self._regenerate_missing(path_for)
        if changed:
            self._save_index()

    def to_device(self, desktop_format, device_format, data, raw_data=None):
        if desktop_format == "csv" and raw_data:
            report = Report()
            try:
                original = FORMATS[device_format].reader(raw_data, report)
            except (ConversionError, ValueError):
                original = None
            if original is not None and original.sheets:
                edited = FORMATS["csv"].reader(data, report)
                merge_first_sheet(original.sheets[0], edited.sheets[0])
                output = FORMATS[device_format].writer(original, report, version=self.version)
                return Conversion(output, desktop_format, device_format, report.warnings)
        return converter(desktop_format, device_format)(data, version=self.version)

    def _write_back(self, item_id, raw, converted, entry):
        device_format = self.device_format(item_id)
        desktop_format = entry.get("format") or format_for_extension(converted.suffix)
        try:
            conversion = self.to_device(desktop_format, device_format, converted.read_bytes(), raw.read_bytes())
        except (ConversionError, ValueError) as error:
            self.report(_("{name} could not be converted back: {error}").format(name=entry["converted"], error=error))
            return False
        raw.write_bytes(conversion.data)
        self._warn(entry["converted"], conversion.warnings)
        entry.update(raw_hash=file_hash(conversion.data), stamp=stamp(converted))
        return True

    def _adopt_new_files(self, path_for):
        known = {entry["converted"] for entry in self.index.values()}
        desktop_formats = {}
        for device_format in DESKTOP_DEFAULTS:
            if device_format == "2bp" and self.version != 1:
                continue
            for desktop_format in self.accepted_formats(device_format):
                for extension in FORMATS[desktop_format].extensions:
                    desktop_formats[extension] = (desktop_format, device_format)
        adopted = False
        for folder in self.folders:
            base = self.directory / folder
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if not path.is_file() or path.name.startswith(".") or self._relative(path) in known:
                    continue
                formats = desktop_formats.get(path.suffix.lower())
                if not formats:
                    continue
                desktop_format, device_format = formats
                relative = self._relative(path)
                item_id = relative.rpartition(".")[0] + DEVICE_EXTENSIONS[device_format]
                raw = path_for(item_id)
                if raw.exists():
                    continue
                try:
                    conversion = self.to_device(desktop_format, device_format, path.read_bytes())
                except (ConversionError, ValueError) as error:
                    self.report(_("{name} could not be converted: {error}").format(name=relative, error=error))
                    continue
                raw.parent.mkdir(parents=True, exist_ok=True)
                raw.write_bytes(conversion.data)
                self._warn(relative, conversion.warnings)
                self.index[item_id] = {"raw_hash": file_hash(conversion.data), "converted": relative, "stamp": stamp(path),
                                       "format": desktop_format, "chosen": self.desktop_format(device_format)}
                known.add(relative)
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
