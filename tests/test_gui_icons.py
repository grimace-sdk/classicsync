import struct
from types import SimpleNamespace

import pytest

pytest.importorskip("wx")

from classicsync.gui.common.artwork import icon_entries  # noqa: E402
from classicsync.gui.common.file_icons import (  # noqa: E402
    ACTIVESYNC_ICONS, BASE_KINDS, CE_SERVICES_ICONS, HPC_EXPLORER_ICONS, KIND_FILE, KIND_FOLDER, FileIcons,
)
from classicsync.gui.common.icon_grid import is_grid_style  # noqa: E402


def entry(name, directory=False):
    return SimpleNamespace(name=name, is_directory=directory)


def shell_number(icons, index):
    return icons.extra_numbers[index - len(BASE_KINDS)]


def test_hpc_explorer_documents_and_applications_use_minshell_indices():
    icons = FileIcons(table=HPC_EXPLORER_ICONS)
    assert shell_number(icons, icons.index_for(entry("Letter.pwd"))) == 4
    assert shell_number(icons, icons.index_for(entry("Amortize.PXL"))) == 6
    assert shell_number(icons, icons.index_for(entry("pword.exe"))) == 5
    assert icons.index_for(entry("Template.pwt")) == BASE_KINDS.index(KIND_FILE)
    assert icons.index_for(entry("Samples", directory=True)) == BASE_KINDS.index(KIND_FOLDER)


def test_ce_services_and_activesync_tables():
    ce_services = FileIcons(table=CE_SERVICES_ICONS)
    assert shell_number(ce_services, ce_services.index_for(entry("Template.pwt"))) == 32
    assert shell_number(ce_services, ce_services.index_for(entry("iexplore.exe"))) == 17
    assert ce_services.index_for(entry("poutlook.exe")) == BASE_KINDS.index(KIND_FILE)
    activesync = FileIcons(table=ACTIVESYNC_ICONS)
    assert shell_number(activesync, activesync.index_for(entry("poutlook.exe"))) == 34


def test_without_artwork_every_file_is_generic():
    icons = FileIcons()
    assert icons.index_for(entry("Letter.pwd")) == BASE_KINDS.index(KIND_FILE)


def test_icon_entries_skip_unloadable_depths():
    image = b"\0" * 40
    header = struct.pack("<HHH", 0, 1, 2)
    first = struct.pack("<BBBBHHII", 16, 16, 0, 0, 1, 2, len(image), 6 + 32)
    second = struct.pack("<BBBBHHII", 32, 32, 16, 0, 1, 4, len(image), 6 + 32 + len(image))
    entries = icon_entries(header + first + second + image + image)
    assert [(width, depth) for width, height, colours, planes, depth, size, start in entries] == [(32, 4)]


def test_grid_only_for_icon_views_off_windows():
    import wx
    expected = wx.Platform != "__WXMSW__"
    assert is_grid_style(wx.LC_ICON) is expected
    assert is_grid_style(wx.LC_SMALL_ICON) is expected
    assert not is_grid_style(wx.LC_REPORT)
    assert not is_grid_style(wx.LC_LIST)
