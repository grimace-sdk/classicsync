import argparse
import platform
import plistlib
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import PyInstaller.__main__

REPOSITORY = Path(__file__).resolve().parents[1]
PACKAGING = REPOSITORY / "packaging"
BUILD = REPOSITORY / "build" / "pyinstaller"
DIST = REPOSITORY / "dist"


def version():
    sys.path.insert(0, str(REPOSITORY / "src"))
    from classicsync import __version__
    return __version__


def platform_name():
    system = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}.get(platform.system(), platform.system().lower())
    machine = platform.machine().lower().replace("amd64", "x86_64").replace("aarch64", "arm64")
    return f"{system}-{machine}"


CLI_FOLDER = "classicsync-cli"


def run_pyinstaller(name, script, windowed, stage):
    arguments = [
        str(script), "--name", name, "--noconfirm", "--clean", "--onedir",
        "--distpath", str(BUILD / stage / "dist"), "--workpath", str(BUILD / stage / "work"), "--specpath", str(BUILD / stage / "spec"),
        "--collect-submodules", "classicsync", "--collect-data", "classicsync", "--collect-all", "libusb_package", "--exclude-module", "numpy",
        "--paths", str(REPOSITORY / "src"),
    ]
    if not windowed:
        arguments += ["--exclude-module", "wx"]
    if windowed:
        arguments += ["--windowed", "--collect-all", "freetype"]
        if platform.system() == "Darwin":
            arguments += ["--osx-bundle-identifier", "org.classicsync.ClassicSync"]
    PyInstaller.__main__.run(arguments)


PRIVACY_DESCRIPTIONS = {
    "NSContactsUsageDescription": "ClassicSync synchronizes your contacts with your handheld.",
    "NSCalendarsUsageDescription": "ClassicSync synchronizes your calendar with your handheld.",
    "NSCalendarsFullAccessUsageDescription": "ClassicSync synchronizes your calendar with your handheld.",
    "NSRemindersUsageDescription": "ClassicSync synchronizes your reminders with your handheld's tasks.",
    "NSRemindersFullAccessUsageDescription": "ClassicSync synchronizes your reminders with your handheld's tasks.",
}


def add_privacy_descriptions(application):
    info_path = application / "Contents" / "Info.plist"
    with info_path.open("rb") as file:
        info = plistlib.load(file)
    info.update(PRIVACY_DESCRIPTIONS)
    with info_path.open("wb") as file:
        plistlib.dump(info, file)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(application)], check=True)


def archive(sources, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    if platform.system() == "Darwin":
        staging = BUILD / output.stem
        staging.mkdir(parents=True, exist_ok=True)
        for source, folder in sources:
            subprocess.run(["ditto", str(source), str(staging / folder)], check=True)
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(staging), str(output)], check=True)
        return output
    if output.suffix == ".zip":
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as bundle:
            for source, folder in sources:
                for path in sorted(source.rglob("*")):
                    bundle.write(path, Path(folder) / path.relative_to(source))
    else:
        with tarfile.open(output, "w:gz") as bundle:
            for source, folder in sources:
                bundle.add(source, arcname=folder)
    return output


def main():
    parser = argparse.ArgumentParser(description="Build standalone ClassicSync app and CLI bundles with PyInstaller")
    parser.add_argument("--skip-gui", action="store_true", help="only build the command-line tool")
    arguments = parser.parse_args()
    if BUILD.exists():
        shutil.rmtree(BUILD)
    run_pyinstaller("classicsync", PACKAGING / "launch_cli.py", windowed=False, stage="cli")
    cli_output = BUILD / "cli" / "dist" / "classicsync"
    subprocess.run([str(cli_output / ("classicsync.exe" if platform.system() == "Windows" else "classicsync")), "--help"],
                   check=True, stdout=subprocess.DEVNULL)
    outputs = [(cli_output, CLI_FOLDER)]
    if not arguments.skip_gui:
        run_pyinstaller("ClassicSync", PACKAGING / "launch_gui.py", windowed=True, stage="gui")
        gui_output = BUILD / "gui" / "dist" / ("ClassicSync.app" if platform.system() == "Darwin" else "ClassicSync")
        if platform.system() == "Darwin":
            add_privacy_descriptions(gui_output)
        outputs.append((gui_output, gui_output.name))
    extension = ".tar.gz" if platform.system() == "Linux" else ".zip"
    result = archive(outputs, DIST / f"ClassicSync-{version()}-{platform_name()}{extension}")
    print(result)


if __name__ == "__main__":
    main()
