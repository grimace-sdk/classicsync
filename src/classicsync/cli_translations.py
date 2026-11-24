import asyncio

from .formats.cab import CabError
from .formats.win32_resources import ResourceError
from .i18n import _
from .translation_import import import_translations

COVERAGE_KINDS = ("string", "dialog", "menu", "message")


def coverage_line(totals):
    parts = []
    for kind in COVERAGE_KINDS:
        counts = totals.get(kind)
        if counts and counts["total"]:
            parts.append(_("{kind} {translated}/{total} ({percent}%, {same} at the same id)").format(
                kind=kind, translated=counts["translated"], total=counts["total"],
                percent=100 * counts["translated"] // counts["total"], same=counts["same_position"]))
    return ", ".join(parts)


def print_summary(summary):
    for catalog in summary.catalogs:
        print(_("{language}: {translations} translations, {derived} without accelerators, {conflicts} conflicts -> {path}").format(
            language=catalog.code, translations=len(catalog.chosen), derived=len(catalog.derived), conflicts=len(catalog.conflicts),
            path=summary.written[catalog.code]))
        for coverage in catalog.coverage:
            print("  " + _("{product}, {count} modules shared with the paired build: {coverage}").format(
                product=coverage.product, count=len(coverage.shared_modules), coverage=coverage_line(coverage.totals(shared_only=True))))
            print("  " + _("{product}, all {count} modules: {coverage}").format(
                product=coverage.product, count=len(coverage.modules), coverage=coverage_line(coverage.totals())))


async def command_import_translations(arguments):
    try:
        summary = await asyncio.to_thread(import_translations, arguments.installers, arguments.destination,
                                          print if arguments.verbose else None)
    except (CabError, ResourceError) as error:
        raise ValueError(str(error)) from error
    print_summary(summary)
    if summary.unpaired:
        names = ", ".join(str(path) for path in summary.unpaired)
        print(_("no English build of the same product for: {names}").format(names=names))
    if summary.unrecognised:
        names = ", ".join(str(path) for path in summary.unrecognised)
        raise ValueError(_("not a recognised installer: {names}").format(names=names))
    if not summary.catalogs:
        raise ValueError(_("no English and localized builds of the same product were given"))


def add_commands(subparsers):
    import_command = subparsers.add_parser(
        "import-translations",
        help=_("build translation catalogs from English and localized copies of the original installers"))
    import_command.add_argument("installers", nargs="+", metavar="INSTALLER",
                                help=_("English and localized installers (.msi or .exe), or directories of them; "
                                       "an English installer with no localized build is matched by text and resource id"))
    import_command.add_argument("--destination", help=_("locale directory (default: <data directory>/locale)"))
    import_command.set_defaults(handler=command_import_translations)
