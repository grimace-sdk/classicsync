# classicsync command-line tool

`classicsync` is installed alongside the app (inside the release archives, or with `uv tool install`, see [README.md](README.md)).

## Connecting

`serve` holds the connection to a device and offers its remote API (RAPI) locally on 127.0.0.1:9990; the other commands use it. The desktop app offers the same address while it runs, so these commands also work alongside the app.

```
classicsync serve /dev/cu.usbserial-10 --baud 19200
classicsync serve COM1
classicsync serve tcp:127.0.0.1:9991        # an emulator's serial port over TCP
classicsync serve usb                       # first attached ActiveSync USB cradle (usb extra)
```

Any device command also takes `--port PORT` to connect directly without `serve`, `--password` for a password-protected device, and `-v` for more detail.

USB cradles for CE 3.0-era devices are a serial stream over bulk endpoints. On Linux the kernel `ipaq` driver exposes them as `/dev/ttyUSB0`. Elsewhere install the `usb` extra (`pyusb`, plus libusb) and use `usb` or `usb:VVVV:PPPP`; on Windows the cradle needs the WinUSB driver (for example via Zadig). The USB path follows the Linux driver but has not been tested on hardware yet.

### Casio BE-300 (PC Connect)

The BE-300 runs Windows CE 3.0 under Casio's own shell and talks Casio PC Connect over USB instead of ActiveSync. Add `--pc-connect`; `usb` then means the BE-300's `usb:07cf:2002`, and a serial cable runs at 115200.

```
classicsync serve usb --pc-connect
classicsync info
classicsync ls "/Nand Disk"
classicsync put notes.txt "/Nand Disk/My Documents/notes.txt"
classicsync install Solitaire.BE-300.cbea   # copied to \Temp\install.cbea, then CoInstall.exe _M
classicsync nand-dump be300.bin --port usb --pc-connect   # the whole 16 MB NAND, about a minute
```

`serve` handshakes as soon as the BE-300 is docked and turned on. If it does not answer, ClassicSync resets the USB port, which makes the BE-300 start a connection by itself; choosing Connect Now on the device also works. Files, folders, the registry, `run`, `time` and `.cbea` installs work; synchronization, `.stg` backup and `db` need ActiveSync's object store calls and do not. On Linux, keep the kernel `ipaq` driver off the BE-300 (it claims `07cf:2002` and asserts only DTR, which makes the device drop the link): ClassicSync detaches it while connected, but a udev rule that unbinds it is more reliable.

## Files, registry and databases

```
classicsync info
classicsync ls "/My Documents"
classicsync put notes.txt
classicsync get "/My Documents/notes.txt"
classicsync rm "/My Documents/old.txt"
classicsync mkdir "/My Documents/Letters"
classicsync run /Windows/pword.exe
classicsync time                            # set the device clock from this computer
classicsync reg list HKCU/ControlPanel/Comm
classicsync reg set HKCU/Software/Example Name string "value"
classicsync db list
classicsync db dump "Contacts Database"
```

## Programs

```
classicsync install App.mips.cab            # also a CeAppMgr .ini, a CE 1.0 .load script, or a Casio .cbea
classicsync apps
classicsync uninstall "Microsoft Mute"
```

## Partnerships and sync

```
classicsync partnership create              # partner the connected device (a device holds two)
classicsync partnership list
classicsync partnership delete Velo --on-device
classicsync sync --dry-run                  # see what would change
classicsync sync                            # files, contacts, calendar, tasks, mail
classicsync sync --first-sync replace       # first sync: replace device items with this computer's
classicsync sync --only contacts --conflict device
classicsync sync --only mail
classicsync sync-status
```

`sync` keeps the desktop copies in the folder described in [README.md](README.md#synchronize) (`$CLASSICSYNC_HOME/data` if that is set). `--folder`, `--provider` and `--conflict` with `--save` are remembered per device.

Only partnered devices synchronize. A partnership is a random 32-bit partner ID kept on this computer (`<settings folder>/partnerships/<name>/partnership.json`) and on the device: `HKLM\Software\Microsoft\Windows CE Services\Partners\P1` or `P2` (`PId`, `PName`) on CE 2.x and later, which the device announces when it connects, and `HKLM\Ident\PartnerId` on CE 1.0. When both sides already hold items of a type that has never been synchronized, `sync` combines them unless `--first-sync replace` or `skip` is given. Items left unresolved (`--conflict skip`) stay listed in `sync-status` until resolved.

Mail is the device Inbox store (Inbox on CE 1.0 and H/PC 2.0). The folder provider keeps it as Maildir folders, `Mail/<folder>/{cur,new,tmp}`, one per device folder, plus `Deleted Items` (CE 1.0) or `Deleted` for messages deleted on the device. Read flags (`S`), moves between folders and deletes go both ways; a message added to `Mail/Outbox` goes to the device Outbox and is sent from the device. Messages carry their text body only: attachments are not copied. Open Inbox on the device once before the first sync, and restart it on the device to see folders added from this computer.

## Sync plugins

Sync plugins add providers: other places to keep the desktop side of a partnership. See [docs/sync-plugins.md](docs/sync-plugins.md) to write one.

```
classicsync plugin list                                  # plugins, their providers, versions and load errors
classicsync plugin install classicsync-csv               # from PyPI
classicsync plugin install git+https://github.com/someone/classicsync-csv
classicsync plugin install ./classicsync-csv             # a project folder
classicsync plugin install classicsync_csv-1.0-py3-none-any.whl
classicsync plugin install csv_contacts.py
classicsync plugin update csv                            # reinstall from the same source, upgrading; no name: all
classicsync plugin remove csv
classicsync plugin use csv --device Velo                 # synchronize Velo with the csv provider
classicsync plugin configure csv                         # show settings for all devices
classicsync plugin configure csv folder=~/Contacts       # change them
classicsync plugin configure folder --device Velo file_depth=2 "file_folders=\My Documents;\Notes"
classicsync plugin configure folder --device Velo file_depth=   # back to the default
classicsync plugin configure folder converted_documents=odt converted_spreadsheets=ods
```

`plugin use --types` picks a provider for some information types only; the rest stay with the partnership's provider. The built-in providers are described in [docs/sync-plugins.md](docs/sync-plugins.md#built-in-providers).

```
classicsync plugin use caldav --device Velo --types contacts,calendar,tasks
classicsync plugin configure caldav --device Velo caldav_url=https://caldav.fastmail.com \
    caldav_contacts_url=https://carddav.fastmail.com caldav_username=me@fastmail.com caldav_password=-
classicsync plugin configure caldav --device Velo caldav_calendar=Work "caldav_task_list=To Do"
classicsync plugin use outlook --device Velo --types contacts,calendar,tasks
classicsync plugin configure outlook --device Velo outlook_contacts_folder=Handheld outlook_future_days=90
classicsync plugin use macos --device Velo --types contacts,calendar,tasks
classicsync plugin configure macos --device Velo macos_contacts_group=Velo macos_calendar=Velo macos_reminders_list=Velo
classicsync plugin use favorites --device Velo --types favorites
classicsync plugin configure favorites --device Velo "favorites_urls=https://example.com/news;https://example.org/"
classicsync plugin use notes --device Velo --types notes
classicsync plugin configure notes --device Velo notes_folder=~/Velo/Notes
```

A password given as `-` is asked for instead. Passwords are saved in the system keyring when the `keyring` package is installed (`classicsync[keyring]`), otherwise in the settings file.

Plugins live in `<settings folder>/plugins/`: `.py` files directly, packages in `lib/<python>-<arch>/`, a `manifest.json` of what was installed and from where, and `settings.json` with the settings for all devices. A device's own settings, kept with its partnership, take precedence. Some settings, like the folder provider's folders, are per device only. List settings are separated by `;`.

Packages are installed with `uv` when it is on the PATH (or in `$UV`), else with `pip` from the Python classicsync runs on. uv's environment variables (`UV_INDEX_URL`, `UV_OFFLINE` and so on) apply. The release apps have no pip: without uv they install `.py` files and pure-Python wheels whose dependencies are already present, and anything else needs uv. Packages classicsync itself already has are not installed again. After updating a plugin that was already loaded, restart the app.

The older `<settings folder>/sync-plugins/` folder is still read.

## Backup

```
classicsync backup Backup.stg               # --incremental, --hpc-explorer for a 1.1-style file
classicsync restore Backup.stg              # then disconnect and reset the device
classicsync backup-info Backup.stg --files
```

## Converting files

No device needed; formats come from the extensions, and anything that does not carry over is listed.

```
classicsync convert Letter.pwd Letter.docx
classicsync convert budget.xlsx budget.pxl                  # Pocket Excel 2.0 (CE 2.x)
classicsync convert notes.rtf notes.pwd --format-version 1  # Pocket Word 1.0 (CE 1.0)
classicsync convert logo.png logo.2bp
```

## Original artwork

ClassicSync does not ship Microsoft artwork. Extract it from your own copies of the original installers (needs the `artwork` extra in a Python install; the release archives include it):

```
classicsync import-artwork hhpcex11.exe WCES22-2.EXE msasync.exe
```

The installers are H/PC Explorer 1.1 (`hhpcex11.exe`), Windows CE Services 2.2 (`WCES22-2.EXE`) and ActiveSync 3.1 (`msasync.exe`); any subset works, and each is identified by its contents rather than its name. Bitmaps, icons, cursors, AVIs and sounds from every module are written to `<settings folder>/artwork/<product>/`. The settings folder is `$CLASSICSYNC_HOME` if set; `--destination` writes somewhere else.

## Translations

ClassicSync does not ship Microsoft text either. It builds translations from an English and a localized copy of the same original installer:

```
classicsync import-translations setup-async-4.5.msi async-4.5/ msasync.exe
```

Give any mix of installers (`.msi` or `.exe`) or directories of them. Each is identified by product and resource language. For every module in both the English and a localized build, string tables, dialog texts, menu items and message tables are paired by resource id. When one English text has several translations the most frequent wins, and the alternatives are listed in the catalog. An English installer with no localized build of its own (ActiveSync 3.1 above) is matched against the others at the same module and id. Catalogs are written to `<settings folder>/locale/<lang>/LC_MESSAGES/` (`de`, `ja`, `zh_CN` for the ActiveSync 4.5 builds) and take precedence over the packaged ones.
