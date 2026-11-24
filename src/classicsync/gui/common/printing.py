import os
import subprocess
import sys

PRINT_TIMEOUT_SECONDS = 60


def finder_print_script(path):
    quoted = str(path).replace("\\", "\\\\").replace('"', '\\"')
    return f'tell application "Finder" to print POSIX file "{quoted}"'


def print_command(path):
    if sys.platform == "darwin":
        return ["osascript", "-e", finder_print_script(path)]
    return ["lp", str(path)]


def print_file(path):
    if sys.platform == "win32":
        os.startfile(str(path), "print")
        return
    try:
        subprocess.run(print_command(path), check=True, capture_output=True, timeout=PRINT_TIMEOUT_SECONDS)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as error:
        raise OSError(str(error)) from error
