import asyncio

from .artwork_import import import_artwork
from .formats.cab import CabError
from .formats.pe_resources import MissingDependencyError
from .i18n import _


async def command_import_artwork(arguments):
    try:
        summary = await asyncio.to_thread(import_artwork, arguments.installers, arguments.destination,
                                          print if arguments.verbose else None)
    except (MissingDependencyError, CabError) as error:
        raise ValueError(str(error)) from error
    for result in summary.products:
        print(_("{installer}: {product}, {resources} resources from {modules} modules, {sounds} sounds -> {directory}").format(
            installer=result.installer.name, product=result.product, resources=result.resource_count, modules=len(result.modules),
            sounds=len(result.sounds), directory=result.directory))
        for message in result.skipped:
            print("  " + _("skipped {message}").format(message=message))
    if summary.unrecognised:
        names = ", ".join(str(path) for path in summary.unrecognised)
        raise ValueError(_("not a recognised H/PC Explorer 1.1, CE Services 2.2 or ActiveSync 3.1 installer: {names}").format(names=names))


def add_commands(subparsers):
    import_command = subparsers.add_parser(
        "import-artwork", help=_("extract the original artwork from H/PC Explorer, CE Services or ActiveSync installers"))
    import_command.add_argument("installers", nargs="+", metavar="FILE",
                                help=_("hhpcex11.exe, WCES22-2.EXE or msasync.exe (or another copy of those installers)"))
    import_command.add_argument("--destination", help=_("artwork directory (default: <data directory>/artwork)"))
    import_command.set_defaults(handler=command_import_artwork)
