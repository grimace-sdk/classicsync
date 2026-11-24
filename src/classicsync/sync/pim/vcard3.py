from .text import fold_line, format_line, parse_line, unfold

RELATED_NAMES_3 = {"spouse": "X-SPOUSE", "child": "X-CHILDREN"}
RELATED_TYPES_4 = {"X-SPOUSE": "spouse", "X-EVOLUTION-SPOUSE": "spouse", "X-CHILDREN": "child"}


def card_version(text):
    for raw in unfold(text):
        line = parse_line(raw)
        if line.name == "VERSION":
            return line.value.strip()
    return ""


def render(lines):
    return "\r\n".join(fold_line(line) for line in lines) + "\r\n"


def vcard_to_version3(text):
    lines = []
    for raw in unfold(text):
        line = parse_line(raw)
        if line.name == "VERSION":
            lines.append("VERSION:3.0")
        elif line.name == "EMAIL":
            types = ["INTERNET"]
            if line.parameter("PREF") == ["1"]:
                types.append("pref")
            lines.append(format_line("EMAIL", line.value, {"TYPE": types}))
        elif line.name == "RELATED":
            related_name = next((name for kind, name in RELATED_NAMES_3.items() if kind in line.types()), None)
            if related_name:
                lines.append(format_line(related_name, line.value))
        elif line.name == "ANNIVERSARY":
            value = line.value.strip()
            if len(value) == 8 and value.isdigit():
                value = f"{value[:4]}-{value[4:6]}-{value[6:]}"
            lines.append(format_line("X-ANNIVERSARY", value))
        else:
            lines.append(raw)
    return render(lines)


def vcard_to_version4(text):
    lines = []
    for raw in unfold(text):
        line = parse_line(raw)
        if line.name == "X-ANNIVERSARY":
            lines.append(format_line("ANNIVERSARY", line.value))
        elif line.name in RELATED_TYPES_4:
            lines.append(format_line("RELATED", line.value, {"TYPE": RELATED_TYPES_4[line.name], "VALUE": "text"}))
        elif line.name == "EMAIL" and "pref" in line.types() and not line.parameter("PREF"):
            lines.append(format_line("EMAIL", line.value, {"PREF": "1"}))
        else:
            lines.append(raw)
    return render(lines)


def vcard_in_version(text, version):
    return vcard_to_version3(text) if version.startswith("3") else text
