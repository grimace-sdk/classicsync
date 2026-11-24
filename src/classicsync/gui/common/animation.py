import struct
from dataclasses import dataclass, field

import wx

RLE_ESCAPE = 0
RLE_END_OF_LINE = 0
RLE_END_OF_BITMAP = 1
RLE_DELTA = 2


def _iterate_chunks(data, start, end):
    offset = start
    while offset + 8 <= end:
        chunk_id = data[offset:offset + 4]
        size = struct.unpack_from("<I", data, offset + 4)[0]
        if chunk_id in (b"RIFF", b"LIST"):
            yield chunk_id, data[offset + 8:offset + 12], offset + 12, offset + 8 + size
        else:
            yield chunk_id, None, offset + 8, offset + 8 + size
        offset += 8 + size + (size & 1)


def _collect_chunks(data, start, end, found):
    for chunk_id, list_type, body_start, body_end in _iterate_chunks(data, start, end):
        if list_type is not None:
            _collect_chunks(data, body_start, body_end, found)
        else:
            found.append((chunk_id, body_start, body_end))


def decode_rle8(payload, width, height, previous):
    pixels = bytearray(previous) if previous else bytearray(width * height)
    x = 0
    y = 0
    index = 0
    while index + 1 < len(payload):
        count = payload[index]
        value = payload[index + 1]
        index += 2
        if count:
            for _ in range(count):
                if x < width and y < height:
                    pixels[y * width + x] = value
                x += 1
        elif value == RLE_END_OF_LINE:
            x = 0
            y += 1
        elif value == RLE_END_OF_BITMAP:
            break
        elif value == RLE_DELTA:
            x += payload[index]
            y += payload[index + 1]
            index += 2
        else:
            for literal in payload[index:index + value]:
                if x < width and y < height:
                    pixels[y * width + x] = literal
                x += 1
            index += value + (value & 1)
    return pixels


@dataclass
class AnimationClip:
    width: int
    height: int
    interval_ms: int
    frames: list = field(default_factory=list)
    transparent_index: int = 0
    palette: list = field(default_factory=list)


def decode_avi(data):
    chunks = []
    _collect_chunks(data, 0, len(data), chunks)
    main_header = next(body for chunk_id, body, _ in chunks if chunk_id == b"avih")
    microseconds_per_frame = struct.unpack_from("<I", data, main_header)[0]
    format_start = next(body for chunk_id, body, _ in chunks if chunk_id == b"strf")
    header_size, width, height, _, bit_count, compression = struct.unpack_from("<IiiHHI", data, format_start)
    colors_used = struct.unpack_from("<I", data, format_start + 32)[0] or (1 << bit_count if bit_count <= 8 else 0)
    palette_bytes = data[format_start + header_size:format_start + header_size + colors_used * 4]
    palette = [(palette_bytes[index * 4 + 2], palette_bytes[index * 4 + 1], palette_bytes[index * 4]) for index in range(colors_used)]
    rows = abs(height)
    clip = AnimationClip(width, rows, max(1, microseconds_per_frame // 1000), palette=palette)
    previous = None
    for chunk_id, body_start, body_end in chunks:
        if chunk_id[2:4] not in (b"db", b"dc"):
            continue
        payload = data[body_start:body_end]
        if compression == 1:
            pixels = decode_rle8(payload, width, rows, previous)
        elif compression == 0 and bit_count == 8:
            stride = (width + 3) & ~3
            pixels = bytearray()
            for row in range(rows):
                pixels += payload[row * stride:row * stride + width]
        else:
            raise ValueError(f"unsupported AVI compression {compression} at {bit_count} bits")
        previous = pixels
        if height > 0:
            pixels = b"".join(bytes(pixels[row * width:(row + 1) * width]) for row in reversed(range(rows)))
        clip.frames.append(bytes(pixels))
    if clip.frames:
        clip.transparent_index = clip.frames[0][0]
    return clip


def frame_bitmap(clip, pixels, background):
    rgb = bytearray(clip.width * clip.height * 3)
    fill = (background.Red(), background.Green(), background.Blue())
    for index, colour_index in enumerate(pixels):
        colour = fill if colour_index == clip.transparent_index else clip.palette[colour_index]
        rgb[index * 3:index * 3 + 3] = bytes(colour)
    return wx.Bitmap(wx.Image(clip.width, clip.height, bytes(rgb)))


class AnimationPlayer(wx.Panel):
    def __init__(self, parent, clip=None, position=wx.DefaultPosition, size=wx.DefaultSize):
        super().__init__(parent, pos=position, size=size)
        self.clip = clip
        self.bitmaps = []
        self.frame = 0
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._advance, self.timer)
        self.Bind(wx.EVT_PAINT, self._paint)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._destroyed)
        if clip:
            self.bitmaps = [frame_bitmap(clip, pixels, self.GetBackgroundColour()) for pixels in clip.frames]

    def play(self):
        if self.bitmaps and not self.timer.IsRunning():
            self.timer.Start(self.clip.interval_ms)

    def stop(self):
        self.timer.Stop()

    def _destroyed(self, event):
        if event.GetEventObject() is self:
            self.timer.Stop()
        event.Skip()

    def _advance(self, event):
        self.frame = (self.frame + 1) % len(self.bitmaps)
        self.Refresh(False)

    def _paint(self, event):
        dc = wx.BufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetBackgroundColour()))
        dc.Clear()
        if not self.bitmaps:
            return
        bitmap = self.bitmaps[self.frame]
        width, height = self.GetClientSize()
        dc.DrawBitmap(bitmap, (width - bitmap.GetWidth()) // 2, (height - bitmap.GetHeight()) // 2, True)


def load_clip(artwork, module, number):
    path = artwork.path(module, f"avi_{number}.avi")
    if not path.exists():
        return None
    try:
        return decode_avi(path.read_bytes())
    except (ValueError, StopIteration, struct.error):
        return None
