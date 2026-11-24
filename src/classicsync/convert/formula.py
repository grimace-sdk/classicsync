import re
import struct

from .errors import ConversionError
from .workbook import ERROR_CODES, ERROR_VALUES, column_letters, column_number

BINARY_OPERATORS = {0x03: "+", 0x04: "-", 0x05: "*", 0x06: "/", 0x07: "^", 0x08: "&", 0x09: "<", 0x0A: "<=",
                    0x0B: "=", 0x0C: ">=", 0x0D: ">", 0x0E: "<>", 0x0F: " ", 0x10: ",", 0x11: ":"}
OPERATOR_TOKENS = {text: token for token, text in BINARY_OPERATORS.items() if text not in (" ", ",")}
PRECEDENCE = {"=": 1, "<": 1, ">": 1, "<=": 1, ">=": 1, "<>": 1, "&": 2, "+": 3, "-": 3, "*": 4, "/": 4, "^": 5}
UNARY_PRECEDENCE = 6
VARIABLE = None
FUNCTIONS = {
    "COUNT": (0, 0, VARIABLE), "IF": (1, 2, 3), "ISNA": (2, 1, 1), "ISERROR": (3, 1, 1), "SUM": (4, 0, VARIABLE),
    "AVERAGE": (5, 1, VARIABLE), "MIN": (6, 1, VARIABLE), "MAX": (7, 1, VARIABLE), "ROW": (8, 0, 1),
    "COLUMN": (9, 0, 1), "NA": (10, 0, 0), "NPV": (11, 2, VARIABLE), "STDEV": (12, 1, VARIABLE),
    "DOLLAR": (13, 1, 2), "FIXED": (14, 1, 3), "SIN": (15, 1, 1), "COS": (16, 1, 1), "TAN": (17, 1, 1),
    "ATAN": (18, 1, 1), "PI": (19, 0, 0), "SQRT": (20, 1, 1), "EXP": (21, 1, 1), "LN": (22, 1, 1),
    "LOG10": (23, 1, 1), "ABS": (24, 1, 1), "INT": (25, 1, 1), "SIGN": (26, 1, 1), "ROUND": (27, 2, 2),
    "LOOKUP": (28, 2, 3), "INDEX": (29, 2, 4), "REPT": (30, 2, 2), "MID": (31, 3, 3), "LEN": (32, 1, 1),
    "VALUE": (33, 1, 1), "TRUE": (34, 0, 0), "FALSE": (35, 0, 0), "AND": (36, 1, VARIABLE), "OR": (37, 1, VARIABLE),
    "NOT": (38, 1, 1), "MOD": (39, 2, 2), "DCOUNT": (40, 3, 3), "DSUM": (41, 3, 3), "DAVERAGE": (42, 3, 3),
    "DMIN": (43, 3, 3), "DMAX": (44, 3, 3), "DSTDEV": (45, 3, 3), "VAR": (46, 1, VARIABLE), "DVAR": (47, 3, 3),
    "TEXT": (48, 2, 2), "PV": (56, 3, 5), "FV": (57, 3, 5), "NPER": (58, 3, 5), "PMT": (59, 3, 5),
    "RATE": (60, 3, 6), "MIRR": (61, 3, 3), "IRR": (62, 1, 2), "RAND": (63, 0, 0), "MATCH": (64, 2, 3),
    "DATE": (65, 3, 3), "TIME": (66, 3, 3), "DAY": (67, 1, 1), "MONTH": (68, 1, 1), "YEAR": (69, 1, 1),
    "WEEKDAY": (70, 1, 2), "HOUR": (71, 1, 1), "MINUTE": (72, 1, 1), "SECOND": (73, 1, 1), "NOW": (74, 0, 0),
    "AREAS": (75, 1, 1), "ROWS": (76, 1, 1), "COLUMNS": (77, 1, 1), "OFFSET": (78, 3, 5), "SEARCH": (82, 2, 3),
    "TRANSPOSE": (83, 1, 1), "TYPE": (86, 1, 1), "ATAN2": (97, 2, 2), "ASIN": (98, 1, 1), "ACOS": (99, 1, 1),
    "CHOOSE": (100, 2, VARIABLE), "HLOOKUP": (101, 3, 4), "VLOOKUP": (102, 3, 4), "ISREF": (105, 1, 1),
    "LOG": (109, 1, 2), "CHAR": (111, 1, 1), "LOWER": (112, 1, 1), "UPPER": (113, 1, 1), "PROPER": (114, 1, 1),
    "LEFT": (115, 1, 2), "RIGHT": (116, 1, 2), "EXACT": (117, 2, 2), "TRIM": (118, 1, 1), "REPLACE": (119, 4, 4),
    "SUBSTITUTE": (120, 3, 4), "CODE": (121, 1, 1), "FIND": (124, 2, 3), "CELL": (125, 1, 2), "ISERR": (126, 1, 1),
    "ISTEXT": (127, 1, 1), "ISNUMBER": (128, 1, 1), "ISBLANK": (129, 1, 1), "T": (130, 1, 1), "N": (131, 1, 1),
    "DATEVALUE": (140, 1, 1), "TIMEVALUE": (141, 1, 1), "SLN": (142, 3, 3), "SYD": (143, 4, 4),
    "DDB": (144, 4, 5), "INDIRECT": (148, 1, 2), "CLEAN": (162, 1, 1), "MDETERM": (163, 1, 1),
    "MINVERSE": (164, 1, 1), "MMULT": (165, 2, 2), "IPMT": (167, 4, 6), "PPMT": (168, 4, 6),
    "COUNTA": (169, 0, VARIABLE), "PRODUCT": (183, 0, VARIABLE), "FACT": (184, 1, 1), "DPRODUCT": (189, 3, 3),
    "ISNONTEXT": (190, 1, 1), "STDEVP": (193, 1, VARIABLE), "VARP": (194, 1, VARIABLE), "DSTDEVP": (195, 3, 3),
    "DVARP": (196, 3, 3), "TRUNC": (197, 1, 2), "ISLOGICAL": (198, 1, 1), "DCOUNTA": (199, 3, 3),
    "ROUNDUP": (212, 2, 2), "ROUNDDOWN": (213, 2, 2), "RANK": (216, 2, 3), "ADDRESS": (219, 2, 5),
    "DAYS360": (220, 2, 3), "TODAY": (221, 0, 0), "VDB": (222, 5, 7), "MEDIAN": (227, 1, VARIABLE),
    "SUMPRODUCT": (228, 1, VARIABLE), "SINH": (229, 1, 1), "COSH": (230, 1, 1), "TANH": (231, 1, 1),
    "ASINH": (232, 1, 1), "ACOSH": (233, 1, 1), "ATANH": (234, 1, 1), "DGET": (235, 3, 3), "DB": (247, 4, 5),
    "FREQUENCY": (252, 2, 2), "AVEDEV": (269, 1, VARIABLE), "COMBIN": (276, 2, 2), "EVEN": (279, 1, 1),
    "FLOOR": (285, 2, 2), "CEILING": (288, 2, 2), "ODD": (298, 1, 1), "PERMUT": (299, 2, 2),
    "DEVSQ": (318, 1, VARIABLE), "GEOMEAN": (319, 1, VARIABLE), "HARMEAN": (320, 1, VARIABLE),
    "SUMSQ": (321, 0, VARIABLE), "LARGE": (325, 2, 2), "SMALL": (326, 2, 2), "MODE": (330, 1, VARIABLE),
    "CONCATENATE": (336, 0, VARIABLE), "POWER": (337, 2, 2), "RADIANS": (342, 1, 1), "DEGREES": (343, 1, 1),
    "SUMIF": (345, 2, 3), "COUNTIF": (346, 2, 2), "COUNTBLANK": (347, 1, 1), "ROMAN": (354, 1, 2),
}
FUNCTION_NAMES = {identifier: name for name, (identifier, _, _) in FUNCTIONS.items()}
REFERENCE_ARGUMENT_FUNCTIONS = {
    "SUM", "AVERAGE", "MIN", "MAX", "COUNT", "COUNTA", "PRODUCT", "STDEV", "STDEVP", "VAR", "VARP", "NPV", "ROW",
    "COLUMN", "ROWS", "COLUMNS", "AREAS", "INDEX", "LOOKUP", "MATCH", "VLOOKUP", "HLOOKUP", "OFFSET", "ISREF",
    "CELL", "IRR", "MIRR", "MEDIAN", "SUMPRODUCT", "AVEDEV", "DEVSQ", "GEOMEAN", "HARMEAN", "SUMSQ", "MODE",
    "LARGE", "SMALL", "RANK", "SUMIF", "COUNTIF", "COUNTBLANK", "DCOUNT", "DSUM", "DAVERAGE", "DMIN", "DMAX",
    "DSTDEV", "DVAR", "DPRODUCT", "DSTDEVP", "DVARP", "DCOUNTA", "DGET", "FREQUENCY", "MMULT", "MDETERM",
    "MINVERSE", "TRANSPOSE",
}
OPERAND_SIZES = {0x21: 2, 0x22: 3, 0x23: 14, 0x24: 3, 0x25: 6, 0x2A: 3, 0x2B: 6, 0x2C: 3, 0x2D: 6, 0x39: 24,
                 0x3A: 17, 0x3B: 20, 0x3C: 17, 0x3D: 20}
ATTRIBUTE_IF = 0x02
ATTRIBUTE_CHOOSE = 0x04
ATTRIBUTE_GOTO = 0x08
ATTRIBUTE_SUM = 0x10
TOKEN_PATTERN = re.compile(r"""
    (?P<space>\s+)
  | (?P<string>"(?:[^"]|"")*")
  | (?P<error>\#(?:NULL!|DIV/0!|VALUE!|REF!|NAME\?|NUM!|N/A))
  | (?P<reference>(?:(?:'(?:[^']|'')+'|[A-Za-z_][\w.]*)!)?\$?[A-Za-z]{1,2}\$?\d+(?::\$?[A-Za-z]{1,2}\$?\d+)?)(?![\w(])
  | (?P<number>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<function>[A-Za-z_][\w.]*)\s*\(
  | (?P<name>[A-Za-z_][\w.]*)
  | (?P<operator><=|>=|<>|[-+*/^&=<>%(),])
""", re.VERBOSE)
CELL_PATTERN = re.compile(r"(\$?)([A-Za-z]{1,2})(\$?)(\d+)")


class FormulaContext:
    def __init__(self, unicode_strings, sheet_names=(), names=()):
        self.unicode_strings = unicode_strings
        self.sheet_names = list(sheet_names)
        self.names = list(names)


def cell_text(row_word, column):
    row = row_word & 0x3FFF
    column_absolute = "" if row_word & 0x4000 else "$"
    row_absolute = "" if row_word & 0x8000 else "$"
    return f"{column_absolute}{column_letters(column)}{row_absolute}{row + 1}"


def relative_cell_text(row_word, column):
    row_offset = row_word & 0x3FFF
    if row_word & 0x8000 and row_offset & 0x2000:
        row_offset -= 0x4000
    if row_word & 0x4000 and column & 0x80:
        column -= 0x100
    return cell_text((row_word & 0xC000) | (row_offset & 0x3FFF), column & 0xFF)


def quote_sheet(name):
    if re.fullmatch(r"[A-Za-z_][\w.]*", name):
        return name
    return "'" + name.replace("'", "''") + "'"


def decode_formula(rgce, context):
    stack = []
    index = 0
    while index < len(rgce):
        token = rgce[index]
        index += 1
        if token in BINARY_OPERATORS:
            right = stack.pop()
            left = stack.pop()
            operator = BINARY_OPERATORS[token]
            stack.append(f"{left}{operator}{right}")
        elif token == 0x12:
            stack.append("+" + stack.pop())
        elif token == 0x13:
            stack.append("-" + stack.pop())
        elif token == 0x14:
            stack.append(stack.pop() + "%")
        elif token == 0x15:
            stack.append("(" + stack.pop() + ")")
        elif token == 0x16:
            stack.append("")
        elif token == 0x17:
            length = rgce[index]
            index += 1
            if context.unicode_strings:
                flags = rgce[index]
                index += 1
                if flags & 1:
                    text = rgce[index:index + length * 2].decode("utf-16-le")
                    index += length * 2
                else:
                    text = rgce[index:index + length].decode("latin-1")
                    index += length
            else:
                text = rgce[index:index + length].decode("cp1252", errors="replace")
                index += length
            stack.append('"' + text.replace('"', '""') + '"')
        elif token == 0x19:
            flags, word = rgce[index], struct.unpack_from("<H", rgce, index + 1)[0]
            index += 3
            if flags & ATTRIBUTE_CHOOSE:
                index += (word + 1) * 2
            elif flags & ATTRIBUTE_SUM:
                stack.append(f"SUM({stack.pop()})")
        elif token == 0x1C:
            stack.append(ERROR_CODES.get(rgce[index], "#VALUE!"))
            index += 1
        elif token == 0x1D:
            stack.append("TRUE" if rgce[index] else "FALSE")
            index += 1
        elif token == 0x1E:
            stack.append(str(struct.unpack_from("<H", rgce, index)[0]))
            index += 2
        elif token == 0x1F:
            value = struct.unpack_from("<d", rgce, index)[0]
            index += 8
            stack.append(f"{int(value)}" if value.is_integer() and abs(value) < 1e15 else repr(value))
        elif token >= 0x20:
            base = (token & 0x1F) | 0x20
            size = OPERAND_SIZES.get(base)
            if size is None:
                raise ConversionError(f"unsupported formula token 0x{token:02x}")
            operand = rgce[index:index + size]
            index += size
            stack.append(decode_operand(base, operand, stack, context))
        else:
            raise ConversionError(f"unsupported formula token 0x{token:02x}")
    if len(stack) != 1:
        raise ConversionError("malformed formula")
    return stack[0]


def decode_operand(base, operand, stack, context):
    if base in (0x21, 0x22):
        if base == 0x21:
            identifier = struct.unpack_from("<H", operand)[0]
            name = FUNCTION_NAMES.get(identifier)
            argument_count = FUNCTIONS[name][1] if name else 0
        else:
            argument_count = operand[0] & 0x7F
            identifier = struct.unpack_from("<H", operand, 1)[0] & 0x7FFF
            name = FUNCTION_NAMES.get(identifier)
        if name is None:
            raise ConversionError(f"unknown function number {identifier}")
        arguments = stack[len(stack) - argument_count:] if argument_count else []
        del stack[len(stack) - argument_count:]
        return f"{name}({','.join(arguments)})"
    if base == 0x23:
        index = struct.unpack_from("<H", operand)[0] - 1
        return context.names[index] if 0 <= index < len(context.names) else "#NAME?"
    if base == 0x24:
        row_word, column = struct.unpack_from("<HB", operand)
        return cell_text(row_word, column)
    if base == 0x25:
        first_row, last_row, first_column, last_column = struct.unpack_from("<HHBB", operand)
        return f"{cell_text(first_row, first_column)}:{cell_text(last_row, last_column)}"
    if base == 0x2C:
        row_word, column = struct.unpack_from("<HB", operand)
        return relative_cell_text(row_word, column)
    if base == 0x2D:
        first_row, last_row, first_column, last_column = struct.unpack_from("<HHBB", operand)
        return f"{relative_cell_text(first_row, first_column)}:{relative_cell_text(last_row, last_column)}"
    if base in (0x2A, 0x2B, 0x3C, 0x3D):
        return "#REF!"
    if base == 0x39:
        index = struct.unpack_from("<H", operand, 10)[0] - 1
        return context.names[index] if 0 <= index < len(context.names) else "#NAME?"
    if base in (0x3A, 0x3B):
        first_sheet = struct.unpack_from("<H", operand, 10)[0]
        sheet = context.sheet_names[first_sheet] if first_sheet < len(context.sheet_names) else "Sheet1"
        if base == 0x3A:
            row_word, column = struct.unpack_from("<HB", operand, 14)
            return f"{quote_sheet(sheet)}!{cell_text(row_word, column)}"
        first_row, last_row, first_column, last_column = struct.unpack_from("<HHBB", operand, 14)
        return f"{quote_sheet(sheet)}!{cell_text(first_row, first_column)}:{cell_text(last_row, last_column)}"
    raise ConversionError(f"unsupported formula token 0x{base:02x}")


def tokenize_formula(text):
    tokens = []
    position = 0
    text = text.strip()
    if text.startswith("="):
        text = text[1:]
    while position < len(text):
        match = TOKEN_PATTERN.match(text, position)
        if not match:
            raise ConversionError(f"cannot parse formula near {text[position:position + 10]!r}")
        position = match.end()
        kind = match.lastgroup
        if kind != "space":
            tokens.append((kind, match.group(kind)))
    return tokens


class FormulaParser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.position = 0

    def peek(self):
        return self.tokens[self.position] if self.position < len(self.tokens) else (None, None)

    def take(self):
        token = self.peek()
        self.position += 1
        return token

    def expect(self, value):
        kind, text = self.take()
        if text != value:
            raise ConversionError(f"expected {value!r} in formula")

    def parse(self):
        node = self.expression(0)
        if self.position != len(self.tokens):
            raise ConversionError("unexpected text at the end of the formula")
        return node

    def expression(self, minimum_precedence):
        left = self.unary()
        while True:
            kind, text = self.peek()
            if kind != "operator" or text not in PRECEDENCE or PRECEDENCE[text] < minimum_precedence:
                return left
            self.take()
            precedence = PRECEDENCE[text]
            right = self.expression(precedence if text == "^" else precedence + 1)
            left = ("binary", text, left, right)

    def unary(self):
        kind, text = self.peek()
        if kind == "operator" and text in ("-", "+"):
            self.take()
            return ("unary", text, self.expression(UNARY_PRECEDENCE))
        node = self.primary()
        while self.peek() == ("operator", "%"):
            self.take()
            node = ("percent", node)
        return node

    def primary(self):
        kind, text = self.take()
        if kind == "number":
            return ("number", float(text))
        if kind == "string":
            return ("string", text[1:-1].replace('""', '"'))
        if kind == "error":
            return ("error", text)
        if kind == "reference":
            return ("reference", text)
        if kind == "name":
            if text.upper() in ("TRUE", "FALSE"):
                return ("boolean", text.upper() == "TRUE")
            return ("name", text)
        if kind == "function":
            arguments = []
            if self.peek() == ("operator", ")"):
                self.take()
            else:
                while True:
                    if self.peek() in (("operator", ","), ("operator", ")")):
                        arguments.append(("missing",))
                    else:
                        arguments.append(self.expression(0))
                    separator = self.take()
                    if separator == ("operator", ")"):
                        break
                    if separator != ("operator", ","):
                        raise ConversionError("expected ',' or ')' in function arguments")
            return ("function", text.upper(), arguments)
        if (kind, text) == ("operator", "("):
            node = self.expression(0)
            self.expect(")")
            return ("paren", node)
        raise ConversionError(f"unexpected {text!r} in formula")


def encode_cell(text):
    match = CELL_PATTERN.fullmatch(text)
    if not match:
        raise ConversionError(f"bad cell reference {text}")
    column_absolute, letters, row_absolute, digits = match.groups()
    row = int(digits) - 1
    column = column_number(letters)
    if row > 0x3FFF or column > 0xFF:
        raise ConversionError(f"cell reference {text} is out of range")
    row_word = row | (0 if column_absolute else 0x4000) | (0 if row_absolute else 0x8000)
    return row_word, column


class FormulaEncoder:
    def __init__(self, context):
        self.context = context

    def node(self, node, reference_class):
        kind = node[0]
        if kind == "number":
            value = node[1]
            if value.is_integer() and 0 <= value <= 0xFFFF:
                return bytes((0x1E,)) + struct.pack("<H", int(value))
            return bytes((0x1F,)) + struct.pack("<d", value)
        if kind == "string":
            return self.string(node[1])
        if kind == "boolean":
            return bytes((0x1D, 1 if node[1] else 0))
        if kind == "error":
            return bytes((0x1C, ERROR_VALUES[node[1]]))
        if kind == "missing":
            return bytes((0x16,))
        if kind == "paren":
            return self.node(node[1], False) + bytes((0x15,))
        if kind == "percent":
            return self.node(node[1], False) + bytes((0x14,))
        if kind == "unary":
            return self.node(node[2], False) + bytes((0x12 if node[1] == "+" else 0x13,))
        if kind == "binary":
            return self.node(node[2], False) + self.node(node[3], False) + bytes((OPERATOR_TOKENS[node[1]],))
        if kind == "reference":
            return self.reference(node[1], reference_class)
        if kind == "name":
            upper_names = [name.upper() for name in self.context.names]
            if node[1].upper() not in upper_names:
                raise ConversionError(f"unknown name {node[1]}")
            index = upper_names.index(node[1].upper()) + 1
            return bytes((0x23 if reference_class else 0x43,)) + struct.pack("<H", index) + bytes(12)
        if kind == "function":
            return self.function(node[1], node[2])
        raise ConversionError(f"cannot encode {kind}")

    def string(self, text):
        if len(text) > 255:
            raise ConversionError("string constant longer than 255 characters")
        if self.context.unicode_strings:
            return bytes((0x17, len(text), 1)) + text.encode("utf-16-le")
        return bytes((0x17, len(text))) + text.encode("cp1252", errors="replace")

    def reference(self, text, reference_class):
        if "!" in text:
            return self.sheet_reference(text, reference_class)
        if ":" in text:
            first, last = text.split(":")
            first_row, first_column = encode_cell(first)
            last_row, last_column = encode_cell(last)
            token = 0x25 if reference_class else 0x45
            return bytes((token,)) + struct.pack("<HHBB", first_row, last_row, first_column, last_column)
        row_word, column = encode_cell(text)
        return bytes((0x24 if reference_class else 0x44,)) + struct.pack("<HB", row_word, column)

    def sheet_reference(self, text, reference_class):
        sheet, _, cells = text.rpartition("!")
        if sheet.startswith("'"):
            sheet = sheet[1:-1].replace("''", "'")
        lowered = [name.lower() for name in self.context.sheet_names]
        if sheet.lower() not in lowered:
            raise ConversionError(f"reference to unknown sheet {sheet}")
        sheet_index = lowered.index(sheet.lower())
        prefix = struct.pack("<H", 0xFFFF) + bytes(8) + struct.pack("<HH", sheet_index, sheet_index)
        if ":" in cells:
            first, last = cells.split(":")
            first_row, first_column = encode_cell(first)
            last_row, last_column = encode_cell(last)
            token = 0x3B if reference_class else 0x5B
            return bytes((token,)) + prefix + struct.pack("<HHBB", first_row, last_row, first_column, last_column)
        row_word, column = encode_cell(cells)
        return bytes((0x3A if reference_class else 0x5A,)) + prefix + struct.pack("<HB", row_word, column)

    def function(self, name, arguments):
        if name not in FUNCTIONS:
            raise ConversionError(f"function {name} is not supported by Pocket Excel")
        identifier, minimum, maximum = FUNCTIONS[name]
        if len(arguments) < minimum or (maximum is not None and len(arguments) > maximum):
            raise ConversionError(f"wrong number of arguments to {name}")
        reference_arguments = name in REFERENCE_ARGUMENT_FUNCTIONS
        encoded = [self.node(argument, reference_arguments) for argument in arguments]
        if name == "IF":
            return self.conditional(encoded)
        if name == "SUM" and len(encoded) == 1:
            return encoded[0] + bytes((0x19, ATTRIBUTE_SUM, 0, 0))
        if minimum == maximum:
            return b"".join(encoded) + bytes((0x41,)) + struct.pack("<H", identifier)
        return b"".join(encoded) + bytes((0x42, len(encoded))) + struct.pack("<H", identifier)

    def conditional(self, encoded):
        condition, when_true = encoded[0], encoded[1]
        function = bytes((0x42, len(encoded))) + struct.pack("<H", FUNCTIONS["IF"][0])
        goto_size = 4
        if len(encoded) == 2:
            return (condition + bytes((0x19, ATTRIBUTE_IF)) + struct.pack("<H", len(when_true) + goto_size) +
                    when_true + bytes((0x19, ATTRIBUTE_GOTO)) + struct.pack("<H", len(function) - 1) + function)
        when_false = encoded[2]
        return (condition + bytes((0x19, ATTRIBUTE_IF)) + struct.pack("<H", len(when_true) + goto_size) +
                when_true + bytes((0x19, ATTRIBUTE_GOTO)) +
                struct.pack("<H", len(when_false) + goto_size + len(function) - 1) +
                when_false + bytes((0x19, ATTRIBUTE_GOTO)) + struct.pack("<H", len(function) - 1) + function)


def encode_formula(text, context, reference_class=False):
    encoder = FormulaEncoder(context)
    return encoder.node(FormulaParser(tokenize_formula(text)).parse(), reference_class)


def shift_formula(text, row_offset, column_offset):
    def shift(match):
        column_absolute, letters, row_absolute, digits = match.groups()
        column = column_number(letters) + (0 if column_absolute else column_offset)
        row = int(digits) + (0 if row_absolute else row_offset)
        return f"{column_absolute}{column_letters(column)}{row_absolute}{row}"

    pieces = []
    for kind, value in tokenize_formula(text):
        if kind == "reference":
            sheet, _, cells = value.rpartition("!")
            value = (sheet + "!" if sheet else "") + CELL_PATTERN.sub(shift, cells)
        pieces.append(value + "(" if kind == "function" else value)
    return "".join(pieces)
