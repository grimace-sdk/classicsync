from dataclasses import dataclass, field
from datetime import date, datetime

from .text import fold_line, parse_line, unfold

MOMENT_NAMES = ("DTSTART", "DTEND", "DUE", "COMPLETED", "BDAY", "ANNIVERSARY")


@dataclass
class Block:
    name: str
    begin: str = ""
    end: str = ""
    items: list = field(default_factory=list)


def parse_blocks(text):
    root = Block("")
    stack = [root]
    for raw in unfold(text):
        line = parse_line(raw)
        if line.name == "BEGIN":
            block = Block(line.value.strip().upper(), raw)
            stack[-1].items.append(block)
            stack.append(block)
        elif line.name == "END" and len(stack) > 1:
            stack[-1].end = raw
            stack.pop()
        else:
            stack[-1].items.append(raw)
    return root


def render_blocks(block):
    lines = []
    for item in block.items:
        if isinstance(item, Block):
            lines.append(fold_line(item.begin))
            lines.extend(render_blocks(item))
            lines.append(fold_line(item.end or f"END:{item.name}"))
        else:
            lines.append(fold_line(item))
    return lines


def render_document(root):
    return "\r\n".join(render_blocks(root)) + "\r\n"


def is_override(block):
    return any(isinstance(item, str) and parse_line(item).name == "RECURRENCE-ID" for item in block.items)


def find_component(block, name):
    candidates = []
    for item in block.items:
        if isinstance(item, Block):
            if item.name == name:
                candidates.append(item)
            else:
                found = find_component(item, name)
                if found is not None:
                    candidates.append(found)
    masters = [candidate for candidate in candidates if not is_override(candidate)]
    return (masters or candidates or [None])[0]


def line_group(raw):
    head = raw.split(":", 1)[0].split(";", 1)[0]
    return head.split(".", 1)[0].upper() if "." in head else ""


def moment_of(raw, date_only=False):
    from .icalendar import parse_moment
    line = parse_line(raw)
    try:
        moment = parse_moment(line)
    except (ValueError, IndexError):
        return None
    if isinstance(moment, datetime):
        if date_only:
            return ("date", moment.astimezone().date().isoformat())
        return ("datetime", moment.timestamp())
    if isinstance(moment, date):
        return ("date", moment.isoformat())
    return None


def drop_orphaned_groups(items):
    groups = {}
    for item in items:
        if isinstance(item, str) and line_group(item):
            name = parse_line(item).name
            groups.setdefault(line_group(item), set()).add(name)
    orphaned = {group for group, names in groups.items() if names <= {"X-ABLABEL"}}
    return [item for item in items if not (isinstance(item, str) and line_group(item) in orphaned)]


def same_moment(previous, generated, date_only):
    previous_moment = moment_of(previous, date_only)
    return previous_moment is not None and previous_moment == moment_of(generated, date_only)


def merge_component(existing_text, generated_text, component_name, managed_names, managed_children=(), kept_names=("UID",),
                    date_only_names=()):
    if not existing_text:
        return generated_text
    existing_root = parse_blocks(existing_text)
    generated_root = parse_blocks(generated_text)
    target = find_component(existing_root, component_name)
    source = find_component(generated_root, component_name)
    if target is None or source is None:
        return generated_text
    managed = set(managed_names)
    existing_lines = {}
    for item in target.items:
        if isinstance(item, str):
            existing_lines.setdefault(parse_line(item).name, []).append(item)
    kept = []
    for item in target.items:
        if isinstance(item, Block):
            if item.name not in managed_children:
                kept.append(item)
            continue
        name = parse_line(item).name
        if name not in managed or name in kept_names:
            kept.append(item)
    added = []
    for item in source.items:
        if isinstance(item, Block):
            if item.name in managed_children:
                added.append(item)
            continue
        name = parse_line(item).name
        if name not in managed or (name in kept_names and name in existing_lines):
            continue
        previous = existing_lines.get(name, [])
        if name in MOMENT_NAMES and len(previous) == 1 and same_moment(previous[0], item, name in date_only_names):
            added.append(previous[0])
        else:
            added.append(item)
    target.items = drop_orphaned_groups(kept + added)
    return render_document(existing_root)
