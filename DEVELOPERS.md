# Developing ClassicSync

## Setup

```
uv venv .venv
uv pip install --python .venv -e ".[gui,usb,artwork,dev]"
.venv/bin/classicsync-gui
```

## Tests and lint

```
.venv/bin/ruff check src tests tools
.venv/bin/python -m pytest -m "not device"     # fast suite, no emulator
VELO_EMU=../velo-emu .venv/bin/python -m pytest   # adds CE 1.0 and CE 2.0 emulator sessions
```

Tests that need the original installers look in `$CLASSICSYNC_INSTALLERS` (default `../classicsync-installers`) and skip when they are absent. Pocket Word 1.0 `.pwi` sample tests read `$CLASSICSYNC_PWI_SAMPLES`. Emulator tests (marked `device`) need a [velo-emu](https://github.com/Gadgetoid/velo-emu) build in `$VELO_EMU`. CalDAV tests use an in-process fake server; to also run them against Radicale, point `$CLASSICSYNC_RADICALE_PYTHON` at a Python with `radicale` installed (`uv venv radicale-env && uv pip install --python radicale-env radicale`).

## Layout

- `src/classicsync/link`: transports (serial, TCP serial, USB), HDLC framing, PPP (direct cable handshake, LCP, IPCP).
- `src/classicsync/net`: userspace IPv4, TCP, UDP and ICMP over the PPP link. No root, no pppd.
- `src/classicsync/connection`: connection manager (TCP 5679), the `Desktop` session, port scanning for Get Connected.
- `src/classicsync/rapi`: RAPI client (TCP 990), commands 0x00-0x55.
- `src/classicsync/link/pcconnect.py`, `src/classicsync/pcconnect`: Casio PC Connect for the BE-300: the `0x55` handshake and big-endian frame link, the `Wil*` command client, a bridge that answers RAPI requests with `Wil*` calls (so `RapiClient`, `serve` and the CLI work unchanged), and the session. Tests run against `tests/fake_pcconnect.py`.
- `src/classicsync/install`: CE 2.x/3.x CABs and CeAppMgr INIs via wceload, CE 1.0 `.load` scripts, Casio `.cbea` packages via CoInstall.
- `src/classicsync/sync`: two-way sync engine over RAPI, partnerships, the provider plugin API, plugin installer (`plugin_install.py`), provider settings schema and the default `folder` provider. `sync/providers/` holds the other built-in providers (CalDAV/CardDAV, Outlook, macOS, offline pages, notes). See [docs/sync-plugins.md](docs/sync-plugins.md).
- `src/classicsync/convert`: Pocket Word, Pocket Excel and 2bp converters.
- `src/classicsync/backup`: `.stg` backup and restore.
- `src/classicsync/formats`: cabinet (MSZIP, LZX), InstallShield 3, MSI, compound file and Windows resource readers.
- `src/classicsync/gui`: the wxPython app. `common/` holds shared pieces (dialog-unit layout, artwork, device browser, sync runner); `frontends/` holds one package per recreated product.
- `src/classicsync/locale`: packaged translation catalogs.
- `tools/i18n`: extract, merge and compile translation catalogs.
- `tools/gui_capture`: drive the GUI against velo-emu and save window captures.
- `packaging`: PyInstaller build of the release archives.

## Translations

Mark user-visible strings with `_()`, `ngettext()` or `pgettext()` from `classicsync.i18n`. Strings that come from the original software use the original English text as msgid, accelerators and placeholders included, so catalogs imported from the original installers apply. Format original placeholders (`FormatMessage` inserts such as `%1!d!`, or printf conversions) with `format_original` rather than `str.format`:

```python
from classicsync.i18n import _, format_original

format_original(_("%1!d! items not synchronized"), count)
```

Strings ClassicSync adds itself use whole sentences with `{name}` placeholders, formatted after translation.

```
.venv/bin/python tools/i18n/update_catalogs.py de fr     # re-extract and merge into locale/<lang>/LC_MESSAGES/classicsync.po
.venv/bin/python tools/i18n/compile_catalogs.py
```

## Window captures

`tools/gui_capture/run_with_emulator.sh ROM STATE OUTPUT_DIR DRIVER [ARTWORK_PRODUCT ARTWORK_DIR]` starts velo-emu with its serial port on TCP, runs a driver script against it, and stops the emulator afterwards. The drivers save window captures with `wx.WindowDC(window).GetAsBitmap()`.

The README screenshots come from `drive_screenshots.py` on macOS, which renders whole windows including the title bar in light appearance. Run it once per frontend:

```
CLASSICSYNC_FRONTEND=hpcexplorer11 tools/gui_capture/run_with_emulator.sh rom/nk.bin CE1_STATE OUT tools/gui_capture/drive_screenshots.py
CLASSICSYNC_FRONTEND=ceservices22 tools/gui_capture/run_with_emulator.sh rom/nk-ce2-merged-patchsets-115k.bin CE2_STATE OUT tools/gui_capture/drive_screenshots.py
CLASSICSYNC_FRONTEND=activesync31 tools/gui_capture/run_with_emulator.sh rom/nk-ce2-merged-patchsets-115k.bin CE2_STATE OUT tools/gui_capture/drive_screenshots.py
```

then copy the PNGs from `OUT` to `docs/screenshots/`.

## Release archives

```
.venv/bin/python packaging/build_app.py
```

builds `dist/ClassicSync-<version>-<platform>.zip` (`.tar.gz` on Linux) with the app and the command-line tool. CI builds these for Linux, macOS and Windows on every push; pushing a tag `v<version>` matching `pyproject.toml` publishes a GitHub release with the archives and the wheel.
