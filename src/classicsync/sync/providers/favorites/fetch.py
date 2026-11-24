import codecs
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from ....convert.bitmap import Bitmap, read_image, write_bmp
from ....convert.errors import ConversionError

USER_AGENT = "Mozilla/5.0 (compatible; ClassicSync offline pages)"
TIMEOUT_SECONDS = 20
MOST_PAGE_BYTES = 4 * 1024 * 1024
META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([\w.:-]+)""", re.IGNORECASE)
GIF_SIGNATURES = (b"GIF87a", b"GIF89a")
JPEG_SIGNATURE = b"\xff\xd8\xff"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
WIDEST_IMAGE = 240


class FetchError(Exception):
    pass


@dataclass
class Fetched:
    url: str
    data: bytes
    content_type: str = ""
    charset: str = ""


def fetch(url, limit=MOST_PAGE_BYTES):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,image/*;q=0.8,*/*;q=0.5"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            data = response.read(limit + 1)
            content_type = response.headers.get_content_type() or ""
            charset = response.headers.get_content_charset() or ""
            final_url = response.geturl()
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise FetchError(str(getattr(error, "reason", error))) from error
    if len(data) > limit:
        raise FetchError(f"larger than {limit // 1024} KB")
    return Fetched(final_url, data, content_type, charset)


def known_codec(name):
    try:
        return codecs.lookup(name).name
    except (LookupError, TypeError):
        return None


def decode_page(fetched):
    data = fetched.data
    if data.startswith(codecs.BOM_UTF8):
        return data[len(codecs.BOM_UTF8):].decode("utf-8", errors="replace")
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", errors="replace")
    candidates = [fetched.charset]
    meta = META_CHARSET.search(data[:4096])
    if meta:
        candidates.append(meta.group(1).decode("ascii", errors="ignore"))
    for candidate in candidates:
        codec = known_codec(candidate)
        if codec:
            return data.decode(codec, errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def scaled(bitmap, widest=WIDEST_IMAGE):
    if bitmap.width <= widest:
        return bitmap
    height = max(1, bitmap.height * widest // bitmap.width)
    rows = []
    for row_index in range(height):
        source_row = bitmap.pixels[row_index * bitmap.height // height]
        rows.append([source_row[column * bitmap.width // widest] for column in range(widest)])
    return Bitmap(widest, height, rows)


def device_image(data, most_bytes):
    if data.startswith(GIF_SIGNATURES):
        return (".gif", data) if len(data) <= most_bytes else None
    if data.startswith(JPEG_SIGNATURE):
        return (".jpg", data) if len(data) <= most_bytes else None
    if data.startswith(PNG_SIGNATURE) or data.startswith(b"BM"):
        try:
            converted = write_bmp(scaled(read_image(data)))
        except (ConversionError, ValueError, IndexError, KeyError):
            return None
        return (".bmp", converted) if len(converted) <= most_bytes else None
    return None
