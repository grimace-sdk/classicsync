import pytest

pytest.importorskip("wx")

from classicsync.gui.common.device_browser import unused_path  # noqa: E402


def test_unused_path_numbers_existing_and_taken_names(tmp_path):
    (tmp_path / "romdump.txt").write_text("old")
    (tmp_path / "romdump (2).txt").write_text("old")
    assert unused_path(tmp_path / "romdump.txt") == tmp_path / "romdump (3).txt"
    assert unused_path(tmp_path / "romdump.txt", {tmp_path / "romdump (3).txt"}) == tmp_path / "romdump (4).txt"
    assert unused_path(tmp_path / "new.txt") == tmp_path / "new.txt"
