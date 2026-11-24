import ast
import struct

MO_MAGIC = 0x950412DE
DEFAULT_PLURAL_FORMS = "nplurals=2; plural=(n != 1);"
PO_ESCAPES = {"\\": "\\\\", '"': '\\"', "\t": "\\t", "\n": "\\n", "\r": "\\r"}


def quote(text):
    return '"' + "".join(PO_ESCAPES.get(character, character) for character in text) + '"'


def header_entry(fields):
    return {"msgid": "", "msgstr": "".join(f"{name}: {value}\n" for name, value in fields)}


def header_fields(language=None, plural_forms=DEFAULT_PLURAL_FORMS, extra=()):
    fields = [("Project-Id-Version", "classicsync")]
    fields.extend(extra)
    if language:
        fields.append(("Language", language))
    fields.extend([("MIME-Version", "1.0"), ("Content-Type", "text/plain; charset=UTF-8"),
                   ("Content-Transfer-Encoding", "8bit"), ("Plural-Forms", plural_forms)])
    return fields


def header_value(entries, name):
    for entry in entries:
        if entry["msgid"] == "" and "msgctxt" not in entry:
            for line in entry.get("msgstr", "").split("\n"):
                if line.startswith(name + ":"):
                    return line.partition(":")[2].strip()
    return None


def parse_po(path):
    entries = []
    current = {}
    field = None

    def finish():
        if "msgid" in current:
            entries.append(dict(current))
        current.clear()

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            finish()
            field = None
            continue
        if line.startswith("#"):
            if line.startswith("#,") and "fuzzy" in line:
                current["fuzzy"] = True
            continue
        keyword, _, rest = line.partition(" ")
        if line.startswith('"'):
            current[field] += ast.literal_eval(line)
            continue
        if keyword.startswith("msgstr["):
            field = keyword
        elif keyword in ("msgid", "msgid_plural", "msgstr", "msgctxt"):
            if keyword in ("msgid", "msgctxt") and "msgid" in current and field not in ("msgctxt",):
                finish()
            field = keyword
        else:
            continue
        current[field] = ast.literal_eval(rest)
    finish()
    return entries


def format_entry(entry):
    lines = [f"#. {comment}" for comment in entry.get("comments", ())]
    if entry.get("references"):
        lines.append("#: " + " ".join(entry["references"]))
    if entry.get("fuzzy"):
        lines.append("#, fuzzy")
    if entry.get("msgctxt") is not None:
        lines.append(f"msgctxt {quote(entry['msgctxt'])}")
    if entry["msgid"] == "" and entry.get("msgstr"):
        lines.append('msgid ""')
        lines.append('msgstr ""')
        lines.extend(quote(line + "\n") for line in entry["msgstr"].rstrip("\n").split("\n"))
        return lines
    lines.append(f"msgid {quote(entry['msgid'])}")
    if "msgid_plural" in entry:
        lines.append(f"msgid_plural {quote(entry['msgid_plural'])}")
        forms = sorted(name for name in entry if name.startswith("msgstr[")) or ["msgstr[0]", "msgstr[1]"]
        lines.extend(f"{name} {quote(entry.get(name, ''))}" for name in forms)
    else:
        lines.append(f"msgstr {quote(entry.get('msgstr', ''))}")
    return lines


def write_po(path, entries):
    lines = []
    for entry in entries:
        lines.extend(format_entry(entry))
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def compile_entries(entries):
    catalog = {}
    for entry in entries:
        if entry.get("fuzzy") and entry["msgid"]:
            continue
        key = entry["msgid"]
        if "msgctxt" in entry:
            key = entry["msgctxt"] + "\x04" + key
        if "msgid_plural" in entry:
            key += "\x00" + entry["msgid_plural"]
            forms = [entry[name] for name in sorted(name for name in entry if name.startswith("msgstr["))]
            if not any(forms):
                continue
            value = "\x00".join(forms)
        else:
            value = entry.get("msgstr", "")
            if not value:
                continue
        catalog[key] = value
    keys = sorted(catalog, key=lambda key: key.encode("utf-8"))
    identifiers = b""
    strings = b""
    offsets = []
    for key in keys:
        encoded_key = key.encode("utf-8")
        encoded_value = catalog[key].encode("utf-8")
        offsets.append((len(identifiers), len(encoded_key), len(strings), len(encoded_value)))
        identifiers += encoded_key + b"\0"
        strings += encoded_value + b"\0"
    header_size = 7 * 4
    key_table = header_size
    value_table = key_table + len(keys) * 8
    identifiers_start = value_table + len(keys) * 8
    strings_start = identifiers_start + len(identifiers)
    key_entries = b"".join(struct.pack("<II", length, identifiers_start + offset) for offset, length, _, _ in offsets)
    value_entries = b"".join(struct.pack("<II", length, strings_start + offset) for _, _, offset, length in offsets)
    header = struct.pack("<7I", MO_MAGIC, 0, len(keys), key_table, value_table, 0, 0)
    return header + key_entries + value_entries + identifiers + strings


def compile_catalog(po_path, mo_path):
    mo_path.parent.mkdir(parents=True, exist_ok=True)
    mo_path.write_bytes(compile_entries(parse_po(po_path)))
