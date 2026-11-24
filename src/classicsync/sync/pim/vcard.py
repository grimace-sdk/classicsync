from ...rapi.cedb import CEVT_FILETIME, CEVT_LPWSTR
from .properties import CONTACT_DATE_FIELDS, CONTACT_FILE_AS, CONTACT_TEXT_FIELDS
from .record import (
    filetime_for_local_date, format_date, local_date_from_filetime, merge_properties, parse_date, property_map, text_value,
)
from .text import all_lines, escape_text, first_line, format_line, parse_components, split_escaped, unescape_text

PRODID = "-//classicsync//classicsync//EN"

TEXT_KEYS = {name: (identifier, CEVT_LPWSTR) for name, identifier in CONTACT_TEXT_FIELDS.items()}
DATE_KEYS = {name: (identifier, CEVT_FILETIME) for name, identifier in CONTACT_DATE_FIELDS.items()}
FILE_AS_KEY = (CONTACT_FILE_AS, CEVT_LPWSTR)
OWNED = set(TEXT_KEYS.values()) | set(DATE_KEYS.values()) | {FILE_AS_KEY}

PHONE_FIELDS = [
    ("work_phone", ["work", "voice"]),
    ("work_phone2", ["work", "voice"]),
    ("home_phone", ["home", "voice"]),
    ("home_phone2", ["home", "voice"]),
    ("mobile_phone", ["cell"]),
    ("car_phone", ["x-car"]),
    ("pager", ["pager"]),
    ("work_fax", ["work", "fax"]),
    ("home_fax", ["home", "fax"]),
    ("assistant_phone", ["x-assistant"]),
]
ADDRESS_FIELDS = [("home", ["home"]), ("work", ["work"]), ("other", [])]
ADDRESS_PARTS = ["street", "city", "state", "postal_code", "country"]
EMAIL_FIELDS = ["email1", "email2", "email3"]
RELATED_FIELDS = [("spouse", "spouse"), ("children", "child")]


def contact_fields(properties):
    values = property_map(properties)
    fields = {name: text_value(values, key) for name, key in TEXT_KEYS.items()}
    for name, key in DATE_KEYS.items():
        fields[name] = values.get(key)
    return fields


def display_name(fields):
    parts = [fields["name_prefix"], fields["given_name"], fields["middle_name"], fields["surname"], fields["generation"]]
    name = " ".join(part for part in parts if part)
    return name or fields["company"] or fields["email1"] or "Unnamed"


def default_file_as(fields):
    if fields.get("surname") and fields.get("given_name"):
        return f"{fields['surname']}, {fields['given_name']}"
    return fields.get("surname") or fields.get("given_name") or fields.get("company") or ""


def contact_to_vcard(properties, uid=None):
    fields = contact_fields(properties)
    lines = ["BEGIN:VCARD", "VERSION:4.0", f"PRODID:{PRODID}"]
    if uid:
        lines.append(format_line("UID", uid))
    lines.append(format_line("FN", escape_text(display_name(fields))))
    name_parts = [fields["surname"], fields["given_name"], fields["middle_name"], fields["name_prefix"], fields["generation"]]
    lines.append(format_line("N", ";".join(escape_text(part) for part in name_parts)))
    if fields["company"] or fields["department"]:
        organisation = escape_text(fields["company"])
        if fields["department"]:
            organisation += ";" + escape_text(fields["department"])
        lines.append(format_line("ORG", organisation))
    if fields["title"]:
        lines.append(format_line("TITLE", escape_text(fields["title"])))
    for index, name in enumerate(EMAIL_FIELDS):
        if fields[name]:
            lines.append(format_line("EMAIL", escape_text(fields[name]), {"PREF": str(index + 1)}))
    for name, types in PHONE_FIELDS:
        if fields[name]:
            lines.append(format_line("TEL", escape_text(fields[name]), {"TYPE": types}))
    for prefix, types in ADDRESS_FIELDS:
        parts = [fields[f"{prefix}_{part}"] for part in ADDRESS_PARTS]
        if any(parts):
            value = ";".join(["", ""] + [escape_text(part) for part in parts])
            lines.append(format_line("ADR", value, {"TYPE": types} if types else None))
    if fields["web_page"]:
        lines.append(format_line("URL", fields["web_page"]))
    for name, related_type in RELATED_FIELDS:
        if fields[name]:
            lines.append(format_line("RELATED", escape_text(fields[name]), {"TYPE": related_type, "VALUE": "text"}))
    if fields["assistant"]:
        lines.append(format_line("X-ASSISTANT", escape_text(fields["assistant"])))
    if fields["office_location"]:
        lines.append(format_line("X-OFFICE-LOCATION", escape_text(fields["office_location"])))
    if fields["categories"]:
        categories = [item.strip() for item in fields["categories"].split(",") if item.strip()]
        lines.append(format_line("CATEGORIES", ",".join(escape_text(item) for item in categories)))
    for name, vcard_name in (("birthday", "BDAY"), ("anniversary", "ANNIVERSARY")):
        if fields[name]:
            lines.append(format_line(vcard_name, format_date(local_date_from_filetime(fields[name]))))
    if fields["notes"]:
        lines.append(format_line("NOTE", escape_text(fields["notes"])))
    lines.append("END:VCARD")
    return "\r\n".join(lines) + "\r\n"


def structured(line, count):
    parts = [unescape_text(part) for part in split_escaped(line.value, ";")]
    return (parts + [""] * count)[:count]


def assign_in_order(fields, candidates, value):
    for name in candidates:
        if not fields.get(name):
            fields[name] = value
            return


def phone_targets(types):
    if "fax" in types:
        return ["home_fax"] if "home" in types else ["work_fax"]
    if "cell" in types or "mobile" in types:
        return ["mobile_phone"]
    if "pager" in types:
        return ["pager"]
    if "x-car" in types or "car" in types:
        return ["car_phone"]
    if "x-assistant" in types:
        return ["assistant_phone"]
    if "home" in types:
        return ["home_phone", "home_phone2"]
    return ["work_phone", "work_phone2", "home_phone", "home_phone2", "mobile_phone"]


def parse_vcard_fields(text):
    components = [component for component in parse_components(text) if component["name"] == "VCARD"]
    if not components:
        raise ValueError("no VCARD in file")
    card = components[0]
    fields = {}
    name = first_line(card, "N")
    if name:
        fields["surname"], fields["given_name"], fields["middle_name"], fields["name_prefix"], fields["generation"] = structured(name, 5)
    else:
        formatted = first_line(card, "FN")
        if formatted:
            fields["given_name"] = unescape_text(formatted.value)
    organisation = first_line(card, "ORG")
    if organisation:
        fields["company"], fields["department"] = structured(organisation, 2)
    for vcard_name, field_name in (("TITLE", "title"), ("NOTE", "notes"), ("X-ASSISTANT", "assistant"),
                                   ("X-OFFICE-LOCATION", "office_location")):
        line = first_line(card, vcard_name)
        if line:
            fields[field_name] = unescape_text(line.value)
    url = first_line(card, "URL")
    if url:
        fields["web_page"] = url.value
    emails = sorted(all_lines(card, "EMAIL"), key=lambda line: int((line.parameter("PREF") or ["100"])[0]))
    for line, field_name in zip(emails, EMAIL_FIELDS):
        fields[field_name] = unescape_text(line.value)
    for line in all_lines(card, "TEL"):
        value = unescape_text(line.value)
        if value.lower().startswith("tel:"):
            value = value[4:]
        assign_in_order(fields, phone_targets(line.types()), value)
    for line in all_lines(card, "ADR"):
        types = line.types()
        prefix = "home" if "home" in types else "work" if "work" in types else "other"
        if any(fields.get(f"{prefix}_{part}") for part in ADDRESS_PARTS):
            prefix = "other"
        _, extended, street, *rest = structured(line, 7)
        street = "\n".join(part for part in (extended, street) if part)
        for part, value in zip(ADDRESS_PARTS, [street, *rest]):
            fields[f"{prefix}_{part}"] = value
    for line in all_lines(card, "RELATED"):
        types = line.types()
        for field_name, related_type in RELATED_FIELDS:
            if related_type in types:
                fields[field_name] = unescape_text(line.value)
    categories = first_line(card, "CATEGORIES")
    if categories:
        fields["categories"] = ", ".join(unescape_text(item) for item in split_escaped(categories.value, ","))
    for vcard_name, field_name in (("BDAY", "birthday"), ("ANNIVERSARY", "anniversary")):
        line = first_line(card, vcard_name)
        if line and len(line.value.replace("-", "")) >= 8 and line.value[:1].isdigit():
            fields[field_name] = parse_date(line.value[:10])
    return fields


def vcard_to_contact(text, base_properties=()):
    fields = parse_vcard_fields(text)
    values = {}
    for name, key in TEXT_KEYS.items():
        value = fields.get(name)
        values[key] = value if value else None
    for name, key in DATE_KEYS.items():
        values[key] = filetime_for_local_date(fields[name]) if fields.get(name) else None
    base = list(base_properties)
    previous_file_as = property_map(base).get(FILE_AS_KEY)
    if not previous_file_as or previous_file_as == default_file_as(contact_fields(base)):
        values[FILE_AS_KEY] = default_file_as(fields) or None
    else:
        values[FILE_AS_KEY] = previous_file_as
    return merge_properties(base, OWNED, values)
