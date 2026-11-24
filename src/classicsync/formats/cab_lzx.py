FRAME_SIZE = 32768
MINIMUM_MATCH = 2
LITERAL_COUNT = 256
PRETREE_SYMBOLS = 20
LENGTH_SYMBOLS = 249
ALIGNED_SYMBOLS = 8
TABLE_BITS = 16

BLOCK_VERBATIM = 1
BLOCK_ALIGNED = 2
BLOCK_UNCOMPRESSED = 3

POSITION_SLOTS = {15: 30, 16: 32, 17: 34, 18: 36, 19: 38, 20: 42, 21: 50}


def build_position_tables():
    extra_bits = []
    bits = 0
    for slot in range(0, 52, 2):
        extra_bits.extend([bits, bits])
        if slot != 0 and bits < 17:
            bits += 1
    position_base = []
    base = 0
    for extra in extra_bits:
        position_base.append(base)
        base += 1 << extra
    return extra_bits, position_base


EXTRA_BITS, POSITION_BASE = build_position_tables()


class LzxError(Exception):
    pass


def build_decode_table(lengths):
    table = [0] * (1 << TABLE_BITS)
    code = 0
    for bit_length in range(1, TABLE_BITS + 1):
        span = 1 << (TABLE_BITS - bit_length)
        for symbol, length in enumerate(lengths):
            if length != bit_length:
                continue
            start = code * span
            if start + span > len(table):
                raise LzxError("oversubscribed Huffman table")
            table[start:start + span] = [(symbol << 5) | bit_length] * span
            code += 1
        code <<= 1
    return table


class BitReader:
    def __init__(self, data):
        self.data = data
        self.position = 0
        self.buffer = 0
        self.bits_left = 0

    def fill(self, needed):
        data = self.data
        while self.bits_left < needed:
            position = self.position
            if position + 1 < len(data):
                word = data[position] | (data[position + 1] << 8)
            else:
                word = 0
            self.position = position + 2
            self.buffer = ((self.buffer << 16) | word) & 0xFFFFFFFFFFFF
            self.bits_left += 16

    def read(self, count):
        if count == 0:
            return 0
        if self.bits_left < count:
            self.fill(count)
        self.bits_left -= count
        return (self.buffer >> self.bits_left) & ((1 << count) - 1)

    def decode(self, table):
        if self.bits_left < TABLE_BITS:
            self.fill(TABLE_BITS)
        entry = table[(self.buffer >> (self.bits_left - TABLE_BITS)) & 0xFFFF]
        length = entry & 31
        if length == 0:
            raise LzxError("invalid Huffman code")
        self.bits_left -= length
        return entry >> 5

    def align_to_word(self):
        self.bits_left -= self.bits_left & 15

    def align_for_uncompressed(self):
        buffered_words = self.bits_left // 16
        if self.bits_left % 16 == 0:
            buffered_words -= 1
        self.position -= 2 * buffered_words
        self.bits_left = 0
        self.buffer = 0

    def read_byte(self):
        value = self.data[self.position]
        self.position += 1
        return value

    def read_bytes(self, count):
        chunk = self.data[self.position:self.position + count]
        self.position += count
        return chunk


class LzxDecoder:
    def __init__(self, window_bits):
        if window_bits not in POSITION_SLOTS:
            raise LzxError(f"unsupported LZX window size: 2^{window_bits}")
        self.main_symbols = LITERAL_COUNT + POSITION_SLOTS[window_bits] * 8
        self.main_lengths = [0] * self.main_symbols
        self.length_lengths = [0] * LENGTH_SYMBOLS
        self.main_table = None
        self.length_table = None
        self.aligned_table = None
        self.output = bytearray()
        self.repeats = [1, 1, 1]
        self.header_read = False
        self.intel_file_size = 0
        self.intel_started = False
        self.block_type = 0
        self.block_remaining = 0
        self.block_length = 0
        self.frame_index = 0

    def read_lengths(self, reader, lengths, first, last):
        pretree_lengths = [reader.read(4) for _ in range(PRETREE_SYMBOLS)]
        pretree = build_decode_table(pretree_lengths)
        index = first
        while index < last:
            symbol = reader.decode(pretree)
            if symbol == 17:
                run = min(reader.read(4) + 4, last - index)
                lengths[index:index + run] = [0] * run
                index += run
            elif symbol == 18:
                run = min(reader.read(5) + 20, last - index)
                lengths[index:index + run] = [0] * run
                index += run
            elif symbol == 19:
                run = min(reader.read(1) + 4, last - index)
                symbol = reader.decode(pretree)
                value = (lengths[index] - symbol) % 17
                lengths[index:index + run] = [value] * run
                index += run
            else:
                lengths[index] = (lengths[index] - symbol) % 17
                index += 1

    def read_block_header(self, reader):
        if self.block_type == BLOCK_UNCOMPRESSED and self.block_length & 1:
            reader.read_byte()
        self.block_type = reader.read(3)
        self.block_length = (reader.read(16) << 8) | reader.read(8)
        self.block_remaining = self.block_length
        if self.block_type == BLOCK_ALIGNED:
            aligned_lengths = [reader.read(3) for _ in range(ALIGNED_SYMBOLS)]
            self.aligned_table = build_decode_table(aligned_lengths)
        if self.block_type in (BLOCK_VERBATIM, BLOCK_ALIGNED):
            self.read_lengths(reader, self.main_lengths, 0, LITERAL_COUNT)
            self.read_lengths(reader, self.main_lengths, LITERAL_COUNT, self.main_symbols)
            self.main_table = build_decode_table(self.main_lengths)
            if self.main_lengths[0xE8]:
                self.intel_started = True
            self.read_lengths(reader, self.length_lengths, 0, LENGTH_SYMBOLS)
            self.length_table = build_decode_table(self.length_lengths)
        elif self.block_type == BLOCK_UNCOMPRESSED:
            self.intel_started = True
            reader.align_for_uncompressed()
            repeats = reader.read_bytes(12)
            self.repeats = [int.from_bytes(repeats[offset:offset + 4], "little") for offset in (0, 4, 8)]
        else:
            raise LzxError(f"bad LZX block type {self.block_type}")

    def decode_compressed(self, reader, frame_end):
        output = self.output
        main_table = self.main_table
        length_table = self.length_table
        aligned_table = self.aligned_table
        aligned = self.block_type == BLOCK_ALIGNED
        repeat0, repeat1, repeat2 = self.repeats
        remaining = self.block_remaining
        while remaining > 0 and len(output) < frame_end:
            symbol = reader.decode(main_table)
            if symbol < LITERAL_COUNT:
                output.append(symbol)
                remaining -= 1
                continue
            symbol -= LITERAL_COUNT
            match_length = symbol & 7
            if match_length == 7:
                match_length += reader.decode(length_table)
            match_length += MINIMUM_MATCH
            slot = symbol >> 3
            if slot > 2:
                if slot == 3:
                    match_offset = 1
                else:
                    extra = EXTRA_BITS[slot]
                    match_offset = POSITION_BASE[slot] - 2
                    if not aligned:
                        match_offset += reader.read(extra)
                    elif extra > 3:
                        match_offset += reader.read(extra - 3) << 3
                        match_offset += reader.decode(aligned_table)
                    elif extra == 3:
                        match_offset += reader.decode(aligned_table)
                    else:
                        match_offset += reader.read(extra)
                repeat2 = repeat1
                repeat1 = repeat0
                repeat0 = match_offset
            elif slot == 0:
                match_offset = repeat0
            elif slot == 1:
                match_offset = repeat1
                repeat1 = repeat0
                repeat0 = match_offset
            else:
                match_offset = repeat2
                repeat2 = repeat0
                repeat0 = match_offset
            start = len(output) - match_offset
            if start < 0:
                raise LzxError("match offset before start of output")
            if match_offset >= match_length:
                output += output[start:start + match_length]
            else:
                for index in range(match_length):
                    output.append(output[start + index])
            remaining -= match_length
        self.repeats = [repeat0, repeat1, repeat2]
        self.block_remaining = remaining

    def decode_uncompressed(self, reader, frame_end):
        count = min(self.block_remaining, frame_end - len(self.output))
        chunk = reader.read_bytes(count)
        if len(chunk) != count:
            raise LzxError("uncompressed block runs past end of input")
        self.output += chunk
        self.block_remaining -= count

    def decompress(self, compressed, uncompressed_size):
        reader = BitReader(compressed)
        if not self.header_read:
            if reader.read(1):
                high = reader.read(16)
                low = reader.read(16)
                self.intel_file_size = (high << 16) | low
            self.header_read = True
        frame_start = len(self.output)
        frame_end = frame_start + uncompressed_size
        while len(self.output) < frame_end:
            if self.block_remaining <= 0:
                self.read_block_header(reader)
            if self.block_type == BLOCK_UNCOMPRESSED:
                self.decode_uncompressed(reader, frame_end)
            else:
                self.decode_compressed(reader, frame_end)
        if len(self.output) != frame_end:
            raise LzxError("LZX frame overran its expected size")
        reader.align_to_word()
        frame = bytes(self.output[frame_start:frame_end])
        frame = self.translate_intel_calls(frame, frame_start)
        self.frame_index += 1
        return frame

    def translate_intel_calls(self, frame, frame_start):
        if not (self.intel_started and self.intel_file_size and self.frame_index < 32768 and len(frame) > 10):
            return frame
        file_size = self.intel_file_size
        translated = bytearray(frame)
        scan_end = len(frame) - 10
        index = translated.find(0xE8, 0, scan_end)
        while index >= 0:
            current_position = frame_start + index
            absolute = int.from_bytes(translated[index + 1:index + 5], "little", signed=True)
            if -current_position <= absolute < file_size:
                relative = absolute - current_position if absolute >= 0 else absolute + file_size
                translated[index + 1:index + 5] = (relative & 0xFFFFFFFF).to_bytes(4, "little")
            index = translated.find(0xE8, index + 5, scan_end)
        return bytes(translated)


def decompress_lzx_folder(blocks, window_bits):
    decoder = LzxDecoder(window_bits)
    return b"".join(decoder.decompress(block, uncompressed_size) for block, uncompressed_size in blocks)
