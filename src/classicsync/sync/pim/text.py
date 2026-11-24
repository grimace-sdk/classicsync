from dataclasses import dataclass, field

LINE_OCTETS = 75


@dataclass
class ContentLine:
    name: str
    value: str
    parameters: dict = field(default_factory=dict)

    def parameter(self, name):
        return self.parameters.get(name.upper(), [])

    def types(self):
        return {item.lower() for value in self.parameter("TYPE") for item in value.split(",")}


def escape_text(value):
    return (value.replace("\\", "\\\\").replace("\r\n", "\n").replace("\n", "\\n")
            .replace(",", "\\,").replace(";", "\\;"))


def unescape_text(value):
    result = []
    index = 0
    while index < len(value):
        character = value[index]
        if character == "\\" and index + 1 < len(value):
            following = value[index + 1]
            result.append("\n" if following in "nN" else following)
            index += 2
        else:
            result.append(character)
            index += 1
    return "".join(result)


def split_escaped(value, separator):
    parts = []
    current = []
    index = 0
    while index < len(value):
        character = value[index]
        if character == "\\" and index + 1 < len(value):
            current.append(value[index:index + 2])
            index += 2
            continue
        if character == separator:
            parts.append("".join(current))
            current = []
        else:
            current.append(character)
        index += 1
    parts.append("".join(current))
    return parts


def fold_line(line):
    encoded = line.encode("utf-8")
    if len(encoded) <= LINE_OCTETS:
        return line
    pieces = []
    current = ""
    limit = LINE_OCTETS
    for character in line:
        if len((current + character).encode("utf-8")) > limit:
            pieces.append(current)
            current = ""
            limit = LINE_OCTETS - 1
        current += character
    pieces.append(current)
    return "\r\n ".join(pieces)


def format_parameter_value(value):
    if any(character in value for character in ':;,'):
        return '"' + value.replace('"', "'") + '"'
    return value


def format_line(name, value, parameters=None):
    text = name
    for parameter_name, parameter_value in (parameters or {}).items():
        values = parameter_value if isinstance(parameter_value, (list, tuple)) else [parameter_value]
        text += f";{parameter_name}=" + ",".join(format_parameter_value(str(item)) for item in values)
    return fold_line(f"{text}:{value}")


def unfold(text):
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw.strip():
            lines.append(raw)
    return lines


def parse_line(line):
    index = 0
    quoted = False
    while index < len(line):
        character = line[index]
        if character == '"':
            quoted = not quoted
        elif character == ":" and not quoted:
            break
        index += 1
    head, value = line[:index], line[index + 1:]
    name, *raw_parameters = split_quoted(head, ";")
    if "." in name:
        name = name.split(".", 1)[1]
    parameters = {}
    for raw in raw_parameters:
        key, _, raw_value = raw.partition("=")
        values = [item.strip('"') for item in split_quoted(raw_value, ",")] if raw_value else [key]
        parameters.setdefault(key.upper() if raw_value else "TYPE", []).extend(values)
    return ContentLine(name.upper(), value, parameters)


def split_quoted(text, separator):
    parts = []
    current = []
    quoted = False
    for character in text:
        if character == '"':
            quoted = not quoted
            current.append(character)
        elif character == separator and not quoted:
            parts.append("".join(current))
            current = []
        else:
            current.append(character)
    parts.append("".join(current))
    return parts


def parse_components(text):
    root = {"name": "", "lines": [], "children": []}
    stack = [root]
    for raw in unfold(text):
        line = parse_line(raw)
        if line.name == "BEGIN":
            component = {"name": line.value.upper(), "lines": [], "children": []}
            stack[-1]["children"].append(component)
            stack.append(component)
        elif line.name == "END":
            if len(stack) > 1:
                stack.pop()
        else:
            stack[-1]["lines"].append(line)
    return root["children"]


def first_line(component, name):
    return next((line for line in component["lines"] if line.name == name), None)


def all_lines(component, name):
    return [line for line in component["lines"] if line.name == name]
