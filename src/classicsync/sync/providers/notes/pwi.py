import re
import struct

PWI_SIGNATURE = b"{\\pwi"
PARAGRAPH_RECORD = re.compile(rb"A\x00(..)(..)(..)(..)\x01\x00", re.DOTALL)
STREAM_OFFSET = 30
PARAGRAPH_END = 0xC4
WIDE_CHARACTER = 0xC0
THREE_BYTE_CODES = frozenset((0xE5, 0xE6, 0xE7, 0xE8, 0xE9))
TWO_BYTE_CODES = frozenset((0xEA, 0xEB, 0xEC))
KANA_BASE = 0x2F80
KANA_PAGE_SIZE = 0x40
MOST_UNKNOWN_BYTES = 2


def is_pwi(data):
    return data.startswith(PWI_SIGNATURE)


def decode_paragraph(stream):
    characters = []
    unknown = 0
    index = 0
    while index < len(stream):
        byte = stream[index]
        if byte == PARAGRAPH_END:
            return "".join(characters), unknown
        following = stream[index + 1] if index + 1 < len(stream) else None
        if 0x80 <= byte < 0xC0 and following is not None and 0xC0 <= following <= 0xC3:
            characters.append(chr(KANA_BASE + (following - 0xC0) * KANA_PAGE_SIZE + byte))
            index += 2
        elif byte == WIDE_CHARACTER and index + 2 < len(stream):
            characters.append(chr(stream[index + 1] | stream[index + 2] << 8))
            index += 3
        elif byte in THREE_BYTE_CODES:
            index += 3
        elif byte in TWO_BYTE_CODES:
            index += 2
        elif 0x20 <= byte < 0x7F or byte == 0x09:
            characters.append(chr(byte))
            index += 1
        else:
            unknown += 1
            index += 1
    return None, unknown


def pwi_paragraphs(data):
    if not is_pwi(data):
        raise ValueError("not an InkWriter or Notes file")
    paragraphs = []
    for match in PARAGRAPH_RECORD.finditer(data):
        start = match.start()
        length = struct.unpack_from("<H", data, start + 8)[0]
        stream = data[start + STREAM_OFFSET:start + STREAM_OFFSET + length]
        if len(stream) < length:
            continue
        text, unknown = decode_paragraph(stream)
        if text is None or unknown > MOST_UNKNOWN_BYTES or unknown * 4 > length:
            continue
        paragraphs.append(text.rstrip())
    while paragraphs and not paragraphs[0]:
        paragraphs.pop(0)
    while paragraphs and not paragraphs[-1]:
        paragraphs.pop()
    return paragraphs


def pwi_text(data):
    return "\n".join(pwi_paragraphs(data))
