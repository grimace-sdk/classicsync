FLAG = 0x7E
ESCAPE = 0x7D
DEFAULT_ACCM = 0xFFFFFFFF
GOOD_FCS = 0xF0B8
HANDSHAKE_PREFIX = b"CLIENT"


def _build_fcs_table():
    table = []
    for index in range(256):
        value = index
        for _ in range(8):
            value = (value >> 1) ^ 0x8408 if value & 1 else value >> 1
        table.append(value)
    return table


FCS_TABLE = _build_fcs_table()


def fcs16(data, fcs=0xFFFF):
    for byte in data:
        fcs = (fcs >> 8) ^ FCS_TABLE[(fcs ^ byte) & 0xFF]
    return fcs


def _needs_escape(byte, accm):
    return byte == FLAG or byte == ESCAPE or (byte < 0x20 and accm & (1 << byte))


def encode_frame(payload, accm=DEFAULT_ACCM):
    fcs = fcs16(payload) ^ 0xFFFF
    body = bytes(payload) + bytes([fcs & 0xFF, fcs >> 8])
    encoded = bytearray([FLAG])
    for byte in body:
        if _needs_escape(byte, accm):
            encoded.append(ESCAPE)
            encoded.append(byte ^ 0x20)
        else:
            encoded.append(byte)
    encoded.append(FLAG)
    return bytes(encoded)


class FrameDecoder:
    def __init__(self, max_frame=4096):
        self.max_frame = max_frame
        self.buffer = bytearray()
        self.escaped = False
        self.in_frame = False
        self.discarding = False
        self.bad_frames = 0

    def reset(self):
        self.buffer.clear()
        self.escaped = False
        self.in_frame = False
        self.discarding = False

    def feed(self, data):
        frames = []
        text = bytearray()
        for byte in data:
            if byte == FLAG:
                if self.in_frame and not self.discarding and not self.escaped and self.buffer:
                    if len(self.buffer) >= 4 and fcs16(self.buffer) == GOOD_FCS:
                        frames.append(bytes(self.buffer[:-2]))
                    else:
                        self.bad_frames += 1
                self.buffer.clear()
                self.escaped = False
                self.discarding = False
                self.in_frame = True
                continue
            if not self.in_frame:
                text.append(byte)
                continue
            if byte == ESCAPE:
                self.escaped = True
                continue
            if self.escaped:
                byte ^= 0x20
                self.escaped = False
            if len(self.buffer) >= self.max_frame:
                self.discarding = True
                continue
            self.buffer.append(byte)
            if len(self.buffer) == len(HANDSHAKE_PREFIX) and self.buffer == HANDSHAKE_PREFIX:
                text += self.buffer
                self.buffer.clear()
                self.in_frame = False
        return frames, bytes(text)
