import sys
from pathlib import Path

from .convert import FORMATS, convert, format_for_extension
from .i18n import _


async def command_convert(arguments):
    output = Path(arguments.output)
    target = arguments.target or format_for_extension(output.suffix)
    if target is None:
        raise ValueError(_("cannot tell the output format from {name!r}; use --to").format(name=output.name))
    options = {}
    if arguments.format_version:
        options["version"] = arguments.format_version
    if arguments.sheet is not None:
        options["sheet"] = arguments.sheet
    result = convert(arguments.input, arguments.source, target, **options)
    output.write_bytes(result.data)
    print(f"{arguments.input} ({result.source_format}) -> {output} ({result.target_format})")
    for warning in result.warnings:
        print("  " + _("not kept: {warning}").format(warning=warning), file=sys.stderr)


def add_commands(subparsers):
    formats = ", ".join(sorted(FORMATS))
    command = subparsers.add_parser(
        "convert", help=_("convert Pocket Word, Pocket Excel and 2bp files to and from desktop formats"),
        description=_("Formats: {formats}. The input format comes from its extension or contents, the output "
                      "format from the output extension.").format(formats=formats))
    command.add_argument("input")
    command.add_argument("output")
    command.add_argument("--from", dest="source", metavar="FORMAT", help=_("input format"))
    command.add_argument("--to", dest="target", metavar="FORMAT", help=_("output format"))
    command.add_argument("--format-version", type=int, choices=[1, 2],
                         help=_("Pocket Word/Excel file version to write: 1 for Windows CE 1.0, 2 (default) for CE 2.x"))
    command.add_argument("--sheet", type=int, help=_("sheet number to write to CSV (from 0)"))
    command.set_defaults(handler=command_convert)
