import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "src"))

from classicsync.artwork_import import import_artwork  # noqa: E402

DESTINATION = REPOSITORY / "src" / "classicsync" / "gui" / "artwork_data"
DEFAULT_INSTALLERS = Path(os.environ.get("CLASSICSYNC_INSTALLERS", REPOSITORY.parent / "classicsync-installers"))
INSTALLER_NAMES = ("hhpcex11.exe", "WCES22-2.EXE", "msasync.exe")
EXCLUDED_MODULES = {
    "_setup.dll", "_isres.dll", "setup.exe", "is_setup.exe", "401cmupd.exe", "uninst.exe", "setupstr.dll", "userdlgs.dll",
}
EXCLUDED_SUFFIXES = (".mips", ".sh3", ".arm")


def keep(module):
    name = module.name.lower()
    return name not in EXCLUDED_MODULES and not name.endswith(EXCLUDED_SUFFIXES)


def main():
    parser = argparse.ArgumentParser(description="Regenerate the artwork shipped in src/classicsync/gui/artwork_data from the original installers")
    parser.add_argument("installers", nargs="*", type=Path, help=f"installers (default: {', '.join(INSTALLER_NAMES)} in $CLASSICSYNC_INSTALLERS)")
    arguments = parser.parse_args()
    installers = arguments.installers or [DEFAULT_INSTALLERS / name for name in INSTALLER_NAMES]
    missing = [path for path in installers if not path.exists()]
    if missing:
        parser.error("missing: " + ", ".join(str(path) for path in missing))
    with tempfile.TemporaryDirectory() as staging:
        staging_path = Path(staging)
        import_artwork(installers, destination=staging_path)
        if DESTINATION.exists():
            shutil.rmtree(DESTINATION)
        for product in sorted(staging_path.iterdir()):
            for item in sorted(product.iterdir()):
                if item.is_dir() and not keep(item):
                    continue
                target = DESTINATION / product.name / item.name
                target.parent.mkdir(parents=True, exist_ok=True)
                if item.is_dir():
                    shutil.copytree(item, target)
                else:
                    shutil.copy2(item, target)
    total = sum(path.stat().st_size for path in DESTINATION.rglob("*") if path.is_file())
    print(f"{DESTINATION.relative_to(REPOSITORY)}: {total // 1024} KB")


if __name__ == "__main__":
    main()
