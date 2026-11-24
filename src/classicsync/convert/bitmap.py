import struct
import zlib
from dataclasses import dataclass

from .errors import ConversionError

BITMAP_FILE_HEADER_SIZE = 14
BITMAP_INFO_HEADER_SIZE = 40
BITMAP_CORE_HEADER_SIZE = 12
BI_RGB = 0
BI_BITFIELDS = 3
TWO_BIT_PALETTE = [(0, 0, 0), (0x80, 0x80, 0x80), (0xC0, 0xC0, 0xC0), (0xFF, 0xFF, 0xFF)]
EXACT_GRAY_LEVELS = {(0, 0, 0): 0, (0x55, 0x55, 0x55): 1, (0x80, 0x80, 0x80): 1, (0xAA, 0xAA, 0xAA): 2,
                     (0xFF, 0xFF, 0xFF): 3}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ADAM7_PASSES = [(0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]


@dataclass
class Bitmap:
    width: int
    height: int
    pixels: list

    def is_grayscale(self):
        return all(red == green == blue for row in self.pixels for red, green, blue in row)


def gray_level(red, green, blue):
    exact = EXACT_GRAY_LEVELS.get((red, green, blue))
    if exact is not None:
        return exact
    luminance = green * 59 + blue * 11 + red * 30
    return (luminance + 4250) * 3 // 25500


def row_stride(width, bits_per_pixel):
    return (width * bits_per_pixel + 31) // 32 * 4


def unpack_indices(row_bytes, width, bits_per_pixel):
    if bits_per_pixel == 8:
        return list(row_bytes[:width])
    per_byte = 8 // bits_per_pixel
    mask = (1 << bits_per_pixel) - 1
    indices = []
    for column in range(width):
        byte = row_bytes[column // per_byte]
        shift = 8 - bits_per_pixel * (column % per_byte + 1)
        indices.append((byte >> shift) & mask)
    return indices


def pack_indices(indices, bits_per_pixel, stride):
    packed = bytearray(stride)
    per_byte = 8 // bits_per_pixel
    for column, index in enumerate(indices):
        shift = 8 - bits_per_pixel * (column % per_byte + 1)
        packed[column // per_byte] |= index << shift
    return bytes(packed)


def mask_shift_and_scale(mask):
    if mask == 0:
        return 0, 0
    shift = 0
    while not (mask >> shift) & 1:
        shift += 1
    return shift, (mask >> shift)


def read_dib(data, offset=0, pixel_offset=None):
    header_size = struct.unpack_from("<I", data, offset)[0]
    if header_size == BITMAP_CORE_HEADER_SIZE:
        width, height, planes, bits_per_pixel = struct.unpack_from("<HHHH", data, offset + 4)
        compression, colours_used, palette_entry_size = BI_RGB, 0, 3
    elif header_size >= BITMAP_INFO_HEADER_SIZE:
        width, height, planes, bits_per_pixel, compression, _, _, _, colours_used = struct.unpack_from(
            "<iiHHIIiiI", data, offset + 4)
        palette_entry_size = 4
    else:
        raise ConversionError(f"unsupported bitmap header size {header_size}")
    if compression not in (BI_RGB, BI_BITFIELDS):
        raise ConversionError("compressed bitmaps are not supported")
    if bits_per_pixel not in (1, 2, 4, 8, 16, 24, 32):
        raise ConversionError(f"unsupported bitmap depth {bits_per_pixel}")
    top_down = height < 0
    height = abs(height)
    position = offset + header_size
    masks = None
    if compression == BI_BITFIELDS:
        if header_size == BITMAP_INFO_HEADER_SIZE:
            masks = struct.unpack_from("<III", data, position)
            position += 12
        else:
            masks = struct.unpack_from("<III", data, offset + 40)
    elif bits_per_pixel == 16:
        masks = (0x7C00, 0x03E0, 0x001F)
    elif bits_per_pixel == 32:
        masks = (0xFF0000, 0x00FF00, 0x0000FF)
    palette = []
    if bits_per_pixel <= 8:
        count = colours_used or (1 << bits_per_pixel)
        for index in range(count):
            blue, green, red = data[position + index * palette_entry_size:position + index * palette_entry_size + 3]
            palette.append((red, green, blue))
        position += count * palette_entry_size
    if pixel_offset is not None:
        position = pixel_offset
    stride = row_stride(width, bits_per_pixel)
    if position + stride * height > len(data):
        raise ConversionError("bitmap pixel data is truncated")
    rows = []
    for stored_row in range(height):
        row_bytes = data[position + stored_row * stride:position + (stored_row + 1) * stride]
        rows.append(decode_row(row_bytes, width, bits_per_pixel, palette, masks))
    if not top_down:
        rows.reverse()
    return Bitmap(width, height, rows), bits_per_pixel, palette


def decode_row(row_bytes, width, bits_per_pixel, palette, masks):
    if bits_per_pixel <= 8:
        black = (0, 0, 0)
        return [palette[index] if index < len(palette) else black
                for index in unpack_indices(row_bytes, width, bits_per_pixel)]
    if bits_per_pixel == 24:
        return [(row_bytes[column * 3 + 2], row_bytes[column * 3 + 1], row_bytes[column * 3])
                for column in range(width)]
    sample_size = bits_per_pixel // 8
    channels = [mask_shift_and_scale(mask) for mask in masks]
    row = []
    for column in range(width):
        value = int.from_bytes(row_bytes[column * sample_size:(column + 1) * sample_size], "little")
        colour = []
        for (shift, maximum), mask in zip(channels, masks):
            colour.append(((value & mask) >> shift) * 255 // maximum if maximum else 0)
        row.append(tuple(colour))
    return row


def read_bmp(data):
    if data[:2] != b"BM":
        raise ConversionError("not a BMP file")
    pixel_offset = struct.unpack_from("<I", data, 10)[0]
    bitmap, _, _ = read_dib(data, BITMAP_FILE_HEADER_SIZE, pixel_offset or None)
    return bitmap


def build_dib(width, height, bits_per_pixel, palette, stored_rows):
    stride = row_stride(width, bits_per_pixel)
    header = struct.pack("<IiiHHIIiiII", BITMAP_INFO_HEADER_SIZE, width, height, 1, bits_per_pixel, BI_RGB,
                         stride * height, 3780, 3780, 0, 0)
    palette_bytes = b"".join(bytes((blue, green, red, 0)) for red, green, blue in palette)
    return header + palette_bytes + b"".join(stored_rows)


def wrap_dib(dib, palette_length):
    pixel_offset = BITMAP_FILE_HEADER_SIZE + BITMAP_INFO_HEADER_SIZE + palette_length * 4
    return b"BM" + struct.pack("<IHHI", BITMAP_FILE_HEADER_SIZE + len(dib), 0, 0, pixel_offset) + dib


def indexed_dib(bitmap, palette, bits_per_pixel, index_for_colour):
    stride = row_stride(bitmap.width, bits_per_pixel)
    stored_rows = [pack_indices([index_for_colour(colour) for colour in row], bits_per_pixel, stride)
                   for row in reversed(bitmap.pixels)]
    return build_dib(bitmap.width, bitmap.height, bits_per_pixel, palette, stored_rows)


def two_bit_dib(bitmap):
    return indexed_dib(bitmap, TWO_BIT_PALETTE, 2, lambda colour: gray_level(*colour))


def write_2bp(bitmap):
    return wrap_dib(two_bit_dib(bitmap), len(TWO_BIT_PALETTE))


def write_bmp(bitmap):
    colours = sorted({colour for row in bitmap.pixels for colour in row})
    if len(colours) <= 16:
        palette = colours + [(0, 0, 0)] * (16 - len(colours))
        lookup = {colour: index for index, colour in enumerate(colours)}
        return wrap_dib(indexed_dib(bitmap, palette, 4, lookup.__getitem__), len(palette))
    stride = row_stride(bitmap.width, 24)
    stored_rows = []
    for row in reversed(bitmap.pixels):
        row_bytes = bytearray(stride)
        for column, (red, green, blue) in enumerate(row):
            row_bytes[column * 3:column * 3 + 3] = bytes((blue, green, red))
        stored_rows.append(bytes(row_bytes))
    return wrap_dib(build_dib(bitmap.width, bitmap.height, 24, [], stored_rows), 0)


def png_chunk(kind, payload):
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def write_png(bitmap):
    grayscale = bitmap.is_grayscale()
    colour_type = 0 if grayscale else 2
    raw = bytearray()
    for row in bitmap.pixels:
        raw.append(0)
        if grayscale:
            raw.extend(red for red, _, _ in row)
        else:
            for colour in row:
                raw.extend(colour)
    header = struct.pack(">IIBBBBB", bitmap.width, bitmap.height, 8, colour_type, 0, 0, 0)
    return (PNG_SIGNATURE + png_chunk(b"IHDR", header) + png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + png_chunk(b"IEND", b""))


def paeth(left, above, upper_left):
    estimate = left + above - upper_left
    distance_left = abs(estimate - left)
    distance_above = abs(estimate - above)
    distance_upper_left = abs(estimate - upper_left)
    if distance_left <= distance_above and distance_left <= distance_upper_left:
        return left
    if distance_above <= distance_upper_left:
        return above
    return upper_left


def unfilter_rows(data, position, row_count, row_length, bytes_per_pixel):
    rows = []
    previous = bytearray(row_length)
    for _ in range(row_count):
        filter_type = data[position]
        current = bytearray(data[position + 1:position + 1 + row_length])
        position += 1 + row_length
        for index in range(row_length):
            left = current[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            above = previous[index]
            upper_left = previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            if filter_type == 1:
                current[index] = (current[index] + left) & 0xFF
            elif filter_type == 2:
                current[index] = (current[index] + above) & 0xFF
            elif filter_type == 3:
                current[index] = (current[index] + (left + above) // 2) & 0xFF
            elif filter_type == 4:
                current[index] = (current[index] + paeth(left, above, upper_left)) & 0xFF
            elif filter_type != 0:
                raise ConversionError(f"bad PNG filter {filter_type}")
        rows.append(bytes(current))
        previous = current
    return rows, position


def png_samples(row, width, bit_depth, channels):
    if bit_depth == 8:
        return [tuple(row[column * channels:(column + 1) * channels]) for column in range(width)]
    if bit_depth == 16:
        return [tuple(row[(column * channels + channel) * 2] for channel in range(channels)) for column in range(width)]
    return [(value,) for value in unpack_indices(row, width, bit_depth)]


def composite_on_white(colour, alpha):
    return tuple((value * alpha + 255 * (255 - alpha)) // 255 for value in colour)


def png_colour(sample, colour_type, bit_depth, palette, transparency):
    if colour_type == 3:
        index = sample[0]
        colour = palette[index] if index < len(palette) else (0, 0, 0)
        alpha = transparency[index] if index < len(transparency) else 255
        return composite_on_white(colour, alpha)
    if colour_type in (0, 4):
        value = sample[0]
        if bit_depth < 8:
            value = value * 255 // ((1 << bit_depth) - 1)
        colour = (value, value, value)
        return composite_on_white(colour, sample[1]) if colour_type == 4 else colour
    colour = sample[:3]
    return composite_on_white(colour, sample[3]) if colour_type == 6 else colour


def read_png(data):
    if not data.startswith(PNG_SIGNATURE):
        raise ConversionError("not a PNG file")
    position = len(PNG_SIGNATURE)
    compressed = bytearray()
    palette = []
    transparency = b""
    header = None
    while position < len(data):
        length, kind = struct.unpack_from(">I4s", data, position)
        payload = data[position + 8:position + 8 + length]
        position += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", payload)
        elif kind == b"PLTE":
            palette = [tuple(payload[index:index + 3]) for index in range(0, len(payload), 3)]
        elif kind == b"tRNS":
            transparency = payload
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            break
    if header is None:
        raise ConversionError("PNG has no header")
    width, height, bit_depth, colour_type, _, _, interlace = header
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(colour_type)
    if channels is None:
        raise ConversionError(f"unsupported PNG colour type {colour_type}")
    if colour_type in (0, 2) and transparency:
        transparency = b""
    raw = zlib.decompress(bytes(compressed))
    bytes_per_pixel = max(1, channels * bit_depth // 8)
    pixels = [[(255, 255, 255)] * width for _ in range(height)]
    passes = ADAM7_PASSES if interlace else [(0, 0, 1, 1)]
    position = 0
    for start_column, start_row, column_step, row_step in passes:
        pass_width = (width - start_column + column_step - 1) // column_step
        pass_height = (height - start_row + row_step - 1) // row_step
        if pass_width <= 0 or pass_height <= 0:
            continue
        row_length = (pass_width * channels * bit_depth + 7) // 8
        rows, position = unfilter_rows(raw, position, pass_height, row_length, bytes_per_pixel)
        for pass_row, row in enumerate(rows):
            samples = png_samples(row, pass_width, bit_depth, channels)
            target_row = pixels[start_row + pass_row * row_step]
            for pass_column, sample in enumerate(samples):
                target_row[start_column + pass_column * column_step] = png_colour(
                    sample, colour_type, bit_depth, palette, transparency)
    return Bitmap(width, height, pixels)


def reduce_to_two_bit(bitmap):
    rows = [[TWO_BIT_PALETTE[gray_level(*colour)] for colour in row] for row in bitmap.pixels]
    return Bitmap(bitmap.width, bitmap.height, rows)


def read_image(data):
    if data.startswith(PNG_SIGNATURE):
        return read_png(data)
    return read_bmp(data)
