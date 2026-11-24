import hashlib
import html
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from ....i18n import N_, _
from ....rapi.structures import datetime_to_filetime
from ...folder import write_file_atomically
from ...objects import KIND_FILES, DeviceFile, ObjectType
from ...provider import DeviceFolders, Provider, Store
from ...settings_schema import Setting
from .fetch import FetchError, decode_page, device_image, fetch
from .simplify import page_document, shorten, simplify_html

FAVORITES = ObjectType("favorites", "Favorite", N_("Favorites"), KIND_FILES, conflict_default="desktop")
CACHE_FOLDER = "favorites"
STATE_NAME = "state.json"
INDEX_PAGE = "index.htm"
PAGE_EXTENSION = ".htm"
SHORTCUT_EXTENSION = ".url"
IMAGE_EXTENSIONS = (".gif", ".jpg", ".bmp")
DEVICE_EDITED_STAMP = "device-edited"
MOST_IMAGE_DOWNLOAD = 512 * 1024
DEFAULT_PAGE_FOLDER = "\\My Documents\\Offline Pages"
DEFAULT_SHORTCUT_FOLDER = "\\Windows\\Favorites\\Mobile Favorites"


def content_hash(data):
    return hashlib.sha1(data).hexdigest()


def root_name(folder):
    return folder.strip("\\").split("\\")[-1]


def device_path(folder):
    return "\\" + folder.strip("\\")


def file_stem(text, limit=40):
    cleaned = re.sub(r"[^\w\- ]+", "", text, flags=re.UNICODE).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)[:limit].strip()
    return cleaned or "page"


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


class OfflinePages:
    def __init__(self, cache_directory, settings, report):
        self.cache_directory = cache_directory
        self.pages_directory = cache_directory / "pages"
        self.shortcuts_directory = cache_directory / "shortcuts"
        self.foreign_directory = cache_directory / "device"
        self.state_path = cache_directory / STATE_NAME
        self.urls = [url.strip() for url in settings.get("favorites_urls") or [] if url.strip()]
        self.page_folder = device_path(settings.get("favorites_device_folder") or DEFAULT_PAGE_FOLDER)
        self.shortcut_folder = device_path(settings.get("favorites_shortcut_folder") or DEFAULT_SHORTCUT_FOLDER)
        self.shortcuts = bool(settings.get("favorites_shortcuts", False))
        if self.shortcuts and root_name(self.shortcut_folder).lower() == root_name(self.page_folder).lower():
            report(_("Favorites: the shortcut folder needs a different name from the pages folder; shortcuts are left out"))
            self.shortcuts = False
        self.images = bool(settings.get("favorites_images", True))
        self.image_bytes = int(settings.get("favorites_image_kb", 20)) * 1024
        self.page_bytes = int(settings.get("favorites_page_kb", 64)) * 1024
        self.refresh = timedelta(hours=int(settings.get("favorites_refresh_hours", 12)))
        self.report = report
        self.state = self.load_state()

    @property
    def page_root(self):
        return root_name(self.page_folder)

    @property
    def shortcut_root(self):
        return root_name(self.shortcut_folder)

    def load_state(self):
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        state.setdefault("pages", {})
        state.setdefault("device_files", {})
        return state

    def save_state(self):
        write_file_atomically(self.state_path, json.dumps(self.state, indent=1, sort_keys=True).encode("utf-8"))

    def page_name(self, url, title):
        existing = self.state["pages"].get(url, {}).get("name")
        if existing:
            return existing
        taken = {entry.get("name", "").lower() for entry in self.state["pages"].values()} | {INDEX_PAGE}
        stem = file_stem(title or urlsplit(url).netloc or url)
        name = stem + PAGE_EXTENSION
        counter = 2
        while name.lower() in taken:
            name = f"{stem} {counter}{PAGE_EXTENSION}"
            counter += 1
        return name

    def due(self, url, moment):
        entry = self.state["pages"].get(url)
        if not entry or not (self.pages_directory / entry.get("name", "")).exists():
            return True
        try:
            fetched = datetime.fromisoformat(entry["fetched"])
        except (KeyError, ValueError):
            return True
        return moment - fetched >= self.refresh

    def local_target(self, url):
        entry = self.state["pages"].get(url)
        return entry["name"] if entry and entry.get("name") else url

    def refresh_page(self, url):
        try:
            fetched = fetch(url)
        except FetchError as error:
            self.report(_("Favorites: could not fetch {url}: {error}").format(url=url, error=error))
            return False
        if fetched.content_type and "html" not in fetched.content_type and "xml" not in fetched.content_type:
            self.report(_("Favorites: {url} is not a web page ({type})").format(url=url, type=fetched.content_type))
            return False
        previous_images = self.state["pages"].get(url, {}).get("images", [])
        page_stem = None
        image_names = []

        def image_source(image_url):
            if not self.images:
                return None
            try:
                image = fetch(image_url, MOST_IMAGE_DOWNLOAD)
            except FetchError:
                return None
            converted = device_image(image.data, self.image_bytes)
            if converted is None:
                return None
            extension, data = converted
            name = f"{page_stem} {len(image_names) + 1}{extension}"
            write_file_atomically(self.pages_directory / name, data)
            image_names.append(name)
            return name

        text = decode_page(fetched)
        title_only = simplify_html(text, fetched.url)
        name = self.page_name(url, title_only.title)
        page_stem = name[:-len(PAGE_EXTENSION)]
        page = simplify_html(text, fetched.url, self.local_target, image_source)
        body, shortened = shorten(page.body, self.page_bytes)
        note = _("This page was shortened to fit the device.") if shortened else ""
        document = page_document(page.title, body, url, now_text(), note)
        write_file_atomically(self.pages_directory / name, document)
        for stale in set(previous_images) - set(image_names):
            (self.pages_directory / stale).unlink(missing_ok=True)
        self.state["pages"][url] = {"name": name, "title": page.title or url, "images": image_names,
                                    "fetched": datetime.now().isoformat(timespec="seconds")}
        return True

    def remove_page(self, url):
        entry = self.state["pages"].pop(url, {})
        for name in [entry.get("name"), *entry.get("images", [])]:
            if name:
                (self.pages_directory / name).unlink(missing_ok=True)
        if entry.get("shortcut"):
            (self.shortcuts_directory / entry["shortcut"]).unlink(missing_ok=True)

    def relink(self):
        replacements = {f'href="{html.escape(url, quote=True)}"'.encode("ascii", "xmlcharrefreplace"):
                        f'href="{html.escape(entry["name"], quote=True)}"'.encode("ascii", "xmlcharrefreplace")
                        for url, entry in self.state["pages"].items()}
        for entry in self.state["pages"].values():
            path = self.pages_directory / entry["name"]
            if not path.exists():
                continue
            data = path.read_bytes()
            linked = data
            for original, local in replacements.items():
                linked = linked.replace(original, local)
            if linked != data:
                write_file_atomically(path, linked)

    def index_document(self):
        lines = ["<html><head>", f"<title>{html.escape(_('Offline Pages'))}</title>", "</head><body>",
                 f"<h3>{html.escape(_('Offline Pages'))}</h3>", "<ul>"]
        for url in self.urls:
            entry = self.state["pages"].get(url)
            if not entry:
                continue
            fetched = entry.get("fetched", "").replace("T", " ")[:16]
            lines.append(f'<li><a href="{html.escape(entry["name"], quote=True)}">{html.escape(entry.get("title") or url)}</a>'
                         f"<br><small>{html.escape(url)} {html.escape(fetched)}</small></li>")
        lines.extend(["</ul>", "</body></html>"])
        return ("\r\n".join(lines) + "\r\n").encode("ascii", "xmlcharrefreplace")

    def shortcut_document(self, name):
        target = f"file://{self.page_folder}\\{name}"
        return f"[InternetShortcut]\r\nURL={target}\r\n".encode("cp1252", errors="replace")

    def write_shortcuts(self):
        wanted = {}
        if self.shortcuts:
            wanted[file_stem(_("Offline Pages")) + SHORTCUT_EXTENSION] = self.shortcut_document(INDEX_PAGE)
            for url in self.urls:
                entry = self.state["pages"].get(url)
                if entry:
                    shortcut = file_stem(entry.get("title") or url) + SHORTCUT_EXTENSION
                    while shortcut in wanted:
                        shortcut = shortcut[:-len(SHORTCUT_EXTENSION)] + " 2" + SHORTCUT_EXTENSION
                    entry["shortcut"] = shortcut
                    wanted[shortcut] = self.shortcut_document(entry["name"])
        self.shortcuts_directory.mkdir(parents=True, exist_ok=True)
        for path in self.shortcuts_directory.iterdir():
            if path.name not in wanted:
                path.unlink()
        for name, data in wanted.items():
            path = self.shortcuts_directory / name
            if not path.exists() or path.read_bytes() != data:
                write_file_atomically(path, data)

    def update(self):
        moment = datetime.now()
        for url in list(self.state["pages"]):
            if url not in self.urls:
                self.remove_page(url)
        for url in self.urls:
            if self.due(url, moment):
                self.refresh_page(url)
        self.pages_directory.mkdir(parents=True, exist_ok=True)
        self.relink()
        index = self.index_document()
        index_path = self.pages_directory / INDEX_PAGE
        if not index_path.exists() or index_path.read_bytes() != index:
            write_file_atomically(index_path, index)
        self.write_shortcuts()
        self.save_state()

    def generated_files(self):
        files = {}
        if self.pages_directory.is_dir():
            wanted = {INDEX_PAGE}
            for entry in self.state["pages"].values():
                wanted.add(entry.get("name"))
                wanted.update(entry.get("images", []))
            for path in sorted(self.pages_directory.iterdir()):
                if path.name in wanted and path.is_file():
                    files[f"{self.page_root}/{path.name}"] = path
        if self.shortcuts and self.shortcuts_directory.is_dir():
            for path in sorted(self.shortcuts_directory.iterdir()):
                files[f"{self.shortcut_root}/{path.name}"] = path
        return files


class FavoriteStore(Store):
    object_type = FAVORITES

    def __init__(self, pages):
        self.pages = pages
        self.files = {}

    def foreign_path(self, item_id):
        return self.pages.foreign_directory.joinpath(*item_id.split("/"))

    def list_items(self):
        self.pages.update()
        self.files = self.pages.generated_files()
        items = {item_id: content_hash(path.read_bytes()) for item_id, path in self.files.items()}
        for item_id in self.pages.state["device_files"]:
            path = self.foreign_path(item_id)
            if path.exists() and item_id not in items:
                items[item_id] = content_hash(path.read_bytes())
        return items

    def path_for(self, item_id):
        return self.files.get(item_id) or self.foreign_path(item_id)

    def read_item(self, item_id, device_id):
        path = self.path_for(item_id)
        modified = datetime_to_filetime(datetime.fromtimestamp(path.stat().st_mtime, timezone.utc))
        return DeviceFile(device_id or item_id, path.read_bytes(), modified)

    def write_item(self, item_id, device_id, device_object):
        if item_id in self.files:
            return item_id, DEVICE_EDITED_STAMP
        item_id = item_id or device_object.path
        if item_id in self.files:
            return item_id, DEVICE_EDITED_STAMP
        write_file_atomically(self.foreign_path(item_id), device_object.data)
        self.pages.state["device_files"][item_id] = True
        self.pages.save_state()
        return item_id, content_hash(device_object.data)

    def delete_item(self, item_id, device_id):
        if item_id in self.files:
            return
        self.foreign_path(item_id).unlink(missing_ok=True)
        self.pages.state["device_files"].pop(item_id, None)
        self.pages.save_state()

    def find_match(self, device_id, device_object, unmatched_item_ids):
        wanted = device_id.lower()
        return next((item_id for item_id in unmatched_item_ids if item_id.lower() == wanted), None)

    def same_content(self, item_id, device_id, device_object):
        return self.path_for(item_id).read_bytes() == device_object.data

    def describe(self, item_id):
        return item_id

    def describe_device(self, device_id, device_object):
        return device_id


class FavoritesProvider(Provider):
    name = "favorites"
    display_name = N_("Offline pages")
    object_types = (FAVORITES,)
    settings_schema = (
        Setting("favorites_urls", N_("Web pages"), "list", [],
                help=N_("Addresses of the pages to keep on the device, separated by ;.")),
        Setting("favorites_device_folder", N_("Device folder"), "string", DEFAULT_PAGE_FOLDER,
                help=N_("Where the pages and index.htm go on the device. Open index.htm in Pocket Internet Explorer.")),
        Setting("favorites_shortcuts", N_("Add to Favorites"), "bool", False,
                help=N_("Also put a shortcut to each page in Pocket Internet Explorer's Favorites.")),
        Setting("favorites_shortcut_folder", N_("Favorites folder"), "string", DEFAULT_SHORTCUT_FOLDER,
                help=N_("Device folder for the shortcuts; give it a different name from the pages folder.")),
        Setting("favorites_images", N_("Include pictures"), "bool", True,
                help=N_("Keep small GIF, JPEG, PNG and BMP pictures (PNG is converted to BMP); larger ones are left out.")),
        Setting("favorites_image_kb", N_("Largest picture (KB)"), "int", 20, minimum=1),
        Setting("favorites_page_kb", N_("Largest page (KB)"), "int", 64, minimum=4,
                help=N_("Longer pages are shortened.")),
        Setting("favorites_refresh_hours", N_("Refresh every (hours)"), "int", 12, minimum=0,
                help=N_("How old a page may get before it is fetched again. 0: at every synchronization.")),
    )

    def __init__(self, context):
        super().__init__(context)
        self.pages = OfflinePages(context.partnership_directory / CACHE_FOLDER, context.settings, context.message)

    def device_folders(self, object_type):
        folders = [self.pages.page_folder]
        extensions = (PAGE_EXTENSION, *IMAGE_EXTENSIONS)
        if self.pages.shortcuts:
            folders.append(self.pages.shortcut_folder)
            extensions = (*extensions, SHORTCUT_EXTENSION)
        return DeviceFolders(folders, 0, extensions)

    def open_store(self, object_type):
        if object_type.key != FAVORITES.key:
            raise ValueError(f"favorites provider does not handle {object_type.key}")
        return FavoriteStore(self.pages)


PROVIDERS = [FavoritesProvider]
