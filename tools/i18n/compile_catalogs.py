import argparse
from pathlib import Path

from classicsync.i18n_catalogs import compile_catalog

REPOSITORY = Path(__file__).resolve().parents[2]
LOCALE = REPOSITORY / "src" / "classicsync" / "locale"


def main():
    parser = argparse.ArgumentParser(description="Compile src/classicsync/locale/<lang>/LC_MESSAGES/classicsync.po files to .mo")
    parser.parse_args()
    compiled = 0
    for po_path in sorted(LOCALE.glob("*/LC_MESSAGES/classicsync.po")):
        compile_catalog(po_path, po_path.with_suffix(".mo"))
        compiled += 1
        print(f"compiled {po_path.relative_to(REPOSITORY)}")
    print(f"{compiled} catalog(s)")


if __name__ == "__main__":
    main()
