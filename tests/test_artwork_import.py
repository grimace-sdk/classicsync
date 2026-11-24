import hashlib
import os
from pathlib import Path

import pytest

from classicsync.artwork_import import archive_members, import_artwork
from classicsync.cli import main

REPOSITORY = Path(__file__).resolve().parents[1]
INSTALLER_DIRECTORY = Path(os.environ.get("CLASSICSYNC_INSTALLERS", REPOSITORY.parent / "classicsync-installers"))
INSTALLERS = {
    "hpc-explorer-1.1": INSTALLER_DIRECTORY / "hhpcex11.exe",
    "ce-services-2.2": INSTALLER_DIRECTORY / "WCES22-2.EXE",
    "activesync-3.1": INSTALLER_DIRECTORY / "msasync.exe",
}
KNOWN_FILES = {
    "activesync-3.1/WCESMgr.exe/bitmap_6008.bmp": "cdc6041a246ebb747950c24f50cbf53b53a91009efe71535cbd1bf8060b179f5",
    "activesync-3.1/WCESMgr.exe/bitmap_6007.bmp": "36ad041ad8cd791859d4d05e007bc26083cdd7e8dac0d5a1abce02687989ab07",
    "activesync-3.1/WCESMgr.exe/avi_147.avi": "19aca70e03e7f4dccf4525eb4f9786b92d218a3ceb0b9d09581abaabd3959883",
    "activesync-3.1/wcescomm.exe/group_icon_131.ico": "8915375a8481dd42996bb942f2ae8a6db6e9c63e3cb7cfd72e8c605c962fea62",
    "activesync-3.1/wcescomm.exe/wave_161.wav": "1cc4141fb8585fcb0bb752a05a15aec62435fff0110d4b0330432dfbc99460d8",
    "ce-services-2.2/SyncMgr.exe/bitmap_142.bmp": "aedc72816729b3e7150fffc19f6b40a861904d04148aa0be21fa84a80c8fc6bd",
    "hpc-explorer-1.1/hpcexpl.exe/bitmap_101.bmp": "4b6fa0e6779ba8cb144f654b3c487a386e3a0ae84918d64cb8ed5380853887c2",
    "hpc-explorer-1.1/hpcexpl.exe/avi_147.avi": "bbb23a09b6b80a0aa141b3de7a2bcf5d7e43ec71647de1954d539009b79535db",
    "hpc-explorer-1.1/pegconn.wav": "6339f4734bd3fd144444b8ca897f4510c0056f6ecdf190f8b1957784b86694a9",
}
KNOWN_MODULES = {
    "ce-services-2.2": ("SyncMgr.exe", "1cfd73e6554c16f555c6881f6439fa5d4f7f961ba09103eca8d075ab9ee1976e"),
    "activesync-3.1": ("WCESMgr.exe", "7af8f7116b51b4dc9f2b5680f47af3d6ca555553fd9b3b63d6218fd5d48e2f96"),
}

needs_installers = pytest.mark.skipif(not all(path.exists() for path in INSTALLERS.values()),
                                      reason="original installers not present in the repository root")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def imported(tmp_path_factory):
    pytest.importorskip("pefile")
    home = tmp_path_factory.mktemp("home")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("CLASSICSYNC_HOME", str(home))
        summary = import_artwork(list(INSTALLERS.values()))
    return home / "artwork", summary


@needs_installers
@pytest.mark.parametrize("product, expected", sorted(KNOWN_MODULES.items()))
def test_installer_modules_extract_byte_identical(product, expected):
    module, digest = expected
    members = dict(archive_members(INSTALLERS[product].read_bytes()))
    matches = [content for name, content in members.items() if name.replace("\\", "/").endswith("/" + module) or name == module]
    assert matches and hashlib.sha256(matches[0]).hexdigest() == digest


@needs_installers
def test_import_detects_each_product(imported):
    root, summary = imported
    assert not summary.unrecognised
    assert {result.product: result.installer for result in summary.products} == INSTALLERS
    for result in summary.products:
        assert result.directory == root / result.product
        assert sorted(sound.lower() for sound in result.sounds) == ["pegconn.wav", "pegdisc.wav"]
        assert result.resource_count > 100


@needs_installers
@pytest.mark.parametrize("relative, digest", sorted(KNOWN_FILES.items()))
def test_import_writes_known_resources(imported, relative, digest):
    root, _ = imported
    assert sha256(root / relative) == digest


@needs_installers
def test_import_includes_gui_state_bitmaps(imported):
    root, _ = imported
    manager = root / "activesync-3.1" / "WCESMgr.exe"
    for number in (6006, 6007, 6008, 6017, 6018, 6019, 6029):
        assert (manager / f"bitmap_{number}.bmp").exists()
    for number in (131, 132, 133, 134, 136):
        assert (root / "activesync-3.1" / "wcescomm.exe" / f"group_icon_{number}.ico").exists()


def test_unrecognised_installer_fails(tmp_path, monkeypatch, capsys):
    pytest.importorskip("pefile")
    monkeypatch.setenv("CLASSICSYNC_HOME", str(tmp_path))
    not_an_installer = tmp_path / "notes.txt"
    not_an_installer.write_bytes(b"nothing to see")
    assert main(["import-artwork", str(not_an_installer)]) == 1
    assert "not a recognised" in capsys.readouterr().err
    assert not (tmp_path / "artwork").exists()
