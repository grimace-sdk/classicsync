# Sync providers

classicsync synchronizes a device with a *provider*: a Python class that keeps the desktop side of one or more object types (files, contacts, calendar, tasks, or your own database). The engine does everything device-side over RAPI, keeps the per-partnership mapping and decides what changed; a provider only reads and writes desktop items.

This mirrors ActiveSync's service providers (`IReplStore`) without the COM: enumeration plus a change stamp replaces `FindFirstItem`/`IsItemChanged`, and `read_item`/`write_item` replace `ObjectToBytes`/`BytesToObject` and the `IReplObjHandler` packets. classicsync does not use the device's replication service (RRA, TCP 5678).

## How a sync works

For each object type the engine:

1. lists the device items (database records by OID, or files under the synchronized folders) and hashes them;
2. calls `store.list_items()` for `{item_id: stamp}` on the desktop;
3. compares both with the mapping saved after the last sync (`<data dir>/partnerships/<partnership>/state.json`) and plans adds, updates, deletes and conflicts in both directions; on the first sync of a type with items on both sides it asks the `first_sync` callback whether to combine them, replace the device's items with the desktop's, or skip the type this time;
4. applies the plan, calling the store for every desktop change.

Each object type has one provider: the partnership's provider (`options.json` `provider`), unless `type_providers` names another for that type, for example `{"contacts": "caldav", "notes": "notes"}` to keep files with the folder provider (`classicsync plugin use caldav --types contacts`). A type that only another provider handles, such as `notes`, is synchronized once it is listed there.

A change beats a delete. Items changed on both sides are conflicts, resolved by the policy for that type: `desktop` (default for contacts, calendar, tasks), `device`, `keep_both` (default for files: the device copy is kept alongside), or `skip` (leave unresolved, like ActiveSync's "Leave the item unresolved"). Unresolved items are kept in `state.json` with a description of both sides; `unresolved_items(partnership)` lists them and `set_resolutions(partnership, items)` records `desktop`, `device` or `skip` per item for the next sync.

## Device objects

- `DeviceRecord(properties, oid)`: a database record. `properties` is a list of `classicsync.rapi.cedb.PropertyValue(identifier, value_type, value)`; types are the `CEVT_*` constants. Read the property tables in `classicsync/sync/pim/properties.py`.
- `DeviceFile(path, data, modified, attributes)`: a file. `path` is the item id (`My Documents/Letters/a.txt`), `modified` a FILETIME.

## The API

```python
from classicsync.sync import Provider, Store, CONTACTS, CALENDAR, TASKS, FILES, ObjectType
from classicsync.sync.settings_schema import Setting
```

`Provider` (one per sync run):

| Member | |
|---|---|
| `name` | unique id used by `--provider` and the partnership options |
| `display_name` | shown in progress messages |
| `object_types` | the `ObjectType`s it handles |
| `settings_schema` | optional: the settings it takes, as `Setting`s (see [Settings](#settings)) |
| `__init__(context)` | `context.device` (`name`, `os_major`, `os_minor`), `context.partnership_directory` (somewhere to keep your own state), `context.settings` (the settings: schema defaults, then the settings for all devices, then the partnership's `provider_settings`, `file_folders` and `file_depth`), `context.message(text)` |
| `open_store(object_type)` | returns a `Store` |
| `device_folders(object_type)` | optional, for your own file types: a `DeviceFolders(folders, depth, extensions)` to synchronize instead of the partnership's file folders |
| `close()` | optional |

`Store` (one per object type):

| Method | |
|---|---|
| `list_items()` | `{item_id: stamp}` for every desktop item. The stamp is any string that changes when the item changes (a content hash, or mtime and size) |
| `read_item(item_id, device_id)` | the item as a `DeviceRecord` or `DeviceFile`. `device_id` is the mapped device item (`None` if new) so you can merge with properties you do not understand |
| `write_item(item_id, device_id, device_object)` | create (`item_id is None`) or replace a desktop item; return `(item_id, stamp)` |
| `delete_item(item_id, device_id)` | delete a desktop item |
| `find_match(device_id, device_object, unmatched_item_ids)` | optional: pair items on the first sync (files match by path) |
| `same_content(item_id, device_id, device_object)` | optional: matched items are equal, no conflict |
| `device_updated(item_id, device_id, device_object)` | optional: called with the device's copy after the engine wrote it; may return a new stamp |
| `describe(item_id)` | optional: text for progress and reports |
| `describe_device(device_id, device_object)` | optional: text for a device item that has no desktop copy |
| `describe_conflict(item_id, device_id, device_object)` | optional: `(desktop_lines, device_lines)` shown when resolving a conflict |

Ids and stamps must be strings. Item ids must be stable between runs. Raise `ProviderError` from `open_store` or `list_items` (a server that can't be reached, a refused password) to skip that type with a message, or from a write to fail just that item.

Your own database type: `ObjectType("expenses", "Expense", "Expenses", database="Expense Log")`. The engine handles any CE database by name.

## Settings

A provider lists its settings in `settings_schema`, so `classicsync plugin configure` and the app's Settings... dialog can show and check them:

```python
settings_schema = (
    Setting("folder", "Contacts folder", "path", help="Where contacts.csv is kept."),
    Setting("quote_all", "Quote every field", "bool", False),
    Setting("limit", "Most contacts", "int", 500, minimum=1),
    Setting("encoding", "Encoding", "choice", "utf-8", choices=[("utf-8", "Unicode (UTF-8)"), ("cp1252", "Western (Windows)")]),
)
```

`Setting(key, label, type, default, choices, help, minimum, maximum, per_device)`:

| Field | |
|---|---|
| `key` | the name in `context.settings` and on the command line |
| `label`, `help` | shown in the dialog and by `plugin configure` |
| `type` | `string`, `path` (a folder; the dialog has Browse...), `bool`, `int` (`minimum`, `maximum`), `choice` (`choices`: values, or `(value, label)` pairs) or `list` (of strings) |
| `default` | used when nothing is set; `None` leaves the key out of `context.settings` |
| `per_device` | only set per partnership, never for all devices (for example a folder named after the device) |
| `secret` | a password: `plugin configure` saves it in the system keyring when the `keyring` package is installed (`classicsync[keyring]`), otherwise in the settings file; `context.settings` holds the value itself |

Plain dicts with the same fields work too, so a plugin need not import `Setting`. Settings are stored as JSON: for all devices in `<data dir>/plugins/settings.json` under the provider's name, per partnership in its `options.json` `provider_settings`, which is shared by all providers, so prefix keys that another provider might also use. A provider without a schema still gets any `key=value` given to `plugin configure`, as strings.

The folder provider's settings: `folder` (per device), `convert_documents`, `converted_documents` (`rtf`, `docx`, `odt`, `html`, `txt`; default RTF on macOS, Word elsewhere), `converted_spreadsheets` (`xlsx`, `ods`, `csv`; default CSV on macOS unless Numbers or Excel is installed, else Excel), `converted_images` (`png`, `bmp`), `file_folders` and `file_depth` (per device). Changing a format regenerates the `Converted/` copies; edited copies in any of these formats are converted back.

## Installing a provider

```
classicsync plugin install SPEC      # PyPI name, git+https:// URL, project folder, .whl or .py
classicsync plugin use NAME --device DEVICE
```

See [CLI.md](../CLI.md#sync-plugins) for the rest. A provider is found as:

- a built-in (`folder` and the providers in [Built-in providers](#built-in-providers));
- an entry point in the `classicsync.sync_providers` group, pointing at the class or a module (every `Provider` subclass with a `name` in it, or the classes listed in `PROVIDERS`), in a package installed into classicsync's own environment or installed with `plugin install` into `<data dir>/plugins/lib/<python>-<arch>/`:

  ```toml
  [project.entry-points."classicsync.sync_providers"]
  csv = "classicsync_csv:CsvProvider"
  ```

- a `.py` file in `<data dir>/plugins/` (what `plugin install file.py` does) or the older `<data dir>/sync-plugins/`: every `Provider` subclass with a `name`, or the classes listed in `PROVIDERS`. Set `__version__` to have it shown.

`<data dir>` is the settings folder, `$CLASSICSYNC_HOME` if set. A later provider with the same name replaces an earlier one, in the order above.

`plugin install` uses uv or pip with `--target` into the library folder, which classicsync adds to `sys.path` (after its own packages) when it looks for providers. Dependencies classicsync already has at the same version are removed from the library again, and so is classicsync itself, so a plugin may depend on `classicsync`: the installer is offered the running version even where classicsync is not on PyPI. The release apps have no pip, so without uv only `.py` files and pure-Python (`py3-none-any`) wheels whose dependencies are already present can be installed. Keep plugins pure Python where you can.

## Built-in providers

They ship with classicsync, in `classicsync/sync/providers/`. Those that need another package or system load only where it is available; `classicsync plugin list` shows why one is missing. Use one for some types only with `plugin use NAME --device DEVICE --types TYPES`.

### CalDAV and CardDAV (`caldav`)

Contacts with a CardDAV address book, appointments (`VEVENT`) and tasks (`VTODO`) with CalDAV calendars: iCloud, Fastmail, Nextcloud, Radicale and other servers that accept a user name and password. It finds the address books and calendars from the server address, notices changes by ETag (with `sync-collection` where the server offers it), and never overwrites a copy changed on the server since it was read. Server-only details (photos, attendees, repeat rules, extra fields) are kept when the device changes an item, and device properties the server doesn't hold are kept on the device. Repeating appointments reach the device as their first occurrence. Google needs OAuth, which isn't supported.

Settings: `caldav_url`, `caldav_contacts_url` (if address books are on another server), `caldav_username`, `caldav_password` (secret; use an app password), `caldav_address_book`, `caldav_calendar`, `caldav_task_list` (names or addresses; empty: the first suitable one), `caldav_past_days` (0: all appointments), `caldav_vcard_version` (`3.0` or `4.0`, for new contacts).

### Outlook (`outlook`, Windows)

Contacts, calendar and tasks with Microsoft Outlook through COM; needs `classicsync[windows]` (pywin32). Only fields the device changed are written to Outlook, so Outlook-only fields are kept. Repeating appointments reach the device as their first occurrence.

Settings: `outlook_contacts_folder`, `outlook_calendar_folder`, `outlook_tasks_folder` (empty: the default folders; `Sub` for a subfolder, `Store\Folder` for another store), `outlook_past_days` (30), `outlook_future_days` (365).

### macOS Contacts, Calendar and Reminders (`macos`)

Contacts with Contacts, appointments with Calendar and tasks with Reminders; needs `classicsync[macos]` (PyObjC). The first sync of each asks for permission; if it was refused, allow ClassicSync (or your terminal) in System Settings, Privacy & Security.

Settings: `macos_contacts_group` (empty: all contacts; new contacts join the group, which is created if missing), `macos_calendar` and `macos_reminders_list` (empty: the defaults), `macos_past_days` (30), `macos_future_days` (365).

### Offline pages (`favorites`)

Fetches a list of web pages, simplifies them for Pocket Internet Explorer and copies them to the device with an `index.htm`, optionally adding Favorites shortcuts. Desktop to device only: changes made on the device are replaced at the next sync.

Settings: `favorites_urls`, `favorites_device_folder` (`\My Documents\Offline Pages`), `favorites_shortcuts`, `favorites_shortcut_folder` (`\Windows\Favorites\Mobile Favorites`), `favorites_images`, `favorites_image_kb`, `favorites_page_kb`, `favorites_refresh_hours` (12; 0: every sync).

### Notes as Markdown (`notes`)

Keeps device notes as Markdown files. Pocket Word (`.pwd`) notes go both ways and new Markdown files become Pocket Word notes. InkWriter and Notes (`.pwi`) files are shown as text but never changed on the device, so their ink is kept; edits to them are saved as a new note. If the folder provider also synchronizes the same device folder, notes appear in both.

Settings: `notes_folder` (per device), `notes_device_folders` (`\My Documents`), `notes_depth`, `notes_word_documents`.

## Example: contacts to a CSV file

`csv_contacts.py`, installed with `classicsync plugin install csv_contacts.py`:

```python
import csv
import hashlib
from pathlib import Path

from classicsync.rapi.cedb import CEVT_LPWSTR, PropertyValue
from classicsync.sync import CONTACTS, DeviceRecord, Provider, Store
from classicsync.sync.settings_schema import Setting

__version__ = "1.0"

FIELDS = {"given": 0x3A06, "surname": 0x3A11, "email": 0x4083, "mobile": 0x3A1C}


class CsvContacts(Store):
    object_type = CONTACTS

    def __init__(self, path):
        self.path = path

    def load(self):
        if not self.path.exists():
            return {}
        with self.path.open(newline="") as file:
            return {row["id"]: row for row in csv.DictReader(file)}

    def save(self, rows):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", newline="") as file:
            writer = csv.DictWriter(file, ["id", *FIELDS])
            writer.writeheader()
            writer.writerows(rows.values())

    def stamp(self, row):
        return hashlib.sha1(repr(sorted(row.items())).encode()).hexdigest()

    def list_items(self):
        return {item_id: self.stamp(row) for item_id, row in self.load().items()}

    def read_item(self, item_id, device_id):
        row = self.load()[item_id]
        return DeviceRecord([PropertyValue(FIELDS[name], CEVT_LPWSTR, row[name]) for name in FIELDS if row[name]])

    def write_item(self, item_id, device_id, device_object):
        rows = self.load()
        values = {prop.identifier: prop.value for prop in device_object.properties}
        item_id = item_id or device_id or str(len(rows) + 1)
        rows[item_id] = {"id": item_id, **{name: values.get(identifier, "") for name, identifier in FIELDS.items()}}
        self.save(rows)
        return item_id, self.stamp(rows[item_id])

    def delete_item(self, item_id, device_id):
        rows = self.load()
        rows.pop(item_id, None)
        self.save(rows)


class CsvProvider(Provider):
    name = "csv"
    display_name = "CSV contacts"
    object_types = (CONTACTS,)
    settings_schema = (
        Setting("csv_folder", "Contacts folder", "path", str(Path.home()), help="contacts.csv is kept in this folder."),
    )

    def open_store(self, object_type):
        return CsvContacts(Path(self.context.settings["csv_folder"]).expanduser() / "contacts.csv")
```

Then:

```
classicsync plugin use csv --device Velo
classicsync plugin configure csv --device Velo csv_folder=~/Velo
```

This one is lossy: properties not in the CSV are removed from the device record when the desktop row changes, because the engine makes the device record match `read_item`. To keep them, store the record you were given in `write_item`/`device_updated` and merge in `read_item`, as the folder provider does with its `raw/` files.

## Palm conduits

A Palm handheld syncs through conduits, as with HotSync: each conduit handles the databases of one handheld application, picked by creator ID or database name. Address Book, Date Book, To Do List and Memo Pad are built-in conduits that hand their records to the sync providers above (contacts, calendar, tasks and notes); Backup runs last and copies databases to `.pdb`/`.prc` files.

A conduit is one of two kinds, from `classicsync.palm.conduit`:

- `RecordConduit`: one database, synchronized record by record through the sync engine and a provider. Set `name`, `display_name`, `creators`, `database`, `object_type`, and implement `parse(data)` and `build(record)` (the handheld record bytes), `to_desktop(record, category, secret)` (returns the device object a provider expects: a `DeviceRecord` of properties, or a `DeviceFile`) and `from_desktop(device_object, base)` (returns the record, its category name, and `True`/`False`/`None` for private, `None` keeping what the handheld had).
- `FreeformConduit`: implement `async run(context)`. `context` has `client` (the desktop link client: open, read and write databases), `user`, `partnership`, `folder` (the partnership's folder), `log(text)` and `dry_run`.

`priority` (0 first to 4 last, default 2) sets the order. Conduits are found like providers: in a `.py` plugin file (every `Conduit` subclass with a `name`, or the classes listed in `CONDUITS`) or through the `classicsync.palm_conduits` entry point group:

```toml
[project.entry-points."classicsync.palm_conduits"]
giraffe = "classicsync_giraffe:GiraffeScores"
```

A later conduit with the same name replaces an earlier one, so a plugin can replace a built-in.

## From the GUI

```python
from classicsync.sync import synchronize, Partnership, SyncOptions

report = await synchronize(client, partnership=None, options=None, progress=callback, first_sync=None)
```

`partnership` defaults to the device's partnership (`find_partnership(client)`, matched by the partner IDs on the device); a guest raises `NoPartnership`. `first_sync(FirstSync(object_type, device_count, desktop_count))` may be a function or coroutine returning `"combine"`, `"replace"` or `"skip"`; without it the engine combines. `options` defaults to the partnership's saved `options.json`. `progress` receives `SyncProgress(phase, object_type, done, total, message)` with phases `start`, `scan`, `apply`, `message`, `done`. The returned `SyncReport` has `actions`, `errors`, `unresolved`, `counts()` and `summary()`.

`classicsync.gui.common.plugin_settings` has the dialogs: `choose_sync_provider(parent, partnership=None)` lists the providers, installs and removes plugins and, given a partnership, saves the chosen provider for it (returns its name, or `None` if cancelled); `show_provider_settings(parent, provider_class, partnership=None)` edits one provider's settings for a partnership or, without one, for all devices; `show_partnership_settings(parent, partnership)` edits the settings of the partnership's current provider.
