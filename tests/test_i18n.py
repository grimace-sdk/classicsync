import ast
import gettext
import importlib
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools" / "i18n"
sys.path.insert(0, str(TOOLS))

compile_catalogs = importlib.import_module("compile_catalogs")
extract_messages = importlib.import_module("extract_messages")

PO_TEXT = '''msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\\n"

msgid "Connected"
msgstr "Verbunden"

msgid "%d object"
msgid_plural "%d objects"
msgstr[0] "%d Objekt"
msgstr[1] "%d Objekte"

msgctxt "menu"
msgid "&File"
msgstr "&Datei"

#, fuzzy
msgid "Disconnected"
msgstr "Getrennt"

msgid "Long "
"line"
msgstr "Lange "
"Zeile"
'''


def test_compiled_catalog_round_trips_through_gettext(tmp_path):
    po_path = tmp_path / "classicsync.po"
    po_path.write_text(PO_TEXT, encoding="utf-8")
    mo_path = tmp_path / "classicsync.mo"
    compile_catalogs.compile_catalog(po_path, mo_path)
    with mo_path.open("rb") as handle:
        translations = gettext.GNUTranslations(handle)
    assert translations.gettext("Connected") == "Verbunden"
    assert translations.ngettext("%d object", "%d objects", 1) == "%d Objekt"
    assert translations.ngettext("%d object", "%d objects", 3) == "%d Objekte"
    assert translations.pgettext("menu", "&File") == "&Datei"
    assert translations.gettext("Disconnected") == "Disconnected"
    assert translations.gettext("Long line") == "Lange Zeile"


def test_extractor_finds_marked_strings(tmp_path):
    source = tmp_path / "sample.py"
    source.write_text('from classicsync.i18n import _, ngettext, pgettext\n'
                      'a = _("Hello")\n'
                      'b = ngettext("%d file", "%d files", 2)\n'
                      'c = pgettext("tray", "E&xit")\n'
                      'd = _(variable)\n', encoding="utf-8")
    found = extract_messages.extract_file(source)
    assert (None, "Hello", None, 2) in found
    assert (None, "%d file", "%d files", 3) in found
    assert ("tray", "E&xit", None, 4) in found
    assert len(found) == 3


def test_untranslated_language_falls_back_to_english():
    from classicsync import i18n
    i18n.set_language("xx")
    assert i18n._("Connected") == "Connected"
    assert i18n.ngettext("%d object", "%d objects", 2) == "%d objects"
    i18n.set_language()


GUI_SOURCE = Path(__file__).resolve().parents[1] / "src" / "classicsync" / "gui"
GUI_EXCLUDED = {"common/plugin_settings.py"}
UI_METHODS = {
    "SetLabel", "SetLabelText", "SetTitle", "SetStatusText", "SetToolTip", "SetHelpText", "Append", "AppendCheckItem",
    "AppendRadioItem", "AppendSubMenu", "Insert", "InsertItem", "SetItem", "AddTool", "SetToolLongHelp",
    "SetToolShortHelp", "InsertColumn", "AppendColumn", "AddPage", "SetPageText", "MessageBox", "ShowBalloon",
    "SetValue", "SetHint", "WriteText",
}
UI_FUNCTIONS = {"place", "MessageBox"}
UI_KEYWORDS = {"label", "title", "caption", "message", "choices", "tooltip", "help", "text"}
ALLOWED_LITERALS = set()


def has_letters(text):
    return any(character.isalpha() for character in text)


def literal_texts(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if has_letters(node.value) and not node.value.startswith("\t"):
            yield node.value
    elif isinstance(node, ast.JoinedStr):
        parts = [value.value for value in node.values if isinstance(value, ast.Constant)]
        if has_letters("".join(parts)):
            yield ast.unparse(node)
    elif isinstance(node, ast.BinOp):
        yield from literal_texts(node.left)
        yield from literal_texts(node.right)
    elif isinstance(node, ast.IfExp):
        yield from literal_texts(node.body)
        yield from literal_texts(node.orelse)
    elif isinstance(node, (ast.List, ast.Tuple)):
        for element in node.elts:
            yield from literal_texts(element)
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        yield from literal_texts(node.func.value)


def is_wx_call(function):
    while isinstance(function, ast.Attribute):
        function = function.value
    return isinstance(function, ast.Name) and function.id == "wx"


def is_user_interface_call(call):
    function = call.func
    if isinstance(function, ast.Name):
        return function.id in UI_FUNCTIONS
    if isinstance(function, ast.Attribute):
        if function.attr in UI_METHODS or is_wx_call(function):
            return True
        return function.attr == "__init__" and isinstance(function.value, ast.Call)
    return False


def unwrapped_literals(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not is_user_interface_call(node):
            continue
        arguments = list(node.args) + [keyword.value for keyword in node.keywords if keyword.arg in UI_KEYWORDS]
        for argument in arguments:
            found.extend((node.lineno, text) for text in literal_texts(argument))
    return found


def gui_modules():
    return sorted(path for path in GUI_SOURCE.rglob("*.py") if path.relative_to(GUI_SOURCE).as_posix() not in GUI_EXCLUDED)


@pytest.mark.parametrize("path", gui_modules(), ids=lambda path: path.relative_to(GUI_SOURCE).as_posix())
def test_gui_strings_are_marked_for_translation(path):
    relative = path.relative_to(GUI_SOURCE).as_posix()
    unwrapped = [(line, text) for line, text in unwrapped_literals(path) if (relative, text) not in ALLOWED_LITERALS]
    assert unwrapped == []


SOURCE = Path(__file__).resolve().parents[1] / "src" / "classicsync"
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def scope_nodes(scope):
    pending = list(ast.iter_child_nodes(scope))
    while pending:
        node = pending.pop()
        yield node
        if not isinstance(node, SCOPES + COMPREHENSIONS + (ast.ClassDef,)):
            pending.extend(ast.iter_child_nodes(node))


def binds_and_calls_underscore(scope):
    nodes = list(scope_nodes(scope))
    arguments = scope.args.args + scope.args.kwonlyargs + scope.args.posonlyargs if isinstance(scope, SCOPES) else []
    binds = any(argument.arg == "_" for argument in arguments) or any(
        isinstance(node, ast.Name) and node.id == "_" and isinstance(node.ctx, ast.Store) for node in nodes)
    calls = any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_" for node in nodes)
    return binds and calls


def test_translation_function_is_not_shadowed():
    shadowed = []
    for path in sorted(SOURCE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, SCOPES + COMPREHENSIONS) and binds_and_calls_underscore(node):
                shadowed.append(f"{path.relative_to(SOURCE)}:{node.lineno}")
    assert shadowed == []
