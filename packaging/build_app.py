import argparse
import platform
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


def run_pyinstaller(name, script, windowed):
    arguments = [
        str(script), "--name", name, "--noconfirm", "--clean", "--onedir",
        "--distpath", str(BUILD / "dist"), "--workpath", str(BUILD / "work"), "--specpath", str(BUILD / "spec"),
        "--collect-submodules", "classicsync", "--collect-data", "classicsync",
        "--paths", str(REPOSITORY / "src"),
    ]
    if not windowed:
        arguments += ["--exclude-module", "wx", "--exclude-module", "classicsync.gui"]
    if windowed:
        arguments.append("--windowed")
        if platform.system() == "Darwin":
            arguments += ["--osx-bundle-identifier", "org.classicsync.ClassicSync"]
    PyInstaller.__main__.run(arguments)


def archive(source_directories, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    if platform.system() == "Darwin":
        staging = BUILD / output.stem
        staging.mkdir(parents=True, exist_ok=True)
        for source in source_directories:
            subprocess.run(["ditto", str(source), str(staging / source.name)], check=True)
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(staging), str(output)], check=True)
        return output
    if output.suffix == ".zip":
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as bundle:
            for source in source_directories:
                for path in sorted(source.rglob("*")):
                    bundle.write(path, path.relative_to(source.parent))
    else:
        with tarfile.open(output, "w:gz") as bundle:
            for source in source_directories:
                bundle.add(source, arcname=source.name)
    return output


def main():
    parser = argparse.ArgumentParser(description="Build standalone ClassicSync app and CLI bundles with PyInstaller")
    parser.add_argument("--skip-gui", action="store_true", help="only build the command-line tool")
    arguments = parser.parse_args()
    if BUILD.exists():
        shutil.rmtree(BUILD)
    run_pyinstaller("classicsync", PACKAGING / "launch_cli.py", windowed=False)
    outputs = [BUILD / "dist" / "classicsync"]
    if not arguments.skip_gui:
        run_pyinstaller("ClassicSync", PACKAGING / "launch_gui.py", windowed=True)
        gui_output = BUILD / "dist" / ("ClassicSync.app" if platform.system() == "Darwin" else "ClassicSync")
        outputs.append(gui_output)
    extension = ".tar.gz" if platform.system() == "Linux" else ".zip"
    result = archive(outputs, DIST / f"ClassicSync-{version()}-{platform_name()}{extension}")
    print(result)


if __name__ == "__main__":
    main()
