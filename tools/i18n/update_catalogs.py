import argparse

from classicsync.i18n_catalogs import DEFAULT_PLURAL_FORMS, header_entry, header_fields, header_value, parse_po, write_po
from compile_catalogs import LOCALE
from extract_messages import collect_messages, write_template


def entry_key(entry):
    return entry.get("msgctxt"), entry["msgid"]


def write_catalog(path, language, messages, existing):
    plural_forms = header_value(existing.values(), "Plural-Forms")
    entries = [header_entry(header_fields(language, plural_forms or DEFAULT_PLURAL_FORMS))]
    for (context, singular), message in sorted(messages.items(), key=lambda item: (item[0][1], item[0][0] or "")):
        previous = existing.get((context, singular), {})
        entry = {"msgid": singular, "references": message["references"], "fuzzy": previous.get("fuzzy", False)}
        if context:
            entry["msgctxt"] = context
        if message["plural"]:
            entry["msgid_plural"] = message["plural"]
            forms = sorted(name for name in previous if name.startswith("msgstr[")) or ["msgstr[0]", "msgstr[1]"]
            entry.update({name: previous.get(name, "") for name in forms})
        else:
            entry["msgstr"] = previous.get("msgstr", "")
        entries.append(entry)
    write_po(path, entries)


def update(languages):
    messages = collect_messages()
    write_template(messages)
    targets = set(languages) | {path.parent.parent.name for path in LOCALE.glob("*/LC_MESSAGES/classicsync.po")}
    for language in sorted(targets):
        path = LOCALE / language / "LC_MESSAGES" / "classicsync.po"
        existing = {}
        if path.exists():
            for entry in parse_po(path):
                existing[entry_key(entry)] = entry
        write_catalog(path, language, messages, existing)
        translated = sum(1 for key in messages if existing.get(key, {}).get("msgstr") or existing.get(key, {}).get("msgstr[0]"))
        print(f"{language}: {translated}/{len(messages)} translated")


def main():
    parser = argparse.ArgumentParser(description="Re-extract messages and merge them into each language's classicsync.po")
    parser.add_argument("languages", nargs="*", help="language codes to create if missing, e.g. de fr ja")
    update(parser.parse_args().languages)


if __name__ == "__main__":
    main()
