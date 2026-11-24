import asyncio
import os
from pathlib import Path

import pytest

from cab_builders import build_cab, build_ce_cab, build_ce_setup
from classicsync.formats.cab import CabArchive, CabError
from classicsync.install import (
    DesktopAppRecords, DeviceProfile, InstallError, LoadScriptInstaller, compatibility_problem, install_cab, list_installed_apps,
    parse_appmgr_ini, parse_load_script, parse_setup, parse_unload_script, read_cab_package, select_package, tokenize_load_line,
)
from classicsync.rapi.client import HKEY_CLASSES_ROOT, HKEY_LOCAL_MACHINE, REG_DWORD, REG_MULTI_SZ, REG_SZ, RapiError
from classicsync.rapi.structures import FILE_ATTRIBUTE_DIRECTORY, ProcessInformation

TEST_LOAD = r'''// exercises every command velo-rapi load supports
copy . . "tool.exe"
copy . "\Windows\Load Test" "Read Me.txt"
mkdir "\Windows\Load Test\Empty"
createShortcut "\Windows\Load Test" "Tool.lnk" . "tool.exe"
createShortcut "\Windows\Load Test" "Volume.lnk" "\Windows" "ctlpnl.exe\" \Windows\sounds.cpl,Volume & Sounds,0"
createShortcut "\Windows\Load Test" "Root.lnk" \ "\"\""
regString      HKEY_LOCAL_MACHINE Software\LoadTest 1 Name "Load Test"
regStringMulti HKEY_LOCAL_MACHINE Software\LoadTest 1 List "one\0two\0three"
regKeyCreate   HKEY_CLASSES_ROOT .loadtest 1
regString      HKEY_CLASSES_ROOT .loadtest 1 Default "loadtestfile"
regString      ~ ~ 1 Tool "%P\tool.exe"
regInt         ~ ~ 0 Count 42
execOnUnload   \Windows\never.exe
remoteExec "\Windows\calc.exe"
exit
copy . . "never.exe"
'''

INSTALL_INF = "[Installer]\r\nAppName=Load Test\r\nInstallDir=\\Program Files\\Load Test\r\n"

APPMGR_INI = """; Note:\r
; Do not edit CEAppManager Version!\r
\r
[CEAppManager]\r
Version = 1.0\r
Component = HandMap\r
\r
[HandMap]\r
Description = HandMap Deluxe\r
CabFiles = HandMap.MIPS.cab,HandMap.SH3.cab\r
Uninstall = Widgets HandMap\r
"""


class FakeDevice:
    def __init__(self):
        self.files = {}
        self.directories = {"\\", "\\windows"}
        self.registry = {}
        self.key_names = {}
        self.processes = []
        self.shortcuts = {}
        self.handles = {}

    def _key(self, root, subkey):
        return (root, subkey.lower())

    async def get_file_attributes(self, path):
        if path.lower() in self.directories:
            return FILE_ATTRIBUTE_DIRECTORY
        if path.lower() in self.files:
            return 0x80
        raise RapiError("CeGetFileAttributes", 2)

    async def create_directory(self, path):
        self.directories.add(path.lower())

    async def write_file_contents(self, path, data, modified=None, progress=None):
        self.files[path.lower()] = (path, bytes(data))
        if progress:
            progress(len(data))

    async def delete_file(self, path):
        self.files.pop(path.lower(), None)

    async def create_process(self, application, arguments=None):
        self.processes.append((application, arguments))
        return ProcessInformation(1, 2, 3, 4)

    async def create_shortcut(self, shortcut, target):
        self.shortcuts[shortcut] = target

    async def reg_create_key(self, root, subkey, class_name=""):
        key = self._key(root, subkey)
        parts = subkey.split("\\")
        for depth in range(1, len(parts) + 1):
            self.registry.setdefault(self._key(root, "\\".join(parts[:depth])), {})
            self.key_names[self._key(root, "\\".join(parts[:depth]))] = parts[depth - 1]
        handle = len(self.handles) + 1
        self.handles[handle] = key
        return handle, 1

    async def reg_open_key(self, root, subkey):
        key = self._key(root, subkey)
        if key not in self.registry:
            raise RapiError("CeRegOpenKeyEx", 2)
        handle = len(self.handles) + 1
        self.handles[handle] = key
        return handle

    async def reg_close_key(self, handle):
        self.handles.pop(handle)

    async def reg_set_value(self, handle, name, value_type, value):
        self.registry[self.handles[handle]][name] = (value_type, value)

    async def reg_query_value(self, handle, name):
        try:
            return self.registry[self.handles[handle]][name]
        except KeyError:
            raise RapiError("CeRegQueryValueEx", 2) from None

    async def reg_delete_value(self, handle, name):
        self.registry[self.handles[handle]].pop(name, None)

    async def reg_enum_key(self, handle, index):
        root, parent = self.handles[handle]
        depth = parent.count("\\") + 1
        children = sorted(self.key_names[(key_root, subkey)] for key_root, subkey in self.registry
                          if key_root == root and subkey.startswith(parent + "\\") and subkey.count("\\") == depth)
        return children[index] if index < len(children) else None

    def value(self, root, subkey, name):
        return self.registry[self._key(root, subkey)][name]

    def file(self, path):
        return self.files[path.lower()][1]


def run(coroutine):
    return asyncio.run(coroutine)


def test_cab_uncompressed_and_mszip_round_trip():
    members = [("small.txt", b"hello"), ("random.bin", os.urandom(70000)), ("text.txt", b"classicsync " * 9000)]
    for compression in (0, 1):
        archive = CabArchive(build_cab(members, compression))
        assert archive.names() == [name for name, _ in members]
        for name, data in members:
            assert archive.read(name) == data
        assert archive.read("SMALL.TXT") == b"hello"
        assert archive.files[0].size == 5
        assert archive.files[0].modified.year == 2002
        assert archive.folders[0].compression_name == ("MSZIP" if compression else "none")


def test_cab_rejects_garbage():
    with pytest.raises(CabError):
        CabArchive(b"not a cabinet" * 4)


def test_cab_extract_all(tmp_path):
    archive = CabArchive(build_cab([("folder\\inner.txt", b"inside")]))
    written = archive.extract_all(tmp_path)
    assert written == [tmp_path / "folder" / "inner.txt"]
    assert written[0].read_bytes() == b"inside"


def test_ce_setup_header():
    setup = parse_setup(build_ce_setup("Mute", "Microsoft", 4000, [("mute.exe", ["%CE1%", "Plus!"]), ("MUTERT.DLL", ["%CE2%"])],
                                       maximum_version=(2, 0), unsupported="Palm PC"))
    assert setup.app_name == "Mute"
    assert setup.provider == "Microsoft"
    assert setup.uninstall_name == "Microsoft Mute"
    assert setup.processor_type == 4000
    assert setup.minimum_version == (2, 0)
    assert setup.maximum_version == (2, 0)
    assert setup.unsupported == ["Palm PC"]
    assert setup.file_paths() == {"mute.exe": "%CE1%\\Plus!", "MUTERT.DLL": "%CE2%"}


def test_cab_package_and_compatibility():
    package = read_cab_package(build_ce_cab("Mute", "Microsoft", 4000, [("mute.exe", ["%CE1%"], b"x" * 100)], maximum_version=(2, 0)),
                               "mute.mips.cab")
    assert package.setup_member == "Mute.000"
    assert package.installed_size == 100
    assert compatibility_problem(package, DeviceProfile(2, 0, 0, 4000)) is None
    assert compatibility_problem(package, DeviceProfile(2, 0, 0, 3912)) is None
    assert "Hitachi SH3" in compatibility_problem(package, DeviceProfile(2, 0, 0, 10003))
    assert "up to 2.00" in compatibility_problem(package, DeviceProfile(2, 11, 0, 4000))
    assert "2.00 or later" in compatibility_problem(package, DeviceProfile(1, 0, 0, 4000))


def test_cab_without_setup_is_refused():
    with pytest.raises(InstallError):
        read_cab_package(build_cab([("readme.txt", b"hi")]), "plain.cab")


def test_select_package_prefers_matching_processor():
    any_cpu = read_cab_package(build_ce_cab("App", "Vendor", 0, [("a.txt", ["%CE1%"], b"a")]), "any.cab")
    sh3 = read_cab_package(build_ce_cab("App", "Vendor", 10003, [("a.txt", ["%CE1%"], b"a")]), "sh3.cab")
    mips = read_cab_package(build_ce_cab("App", "Vendor", 4000, [("a.txt", ["%CE1%"], b"a")]), "mips.cab")
    assert select_package([any_cpu, sh3, mips], DeviceProfile(2, 0, 0, 4000)) is mips
    assert select_package([sh3, any_cpu], DeviceProfile(2, 0, 0, 4000)) is any_cpu
    assert select_package([sh3], DeviceProfile(2, 0, 0, 4000)) is None


def test_appmgr_ini():
    components = parse_appmgr_ini(APPMGR_INI, Path("/apps/HandMap.ini"))
    assert len(components) == 1
    component = components[0]
    assert component.name == "HandMap"
    assert component.description == "HandMap Deluxe"
    assert component.cab_files == ["HandMap.MIPS.cab", "HandMap.SH3.cab"]
    assert component.uninstall == "Widgets HandMap"
    assert component.cab_paths()[0] == Path("/apps/HandMap.MIPS.cab")


@pytest.mark.parametrize("text, message", [
    ("[Other]\nVersion=1.0\n", "header"),
    ("[CEAppManager]\nVersion=2.0\nComponent=A\n[A]\nCabFiles=a.cab\n", "unsupported version"),
    ("[CEAppManager]\nVersion=1.0\nComponent=Missing\n", "application component"),
    ("[CEAppManager]\nVersion=1.0\nComponent=A\n[A]\nDescription=x\n", "no CAB files"),
])
def test_appmgr_ini_errors(text, message):
    with pytest.raises(InstallError, match=message):
        parse_appmgr_ini(text)


def test_load_tokenizer():
    assert tokenize_load_line('createShortcut "\\Windows\\Load Test" "Volume.lnk" "\\Windows" "ctlpnl.exe\\" x,0"') == [
        "createShortcut", "\\Windows\\Load Test", "Volume.lnk", "\\Windows", 'ctlpnl.exe" x,0']
    assert tokenize_load_line('regStringMulti HKEY_LOCAL_MACHINE Software\\LoadTest 1 List "one\\0two"')[-1] == "one\0two"
    assert tokenize_load_line('createShortcut "\\W" "Root.lnk" \\ "\\"\\""')[-1] == '""'
    assert tokenize_load_line("   // comment") == []


def test_load_script_parsing():
    commands = parse_load_script(TEST_LOAD)
    assert [command.key for command in commands][:3] == ["copy", "copy", "mkdir"]
    assert commands[0].arguments == [".", ".", "tool.exe"]
    assert commands[0].line_number == 2
    assert commands[-2].key == "exit"


def write_load_package(directory):
    (directory / "Test.load").write_text(TEST_LOAD)
    (directory / "Install.inf").write_text(INSTALL_INF)
    (directory / "tool.exe.mips").write_bytes(b"mips build\n")
    (directory / "tool.exe.sh3").write_bytes(b"sh3 build\n")
    (directory / "Read Me.txt").write_bytes(b"plain file\n")
    return directory / "Test.load"


def test_load_script_installer(tmp_path):
    script = write_load_package(tmp_path)
    device = FakeDevice()
    result = run(LoadScriptInstaller(device, script, "\\Windows\\LoadTest", 4000).run())
    assert result.errors == []
    assert result.app_name == "Load Test"
    assert device.file("\\Windows\\LoadTest\\tool.exe") == b"mips build\n"
    assert device.file("\\Windows\\Load Test\\Read Me.txt") == b"plain file\n"
    assert device.file("\\Windows\\Load Test\\Tool.lnk") == b"26#\\Windows\\LoadTest\\tool.exe"
    assert device.file("\\Windows\\Load Test\\Volume.lnk") == b'59#"\\Windows\\ctlpnl.exe" \\Windows\\sounds.cpl,Volume & Sounds,0'
    assert device.file("\\Windows\\Load Test\\Root.lnk") == b"1#\\"
    assert "\\windows\\load test\\empty" in device.directories
    assert device.value(HKEY_LOCAL_MACHINE, "Software\\LoadTest", "Name") == (REG_SZ, "Load Test")
    assert device.value(HKEY_LOCAL_MACHINE, "Software\\LoadTest", "List") == (REG_MULTI_SZ, ["one", "two", "three"])
    assert device.value(HKEY_CLASSES_ROOT, ".loadtest", "") == (REG_SZ, "loadtestfile")
    home = "SOFTWARE\\Apps\\Load Test"
    assert device.value(HKEY_LOCAL_MACHINE, home, "Tool") == (REG_SZ, "\\Windows\\LoadTest\\tool.exe")
    assert device.value(HKEY_LOCAL_MACHINE, home, "Count") == (REG_DWORD, 42)
    assert device.value(HKEY_LOCAL_MACHINE, home, "Instl") == (REG_DWORD, 1)
    assert device.value(HKEY_LOCAL_MACHINE, home, "InstlDir") == (REG_SZ, "\\Windows\\LoadTest")
    assert device.value(HKEY_LOCAL_MACHINE, home, "InstlDirCnt") == (REG_DWORD, 1)
    assert device.processes == [("\\Windows\\calc.exe", None)]
    assert "\\windows\\loadtest\\never.exe" not in device.files
    records = parse_unload_script(device.file("\\Windows\\Load Test.unload"))
    assert records[0] == ("3", ["l SOFTWARE\\Apps\\Load Test Tool"])
    assert ("3", ["r .loadtest "]) in records
    assert ("2", ["\\Windows\\Load Test\\Empty"]) in records
    assert ("0", ["\\Windows\\LoadTest", "tool.exe"]) in records
    assert records[-2:] == [("4", ["r .loadtest"]), ("5", ["\\Windows\\never.exe"])]
    assert device.file("\\Windows\\Load Test.unload").decode("utf-16-le").endswith("\\Windows\\never.exe\n\n")


def test_load_script_reports_bad_lines(tmp_path):
    (tmp_path / "Bad.load").write_text("frobnicate x\ncopy . . missing.exe\nmkdir\n")
    result = run(LoadScriptInstaller(FakeDevice(), tmp_path / "Bad.load").run())
    assert result.app_name == "Bad"
    assert result.install_directory == "\\Program Files\\Accessories"
    assert len(result.errors) == 3


def test_install_cab_queues_for_wceload():
    package = read_cab_package(build_ce_cab("App", "Vendor", 4000, [("a.txt", ["%CE1%"], b"a")]), "App.MIPS.cab")
    device = FakeDevice()
    outcome = run(install_cab(device, package, DeviceProfile(2, 0, 0, 4000)))
    assert outcome.name == "Vendor App"
    assert device.file("\\Windows\\AppMgr\\Install\\App.MIPS.cab") == package.data
    assert device.shortcuts == {"\\Windows\\StartUp\\Wceload.lnk": "\\Windows\\Wceload.exe"}
    assert device.processes == [("Wceload.exe", "/noaskdest")]
    with pytest.raises(InstallError, match="Handheld PC 1.0"):
        run(install_cab(device, package, DeviceProfile(1, 0, 0, 4000)))


def test_list_installed_apps(tmp_path):
    device = FakeDevice()
    run(LoadScriptInstaller(device, write_load_package(tmp_path), "\\Windows\\LoadTest").run())
    apps = run(list_installed_apps(device))
    assert [(app.name, app.install_directory) for app in apps] == [("Load Test", "\\Windows\\LoadTest")]


def test_desktop_records(tmp_path, monkeypatch):
    monkeypatch.setenv("CLASSICSYNC_HOME", str(tmp_path))
    ini = tmp_path / "HandMap.ini"
    ini.write_text(APPMGR_INI)
    (tmp_path / "HandMap.MIPS.cab").write_bytes(build_ce_cab("HandMap", "Widgets", 4000, [("a.txt", ["%CE1%"], b"a")]))
    records = DesktopAppRecords()
    records.add_file(ini)
    reloaded = DesktopAppRecords()
    assert reloaded.path == tmp_path / "appmgr" / "apps.json"
    app = reloaded.get("handmap")
    assert app.uninstall == "Widgets HandMap"
    packages = app.to_component().packages()
    assert [package.uninstall_name for package in packages] == ["Widgets HandMap"]
    reloaded.remove("HandMap")
    assert DesktopAppRecords().all() == []


def test_cabs_for_different_processors_merge_into_one_record(tmp_path, monkeypatch):
    from classicsync.install.records import DesktopAppRecords
    monkeypatch.setenv("CLASSICSYNC_HOME", str(tmp_path))
    mute = Path(__file__).resolve().parents[2] / "velo-apps" / "card" / "cabs"
    if not (mute / "mute.mips.cab").exists():
        pytest.skip("sample CABs not available")
    records = DesktopAppRecords()
    records.add_file(mute / "mute.mips.cab")
    records.add_file(mute / "mute.sh3.cab")
    apps = records.all()
    assert len(apps) == 1
    assert len(apps[0].cab_files) == 2
