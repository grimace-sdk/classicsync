import argparse
import ast
from datetime import datetime, timezone
from pathlib import Path

from classicsync.i18n_catalogs import header_entry, header_fields, write_po

REPOSITORY = Path(__file__).resolve().parents[2]
SOURCE = REPOSITORY / "src" / "classicsync"
LOCALE = SOURCE / "locale"
TEMPLATE = LOCALE / "classicsync.pot"

SINGLE_FUNCTIONS = {"_", "N_"}
PLURAL_FUNCTIONS = {"ngettext"}
CONTEXT_FUNCTIONS = {"pgettext"}


def literal(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def function_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def extract_file(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = function_name(node.func)
        arguments = [literal(argument) for argument in node.args]
        if name in SINGLE_FUNCTIONS and arguments and arguments[0] is not None:
            found.append((None, arguments[0], None, node.lineno))
        elif name in PLURAL_FUNCTIONS and len(arguments) >= 2 and None not in arguments[:2]:
            found.append((None, arguments[0], arguments[1], node.lineno))
        elif name in CONTEXT_FUNCTIONS and len(arguments) >= 2 and None not in arguments[:2]:
            found.append((arguments[0], arguments[1], None, node.lineno))
    return found


def collect_messages(source=SOURCE):
    messages = {}
    for path in sorted(source.rglob("*.py")):
        for context, singular, plural, line in extract_file(path):
            key = (context, singular)
            entry = messages.setdefault(key, {"plural": plural, "references": []})
            entry["plural"] = entry["plural"] or plural
            entry["references"].append(f"{path.relative_to(source.parent)}:{line}")
    return messages


def write_template(messages, path=TEMPLATE):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M+0000")
    entries = [header_entry(header_fields(extra=[("POT-Creation-Date", stamp)]))]
    for (context, singular), entry in sorted(messages.items(), key=lambda item: (item[0][1], item[0][0] or "")):
        template_entry = {"msgid": singular, "msgstr": "", "references": entry["references"]}
        if context:
            template_entry["msgctxt"] = context
        if entry["plural"]:
            template_entry["msgid_plural"] = entry["plural"]
            template_entry.update({"msgstr[0]": "", "msgstr[1]": ""})
        entries.append(template_entry)
    write_po(path, entries)


def main():
    parser = argparse.ArgumentParser(description="Extract translatable strings from classicsync into locale/classicsync.pot")
    parser.add_argument("--output", type=Path, default=TEMPLATE)
    arguments = parser.parse_args()
    messages = collect_messages()
    write_template(messages, arguments.output)
    print(f"{len(messages)} messages -> {arguments.output}")


if __name__ == "__main__":
    main()
