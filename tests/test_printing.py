import sys

from classicsync.gui.common.printing import finder_print_script, print_command


def test_finder_script_quotes_awkward_paths():
    assert finder_print_script('/tmp/a "b" \\c.docx') == 'tell application "Finder" to print POSIX file "/tmp/a \\"b\\" \\\\c.docx"'


def test_print_command_matches_the_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert print_command("/tmp/x.txt")[0] == "osascript"
    monkeypatch.setattr(sys, "platform", "linux")
    assert print_command("/tmp/x.txt") == ["lp", "/tmp/x.txt"]
