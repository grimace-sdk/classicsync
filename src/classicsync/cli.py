import argparse
import asyncio
import getpass
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import cli_artwork, cli_backup, cli_convert, cli_install, cli_plugins, cli_sync, cli_translations
from .connection.desktop import DESKTOP_IP, DEVICE_IP, Desktop
from .connection.dccm import CONNECTION_PORT
from .connection.network import DEFAULT_LISTEN, NetworkDesktop
from .connection.status_channel import STATUS_PORT
from .gui.settings import Settings
from .i18n import _, ngettext, set_language
from .link.transport import open_transport
from .pcconnect import PcConnectSession, open_pc_connect_transport
from .rapi import cedb
from .rapi.client import (
    REG_BINARY, REG_DWORD, REG_EXPAND_SZ, REG_MULTI_SZ, REG_SZ, ROOT_KEYS, RapiClient, RapiError,
)
from .rapi.structures import FILE_ATTRIBUTE_DIRECTORY, PLATFORM_NAMES, datetime_to_filetime, filetime_to_datetime
from .sync.partners import PartnershipError

DEFAULT_PROXY = "127.0.0.1:9990"
DEFAULT_BAUD = 19200
NAND_SECTORS_PER_READ = 32
NAND_TOTAL_SECTORS = 32768
REGISTRY_TYPE_NAMES = {REG_SZ: "string", REG_EXPAND_SZ: "expand", REG_BINARY: "binary", REG_DWORD: "dword", REG_MULTI_SZ: "multi"}
REGISTRY_TYPES = {name: value for value, name in REGISTRY_TYPE_NAMES.items()}


def device_path(path):
    path = path.replace("/", "\\")
    return path if path.startswith("\\") else "\\" + path


def join_device_path(directory, name):
    return directory.rstrip("\\") + "\\" + name


def hexdump(data, width=16):
    lines = []
    for offset in range(0, len(data), width):
        chunk = data[offset:offset + width]
        hex_part = " ".join(f"{byte:02x}" for byte in chunk)
        text_part = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in chunk)
        lines.append(f"{offset:08x}  {hex_part:<{width * 3}} {text_part}")
    return "\n".join(lines)


NETWORK_PORT = "network"


def make_desktop(arguments):
    async def ask_password(announcement, attempt):
        if arguments.password is not None and attempt == 0:
            return arguments.password
        if not sys.stdin.isatty():
            return None
        return await asyncio.to_thread(getpass.getpass, _("Device password: "))

    if arguments.pc_connect:
        return PcConnectSession(open_pc_connect_transport(arguments.port, arguments.baud))
    if arguments.port == NETWORK_PORT:
        host, _separator, port = getattr(arguments, "network_listen", "").rpartition(":")
        return NetworkDesktop(host or DEFAULT_LISTEN, int(port or CONNECTION_PORT), getattr(arguments, "device_rapi", None),
                              password_provider=ask_password, status_port=getattr(arguments, "status_port", STATUS_PORT))
    transport = open_transport(arguments.port, arguments.baud or DEFAULT_BAUD)
    return Desktop(transport, arguments.desktop_ip, arguments.device_ip, password_provider=ask_password)


def describe_device(announcement):
    if getattr(announcement, "pc_connect", False):
        return announcement.describe()
    if announcement.legacy:
        return _("Windows CE 1.x device at {address}").format(address=announcement.address)
    info = announcement.info
    return _("{name} ({platform}, Windows CE {version} build {build}, {processor})").format(
        name=info.name, platform=info.platform or _("unknown"), version=f"{info.os_major}.{info.os_minor:02d}", build=info.os_build,
        processor=info.processor_name)


@asynccontextmanager
async def rapi_session(arguments):
    if arguments.port:
        desktop = make_desktop(arguments)
        await desktop.start()
        try:
            print(_("waiting for a device on {port}").format(port=desktop.transport.name), file=sys.stderr)
            announcement = await desktop.wait_for_device(arguments.timeout)
            print(_("connected: {device}").format(device=describe_device(announcement)), file=sys.stderr)
            client = await desktop.open_rapi()
            try:
                yield client
            finally:
                client.close()
        finally:
            await desktop.close()
    else:
        host, separator, port = arguments.connect.rpartition(":")
        try:
            client = await RapiClient.open_tcp(host or "127.0.0.1", int(port))
        except OSError as error:
            raise ConnectionError(_("no classicsync server at {address} ({error}); run 'classicsync serve PORT' or pass --port").format(
                address=arguments.connect, error=error.strerror)) from None
        try:
            yield client
        finally:
            client.close()


USB_WAIT_SECONDS = 0.5


async def start_when_attached(desktop, port):
    waiting = False
    while True:
        try:
            await desktop.start()
            return
        except OSError as error:
            if not port.startswith("usb"):
                raise
            if not waiting:
                print(_("waiting for a USB device ({error})").format(error=error), file=sys.stderr)
                waiting = True
            await asyncio.sleep(USB_WAIT_SECONDS)


async def command_serve(arguments):
    desktop = make_desktop(arguments)
    await start_when_attached(desktop, arguments.port)
    host, separator, port = arguments.listen.rpartition(":")
    server = await desktop.serve_rapi_proxy(host or "127.0.0.1", int(port))
    print(_("listening for a device on {port}; RAPI on {address}").format(port=desktop.transport.name, address=arguments.listen),
          file=sys.stderr)
    try:
        while True:
            desktop.device_changed.clear()
            await desktop.device_changed.wait()
            if desktop.device:
                print(_("connected: {device}").format(device=describe_device(desktop.device)), file=sys.stderr)
                info = getattr(desktop.device, "info", None)
                if isinstance(desktop, NetworkDesktop) and info is not None and info.remote_sync:
                    asyncio.create_task(report_failure(cli_sync.remote_sync(desktop)))
                if arguments.sync_time:
                    async with rapi_session(argparse.Namespace(port=None, connect=arguments.listen)) as client:
                        await sync_clock(client)
            else:
                print(_("disconnected"), file=sys.stderr)
    finally:
        server.close()
        await desktop.close()


async def report_failure(coroutine):
    try:
        await coroutine
    except Exception as error:
        print(_("network sync failed: {error}").format(error=error), file=sys.stderr)


async def sync_clock(client):
    now = datetime.now(timezone.utc)
    offset = datetime.now().astimezone().utcoffset()
    bias = -int(offset.total_seconds() // 60) if offset else 0
    await client.sync_time_to_pc(datetime_to_filetime(now), bias & 0xFFFFFFFF)


def transfer_text(source, destination, size):
    return ngettext("{source} -> {destination} ({count} byte)", "{source} -> {destination} ({count} bytes)", size).format(
        source=source, destination=destination, count=size)


def format_size(size):
    for unit in ("", "K", "M", "G"):
        if size < 1024 or unit == "G":
            return f"{size}{unit}" if unit == "" else f"{size:.1f}{unit}"
        size /= 1024


async def command_info(arguments):
    async with rapi_session(arguments) as client:
        version = await client.get_version()
        system = await client.get_system_info()
        print(_("Windows CE {version} build {build} ({platform})").format(
            version=f"{version.major}.{version.minor:02d}", build=version.build, platform=PLATFORM_NAMES.get(version.platform, version.platform)))
        print(_("Processor: {processor}, page size {page_size}").format(processor=system.processor_name, page_size=system.page_size))
        try:
            store = await client.get_store_information()
            print(_("Object store: {free} free of {total}").format(free=format_size(store.free_size), total=format_size(store.store_size)))
        except RapiError as error:
            print(_("Object store: unavailable ({error})").format(error=error))
        try:
            memory = await client.get_memory_status()
            print(_("Program memory: {free} free of {total}").format(free=format_size(memory.available_physical),
                                                                     total=format_size(memory.total_physical)))
        except RapiError:
            pass
        try:
            power = await client.get_power_status()
            source = {0: _("battery"), 1: _("AC")}.get(power.ac_line_status, _("unknown"))
            percent = _("unknown") if power.battery_life_percent == 255 else f"{power.battery_life_percent}%"
            print(_("Power: {source}, main battery {percent}").format(source=source, percent=percent))
        except RapiError:
            pass


async def command_ls(arguments):
    async with rapi_session(arguments) as client:
        path = device_path(arguments.path)
        pattern = path if any(character in path for character in "*?") else join_device_path(path, "*.*")
        entries = await client.find_all_files(pattern)
        for entry in sorted(entries, key=lambda item: (not item.is_directory, item.name.lower())):
            modified = filetime_to_datetime(entry.last_write_time)
            stamp = modified.astimezone().strftime("%Y-%m-%d %H:%M") if modified else " " * 16
            size = "<DIR>" if entry.is_directory else str(entry.size)
            print(f"{stamp}  {size:>10}  {entry.name}{'/' if entry.is_directory else ''}")


async def command_get(arguments):
    async with rapi_session(arguments) as client:
        remote = device_path(arguments.remote)
        local = Path(arguments.local or remote.rsplit("\\", 1)[-1])
        if local.is_dir():
            local = local / remote.rsplit("\\", 1)[-1]
        data = await client.read_file_contents(remote)
        local.write_bytes(data)
        print(transfer_text(remote, local, len(data)), file=sys.stderr)


async def command_put(arguments):
    async with rapi_session(arguments) as client:
        local = Path(arguments.local)
        remote = device_path(arguments.remote or "\\My Documents\\" + local.name)
        try:
            if (await client.get_file_attributes(remote)) & FILE_ATTRIBUTE_DIRECTORY:
                remote = join_device_path(remote, local.name)
        except RapiError:
            pass
        data = local.read_bytes()
        modified = datetime_to_filetime(datetime.fromtimestamp(local.stat().st_mtime, timezone.utc))
        await client.write_file_contents(remote, data, modified=modified)
        print(transfer_text(local, remote, len(data)), file=sys.stderr)


async def command_rm(arguments):
    async with rapi_session(arguments) as client:
        for path in arguments.paths:
            await client.delete_file(device_path(path))


async def command_mkdir(arguments):
    async with rapi_session(arguments) as client:
        await client.create_directory(device_path(arguments.path))


async def command_rmdir(arguments):
    async with rapi_session(arguments) as client:
        await client.remove_directory(device_path(arguments.path))


async def command_mv(arguments):
    async with rapi_session(arguments) as client:
        await client.move_file(device_path(arguments.source), device_path(arguments.destination))


async def command_run(arguments):
    async with rapi_session(arguments) as client:
        info = await client.create_process(device_path(arguments.program), " ".join(arguments.arguments) or None)
        if info:
            print(_("started process {process}").format(process=f"0x{info.process_id:08x}"), file=sys.stderr)


async def command_time(arguments):
    async with rapi_session(arguments) as client:
        await sync_clock(client)


def split_registry_path(path):
    path = path.replace("/", "\\")
    root_name, separator, subkey = path.partition("\\")
    root = ROOT_KEYS.get(root_name.upper())
    if root is None:
        raise ValueError(_("registry path must start with HKLM, HKCU, HKCR or HKU: {path}").format(path=path))
    return root, subkey


def format_registry_value(value_type, value):
    if isinstance(value, bytes):
        return value.hex(" ")
    if isinstance(value, list):
        return " | ".join(value)
    if value_type == REG_DWORD:
        return f"0x{value:08x} ({value})"
    return str(value)


async def open_registry_key(client, path):
    root, subkey = split_registry_path(path)
    if not subkey:
        return root, False
    return await client.reg_open_key(root, subkey), True


async def command_reg(arguments):
    async with rapi_session(arguments) as client:
        key, opened = await open_registry_key(client, arguments.key) if arguments.action != "set" else (None, False)
        try:
            if arguments.action == "list":
                index = 0
                while (name := await client.reg_enum_key(key, index)) is not None:
                    print(f"[{name}]")
                    index += 1
                index = 0
                while (entry := await client.reg_enum_value(key, index)) is not None:
                    name, value_type, value = entry
                    print(f"{name or '(default)'} = {REGISTRY_TYPE_NAMES.get(value_type, value_type)}: {format_registry_value(value_type, value)}")
                    index += 1
            elif arguments.action == "get":
                value_type, value = await client.reg_query_value(key, arguments.name)
                print(f"{REGISTRY_TYPE_NAMES.get(value_type, value_type)}: {format_registry_value(value_type, value)}")
            elif arguments.action == "set":
                root, subkey = split_registry_path(arguments.key)
                key, _ = await client.reg_create_key(root, subkey)
                opened = True
                value_type = REGISTRY_TYPES[arguments.type]
                if value_type == REG_DWORD:
                    value = int(arguments.data, 0)
                elif value_type == REG_BINARY:
                    value = bytes.fromhex(arguments.data)
                elif value_type == REG_MULTI_SZ:
                    value = arguments.data.split("|")
                else:
                    value = arguments.data
                await client.reg_set_value(key, arguments.name, value_type, value)
            elif arguments.action == "delete":
                await client.reg_delete_value(key, arguments.name)
        finally:
            if opened:
                await client.reg_close_key(key)


async def command_db(arguments):
    async with rapi_session(arguments) as client:
        if arguments.action == "list":
            for database in await client.find_all_databases(flags=0x01 | 0x04 | 0x08 | 0x10):
                print(f"0x{database['oid']:08x}  type {database.get('type', 0):>6}  {database.get('record_count', 0):>6} records  {database.get('name', '')}")
            return
        handle, _ = await client.open_database(arguments.name)
        try:
            await client.seek_database(handle, cedb.CEDB_SEEK_BEGINNING)
            count = 0
            while arguments.limit is None or count < arguments.limit:
                record = await client.read_record(handle)
                if record is None:
                    break
                oid, properties = record
                print(f"record 0x{oid:08x}")
                for prop in properties:
                    value = prop.value
                    if prop.value_type == cedb.CEVT_FILETIME:
                        moment = filetime_to_datetime(value)
                        value = moment.isoformat() if moment else value
                    elif isinstance(value, bytes):
                        value = value.hex(" ")
                    print(f"  0x{prop.identifier:04x} type {prop.value_type:>2}: {value}")
                count += 1
        finally:
            await client.close_handle(handle)


async def command_probe(arguments):
    desktop = make_desktop(arguments)
    await desktop.start()
    print(_("waiting for a device on {port}").format(port=desktop.transport.name), file=sys.stderr)
    if arguments.pc_connect:
        try:
            device = await desktop.wait_for_device(arguments.timeout)
            print(_("connected: {device}").format(device=describe_device(device)))
            print(_("platform release: {release}").format(release=device.platform_release or _("unknown")))
        finally:
            await desktop.close()
        return
    await desktop.link.wait_up(timeout=arguments.timeout)
    print(_("link up: desktop {desktop}, device {device}").format(desktop=desktop.link.local_ip, device=desktop.link.peer_ip), file=sys.stderr)
    try:
        announcement = await desktop.wait_for_device(arguments.timeout)
        print(_("connected: {device}").format(device=describe_device(announcement)))
        print(f"key: 0x{announcement.key:08x}")
        if announcement.info:
            print(hexdump(announcement.info.raw))
        print(f"ping: {await desktop.stack.ping() * 1000:.0f} ms")
    finally:
        await desktop.close()


async def command_nand_dump(arguments):
    if not arguments.port or not arguments.pc_connect:
        raise ValueError(_("nand-dump talks to the device directly: give --port and --pc-connect"))
    session = make_desktop(arguments)
    await session.start()
    try:
        print(_("waiting for a device on {port}").format(port=session.transport.name), file=sys.stderr)
        device = await session.wait_for_device(arguments.timeout)
        print(_("connected: {device}").format(device=describe_device(device)), file=sys.stderr)
        wil = session.wil
        handle = await wil.nand_open()
        try:
            geometry = await wil.nand_get_info(handle)
            print(_("NAND window {sectors} sectors of {size} bytes").format(sectors=geometry.sectors, size=geometry.sector_size), file=sys.stderr)
            with open(arguments.output, "wb") as output:
                for sector in range(0, NAND_TOTAL_SECTORS, NAND_SECTORS_PER_READ):
                    count = min(NAND_SECTORS_PER_READ, NAND_TOTAL_SECTORS - sector)
                    output.write(await wil.nand_read_sectors(handle, sector, count))
                    if sys.stderr.isatty():
                        print("\r" + _("reading sector {sector} of {total}").format(sector=sector + count, total=NAND_TOTAL_SECTORS),
                              end="", file=sys.stderr)
            if sys.stderr.isatty():
                print(file=sys.stderr)
        finally:
            await wil.nand_close(handle)
        print(_("saved {path}").format(path=arguments.output), file=sys.stderr)
    finally:
        await session.close()


def add_link_arguments(parser):
    parser.add_argument("--baud", type=int, help=_("serial speed (default 19200, or 115200 with --pc-connect)"))
    parser.add_argument("--pc-connect", action="store_true",
                        help=_("talk Casio PC Connect (BE-300) instead of ActiveSync; PORT 'usb' means usb:07cf:2002"))
    parser.add_argument("--desktop-ip", default=DESKTOP_IP)
    parser.add_argument("--device-ip", default=DEVICE_IP)
    parser.add_argument("--timeout", type=float, default=60, help=_("seconds to wait for a device"))
    parser.add_argument("--password", help=_("device password, if it has one"))


def build_parser():
    parser = argparse.ArgumentParser(prog="classicsync", description=_("Talk to Windows CE 1.x-3.x devices."))
    parser.add_argument("-v", "--verbose", action="count", default=0)
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help=_("hold the connection to a device and offer RAPI to other commands"))
    serve.add_argument("port", help=_("serial device (/dev/ttyUSB0, /dev/cu.usbserial-X, COM1), usb, usb:VVVV:PPPP, tcp:HOST:PORT, "
                                      "or network to wait for devices syncing over the network"))
    serve.add_argument("--network-listen", default=f"{DEFAULT_LISTEN}:{CONNECTION_PORT}",
                       help=_("with network: address and port to accept devices on (default {address})").format(
                           address=f"{DEFAULT_LISTEN}:{CONNECTION_PORT}"))
    serve.add_argument("--status-port", type=int, default=STATUS_PORT,
                       help=_("with network: port the device reports sync status on (default {port}; 0 to turn off)").format(
                           port=STATUS_PORT))
    serve.add_argument("--device-rapi", metavar="HOST:PORT",
                       help=_("with network: reach the device's RAPI here instead of at its own address, for example through an "
                              "SSH tunnel"))
    serve.add_argument("--listen", default=DEFAULT_PROXY, help=_("local RAPI address (default {address})").format(address=DEFAULT_PROXY))
    serve.add_argument("--sync-time", action="store_true", help=_("set the device clock from this computer on connect"))
    add_link_arguments(serve)
    serve.set_defaults(handler=command_serve)

    probe = subparsers.add_parser("probe", help=_("connect once and report what the device sends"))
    probe.add_argument("port")
    add_link_arguments(probe)
    probe.set_defaults(handler=command_probe)

    def device_command(name, handler, help_text):
        subparser = subparsers.add_parser(name, help=help_text)
        target = subparser.add_mutually_exclusive_group()
        target.add_argument("--port", help=_("connect directly on this serial port or tcp:HOST:PORT instead of using 'serve'"))
        target.add_argument("--connect", default=DEFAULT_PROXY, help=_("classicsync serve address (default {address})").format(address=DEFAULT_PROXY))
        add_link_arguments(subparser)
        subparser.set_defaults(handler=handler)
        return subparser

    device_command("info", command_info, _("show device version, memory and power"))
    device_command("ls", command_ls, _("list a device folder")).add_argument("path", nargs="?", default="\\")
    get = device_command("get", command_get, _("copy a file from the device"))
    get.add_argument("remote")
    get.add_argument("local", nargs="?")
    put = device_command("put", command_put, _("copy a file to the device"))
    put.add_argument("local")
    put.add_argument("remote", nargs="?")
    device_command("rm", command_rm, _("delete device files")).add_argument("paths", nargs="+")
    device_command("mkdir", command_mkdir, _("create a device folder")).add_argument("path")
    device_command("rmdir", command_rmdir, _("remove an empty device folder")).add_argument("path")
    move = device_command("mv", command_mv, _("move or rename a device file"))
    move.add_argument("source")
    move.add_argument("destination")
    run = device_command("run", command_run, _("start a program on the device"))
    run.add_argument("program")
    run.add_argument("arguments", nargs="*")
    device_command("time", command_time, _("set the device clock from this computer"))
    nand_dump = device_command("nand-dump", command_nand_dump, _("save the whole NAND flash of a Casio BE-300 (with --port and --pc-connect)"))
    nand_dump.add_argument("output")

    registry = device_command("reg", command_reg, _("read and write the device registry"))
    registry.add_argument("action", choices=["list", "get", "set", "delete"])
    registry.add_argument("key", help=_("e.g. HKCU\\ControlPanel\\Comm"))
    registry.add_argument("name", nargs="?", default="")
    registry.add_argument("type", nargs="?", choices=sorted(REGISTRY_TYPES))
    registry.add_argument("data", nargs="?")

    database = device_command("db", command_db, _("list or dump object store databases"))
    database.add_argument("action", choices=["list", "dump"])
    database.add_argument("name", nargs="?")
    database.add_argument("--limit", type=int)
    cli_artwork.add_commands(subparsers)
    cli_translations.add_commands(subparsers)
    cli_convert.add_commands(subparsers)
    cli_install.add_commands(subparsers, device_command)
    cli_sync.add_commands(subparsers, device_command)
    cli_backup.add_commands(subparsers, device_command)
    cli_plugins.add_commands(subparsers)
    return parser


def main(argv=None):
    set_language(Settings.load().language or None)
    parser = build_parser()
    arguments, leftovers = parser.parse_known_args(argv)
    if leftovers:
        if isinstance(getattr(arguments, "assignments", None), list) and all("=" in item and not item.startswith("-") for item in leftovers):
            arguments.assignments += leftovers
        else:
            parser.error(_("unrecognized arguments: {arguments}").format(arguments=" ".join(leftovers)))
    level = logging.WARNING - 10 * arguments.verbose
    logging.basicConfig(level=max(logging.DEBUG, level), format="%(name)s: %(message)s")
    try:
        asyncio.run(arguments.handler(arguments))
    except (TimeoutError, ConnectionError, RapiError, ValueError, OSError, PartnershipError) as error:
        print(f"classicsync: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
