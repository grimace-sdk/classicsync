import json
import sys
import zipfile

import pytest

from classicsync import cli
from classicsync.sync import Partnership, SyncOptions
from classicsync.sync import plugin_install
from classicsync.sync.folder import FolderProvider
from classicsync.sync.plugin_install import (
    KIND_FILE, KIND_PACKAGE, PluginError, find_manifest_entry, install_plugin, load_manifest, record_hash, remove_plugin,
    requirement_name, update_plugin,
)
from classicsync.sync.plugins import ORIGIN_FILE, ORIGIN_LIBRARY, discover_plugins, library_directory, load_providers
from classicsync.sync.settings_schema import (
    Setting, SettingError, apply_to_options, effective_settings, load_global_settings, parse_assignments, provider_schema,
    save_global_settings,
)


def provider_source(class_name, provider_name, extra=""):
    return ("from classicsync.sync import CONTACTS, Provider\n\n\n"
            f"class {class_name}(Provider):\n"
            f"    name = {provider_name!r}\n"
            f"    display_name = {class_name!r}\n"
            "    object_types = (CONTACTS,)\n"
            "    settings_schema = [{'key': 'colour', 'type': 'choice', 'choices': ['red', 'blue'], 'default': 'red'}]\n"
            f"{extra}")


def build_wheel(directory, name, version, provider_name, requires=(), tag="py3-none-any"):
    module = name.replace("-", "_")
    dist_info = f"{module}-{version}.dist-info"
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n" + "".join(f"Requires-Dist: {item}\n" for item in requires)
    files = {
        f"{module}.py": provider_source("WheelProvider", provider_name),
        f"{dist_info}/METADATA": metadata,
        f"{dist_info}/WHEEL": f"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: {tag}\n",
        f"{dist_info}/entry_points.txt": f"[classicsync.sync_providers]\n{provider_name} = {module}:WheelProvider\n",
    }
    encoded = {path: text.encode() for path, text in files.items()}
    record = "".join(f"{path},{record_hash(data)},{len(data)}\n" for path, data in encoded.items()) + f"{dist_info}/RECORD,,\n"
    encoded[f"{dist_info}/RECORD"] = record.encode()
    wheel = directory / f"{module}-{version}-{tag}.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for path, data in encoded.items():
            archive.writestr(path, data)
    return wheel


@pytest.fixture
def plugin_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CLASSICSYNC_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "modules", dict(sys.modules))
    return tmp_path / "home" / "plugins"


@pytest.fixture
def no_installer(monkeypatch):
    monkeypatch.setattr(plugin_install, "find_installer", lambda: None)


def test_library_distribution_entry_points_are_discovered(plugin_home, tmp_path):
    wheel = build_wheel(tmp_path, "lib-plugin", "1.2", "libprovider")
    library = library_directory()
    library.mkdir(parents=True)
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(library)
    sources = discover_plugins()
    source = next(source for source in sources if source.origin == ORIGIN_LIBRARY)
    assert (source.name, source.version) == ("lib-plugin", "1.2")
    assert [provider.name for provider in source.providers] == ["libprovider"]
    assert str(library) in sys.path
    assert "libprovider" in load_providers()


def test_loose_plugin_files_load_from_new_and_legacy_folders(plugin_home):
    plugin_home.mkdir(parents=True)
    (plugin_home / "fresh.py").write_text(provider_source("Fresh", "fresh"))
    legacy = plugin_home.parent / "sync-plugins"
    legacy.mkdir()
    (legacy / "older.py").write_text(provider_source("Older", "older"))
    (plugin_home / "broken.py").write_text("raise RuntimeError('nope')\n")
    sources = {source.name: source for source in discover_plugins() if source.origin == ORIGIN_FILE}
    assert {"fresh", "older", "broken"} <= set(sources)
    assert "nope" in sources["broken"].errors[0]
    providers = load_providers()
    assert "fresh" in providers and "older" in providers and "folder" in providers


def test_setting_parsing_and_validation():
    assert Setting("flag", type="bool").parse("Yes") is True
    assert Setting("flag", type="bool").parse("off") is False
    assert Setting("depth", type="int", minimum=0).parse("3") == 3
    assert Setting("folders", type="list").parse(r"\My Documents; \Notes") == ["\\My Documents", "\\Notes"]
    colour = Setting("colour", type="choice", choices=[("r", "Red"), ("b", "Blue")])
    assert colour.parse("blue") == "b" and colour.parse("r") == "r"
    assert colour.format("b") == "Blue"
    with pytest.raises(SettingError):
        Setting("depth", type="int", minimum=0).parse("-1")
    with pytest.raises(SettingError):
        Setting("flag", type="bool").parse("maybe")
    with pytest.raises(SettingError):
        colour.parse("green")
    with pytest.raises(SettingError):
        Setting("odd", type="colour")
    with pytest.raises(SettingError):
        Setting("pick", type="choice")
    with pytest.raises(SettingError):
        Setting.from_value({"key": "x", "typo": 1})


def test_assignments_against_a_schema():
    schema = provider_schema(FolderProvider)
    assert [setting.key for setting in schema] == ["folder", "convert_documents", "converted_documents", "converted_spreadsheets",
                                                  "converted_images", "file_folders", "file_depth"]
    parsed = parse_assignments(schema, ["convert_documents=no", "file_depth=2", "folder="])
    assert parsed == {"convert_documents": False, "file_depth": 2, "folder": None}
    with pytest.raises(SettingError):
        parse_assignments(schema, ["colour=red"])
    with pytest.raises(SettingError):
        parse_assignments(schema, ["convert_documents"])
    assert parse_assignments([], ["anything=goes"]) == {"anything": "goes"}


def test_settings_precedence_default_global_device(plugin_home):
    options = SyncOptions()
    assert effective_settings(FolderProvider, options)["convert_documents"] is True
    save_global_settings("folder", {"convert_documents": False})
    assert load_global_settings("folder") == {"convert_documents": False}
    assert effective_settings(FolderProvider, options)["convert_documents"] is False
    apply_to_options(options, {"convert_documents": True, "file_depth": 3, "folder": "/tmp/x"})
    settings = effective_settings(FolderProvider, options)
    assert settings["convert_documents"] is True and settings["file_depth"] == 3 and settings["folder"] == "/tmp/x"
    apply_to_options(options, {"convert_documents": None, "file_depth": None})
    assert options.file_depth == 1 and "convert_documents" not in options.provider_settings


def test_install_and_remove_py_file_without_installer(plugin_home, tmp_path, no_installer):
    source = tmp_path / "csvish.py"
    source.write_text(provider_source("Csvish", "csvish", "__version__ = '0.3'\n"))
    entries = install_plugin(str(source))
    assert [(entry.name, entry.kind, entry.version, entry.providers) for entry in entries] == [("csvish", KIND_FILE, "0.3", ["csvish"])]
    assert (plugin_home / "csvish.py").is_file()
    manifest = load_manifest()
    assert manifest["csvish"].spec == str(source.resolve())
    assert find_manifest_entry(manifest, "csvish").name == "csvish"
    source.write_text(provider_source("Csvish", "csvish", "__version__ = '0.4'\n"))
    assert update_plugin("csvish")[0].version == "0.4"
    remove_plugin("csvish")
    assert not (plugin_home / "csvish.py").exists()
    assert load_manifest() == {}


def test_py_file_without_provider_is_refused(plugin_home, tmp_path, no_installer):
    source = tmp_path / "empty.py"
    source.write_text("VALUE = 1\n")
    with pytest.raises(PluginError):
        install_plugin(str(source))
    assert not (plugin_home / "empty.py").exists()


def test_install_wheel_without_installer(plugin_home, tmp_path, no_installer):
    wheel = build_wheel(tmp_path, "wheel-plugin", "2.0", "wheelprovider", requires=["classicsync>=0.1", "pytest; extra == 'test'"])
    entries = install_plugin(str(wheel))
    assert [(entry.name, entry.kind, entry.version, entry.tool, entry.providers) for entry in entries] == [
        ("wheel-plugin", KIND_PACKAGE, "2.0", "direct", ["wheelprovider"])]
    library = library_directory()
    assert (library / "wheel_plugin.py").is_file()
    record = (library / "wheel_plugin-2.0.dist-info" / "RECORD").read_text()
    assert "wheel_plugin.py" in record
    assert "wheelprovider" in load_providers()
    stored = json.loads((plugin_home / "manifest.json").read_text())
    assert stored["plugins"]["wheel-plugin"]["spec"] == str(wheel.resolve())
    remove_plugin("wheelprovider")
    assert sorted(path.name for path in library.iterdir()) == []


def test_wheel_needing_a_resolver_is_refused(plugin_home, tmp_path, no_installer):
    with pytest.raises(PluginError, match="needs uv or pip"):
        install_plugin("some-plugin>=1.0")
    with pytest.raises(PluginError, match="not-installed-anywhere"):
        install_plugin(str(build_wheel(tmp_path, "needy", "1.0", "needy", requires=["not-installed-anywhere"])))
    with pytest.raises(PluginError, match="particular platform"):
        install_plugin(str(build_wheel(tmp_path, "native", "1.0", "native", tag="cp313-cp313-macosx_11_0_arm64")))


def test_wheel_without_entry_points_is_refused(plugin_home, tmp_path, no_installer):
    wheel = build_wheel(tmp_path, "plain", "1.0", "plain")
    with zipfile.ZipFile(wheel) as source, zipfile.ZipFile(tmp_path / "plain-1.0-py3-none-any-copy.zip", "w") as copy:
        for item in source.infolist():
            if not item.filename.endswith("entry_points.txt"):
                copy.writestr(item, source.read(item))
    (tmp_path / "plain-1.0-py3-none-any-copy.zip").replace(wheel)
    with pytest.raises(PluginError, match="entry points"):
        install_plugin(str(wheel))
    assert not any(library_directory().iterdir())


def test_requirement_names():
    assert requirement_name("Some_Package>=1.0; python_version >= '3.8'") == "some-package"
    assert requirement_name("pytest; extra == 'test'") is None
    assert requirement_name("requests[socks]") == "requests"


def test_cli_configure_and_use(plugin_home, capsys):
    partnership = Partnership.for_device("Velo")
    partnership.partner_id = 0x1234
    partnership.save_info()
    assert cli.main(["plugin", "configure", "folder", "convert_documents=no"]) == 0
    assert load_global_settings("folder") == {"convert_documents": False}
    assert cli.main(["plugin", "configure", "folder", "file_depth=2"]) == 1
    assert cli.main(["plugin", "configure", "folder", "--device", "Velo", "file_depth=2", r"file_folders=\A;\B"]) == 0
    options = partnership.load_options()
    assert options.file_depth == 2 and options.file_folders == ["\\A", "\\B"]
    assert cli.main(["plugin", "use", "folder"]) == 0
    assert cli.main(["plugin", "use", "missing"]) == 1
    assert cli.main(["plugin", "list"]) == 0
    output = capsys.readouterr().out
    assert "file_depth = 2" in output and "folder: Folder" in output


@pytest.mark.skipif(plugin_install.find_uv() is None, reason="uv is not installed")
def test_install_wheel_with_uv(plugin_home, tmp_path, monkeypatch):
    monkeypatch.setenv("UV_OFFLINE", "1")
    wheel = build_wheel(tmp_path, "uv-plugin", "1.0", "uvprovider", requires=["classicsync"])
    entries = install_plugin(str(wheel))
    assert [(entry.name, entry.tool, entry.providers) for entry in entries] == [("uv-plugin", "uv", ["uvprovider"])]
    library = library_directory()
    assert not list(library.glob("classicsync-*.dist-info"))
    assert "uvprovider" in load_providers()
    assert update_plugin("uv-plugin")[0].version == "1.0"
    remove_plugin("uv-plugin")
    assert not list(library.glob("*.dist-info"))
