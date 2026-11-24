import struct


def encode_wide(text):
    return text.encode("utf-16-le") + b"\0\0"


def decode_wide(data):
    text = bytes(data).decode("utf-16-le", errors="replace")
    end = text.find("\0")
    return text if end < 0 else text[:end]


class Request:
    def __init__(self, command):
        self.command = command
        self.parts = [struct.pack("<I", command)]

    def u32(self, value):
        self.parts.append(struct.pack("<I", value & 0xFFFFFFFF))
        return self

    def u16(self, value):
        self.parts.append(struct.pack("<H", value & 0xFFFF))
        return self

    def raw(self, data):
        self.parts.append(bytes(data))
        return self

    def string(self, text):
        if text is None:
            return self.u32(0)
        encoded = encode_wide(text)
        return self.u32(1).u32(len(encoded) // 2).raw(encoded)

    def buffer(self, data):
        if data is None:
            return self.u32(0)
        return self.u32(1).u32(len(data)).u32(1).raw(data)

    def wide_buffer(self, text):
        return self.buffer(None if text is None else encode_wide(text))

    def u32_buffer(self, value):
        return self.buffer(struct.pack("<I", value))

    def out_buffer(self, size):
        return self.u32(1).u32(size).u32(0)

    def null(self):
        return self.u32(0)

    def build(self):
        body = b"".join(self.parts)
        return struct.pack("<I", len(body)) + body


class Reply:
    def __init__(self, data):
        self.data = bytes(data)
        self.offset = 0

    @property
    def remaining(self):
        return len(self.data) - self.offset

    def take(self, size):
        if self.offset + size > len(self.data):
            raise ValueError(f"short RAPI reply: wanted {size} bytes at {self.offset}, have {len(self.data)}")
        chunk = self.data[self.offset:self.offset + size]
        self.offset += size
        return chunk

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def i32(self):
        return struct.unpack("<i", self.take(4))[0]

    def u16(self):
        return struct.unpack("<H", self.take(2))[0]

    def out_buffer(self):
        present = self.u32()
        if not present:
            return None
        size = self.u32()
        has_data = self.u32()
        if not has_data:
            return None
        return self.take(size)

    def out_u32(self, default=0):
        data = self.out_buffer()
        return struct.unpack("<I", data[:4])[0] if data and len(data) >= 4 else default
