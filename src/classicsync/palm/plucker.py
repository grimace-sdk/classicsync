import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urldefrag, urlparse

from ..formats.plucker import COMPRESSION_ZLIB, build_document, html_page, text_page
from ..sync.providers.favorites.fetch import FetchError, decode_page, fetch
from ..sync.providers.favorites.simplify import simplify_html

FIRST_PAGE_UID = 2
MOST_PAGES = 50
HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
TEXT_SUFFIXES = {".txt", ".md", ".text"}


@dataclass
class Gathered:
    title: str
    pages: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


def is_url(source):
    return urlparse(source).scheme in ("http", "https")


def same_site(url, roots):
    host = urlparse(url).netloc.lower()
    return any(host == urlparse(root).netloc.lower() for root in roots)


def read_source(source):
    if is_url(source):
        fetched = fetch(source)
        return fetched.url, decode_page(fetched), False
    path = Path(source).expanduser()
    data = path.read_text(encoding="utf-8", errors="replace")
    return path.resolve().as_uri(), data, path.suffix.lower() in TEXT_SUFFIXES


def gather(sources, depth=0, most_pages=MOST_PAGES, progress=None):
    queue = [(source, 0) for source in sources]
    seen = set()
    collected = []
    skipped = []
    while queue and len(collected) < most_pages:
        source, level = queue.pop(0)
        key = urldefrag(source)[0]
        if key in seen:
            continue
        seen.add(key)
        if progress:
            progress(source)
        try:
            url, text, plain = read_source(source)
        except (FetchError, OSError) as error:
            skipped.append((source, str(error)))
            continue
        seen.add(urldefrag(url)[0])
        if plain:
            collected.append((url, Path(source).stem, None, text))
            continue
        page = simplify_html(text, url)
        collected.append((url, page.title or url, page.body, None))
        if level < depth:
            for link in HREF.findall(page.body):
                target = urldefrag(html.unescape(link))[0]
                if is_url(target) and same_site(target, sources) and target not in seen:
                    queue.append((target, level + 1))
    return collected, skipped


def build_plucker(sources, title=None, depth=0, compression=COMPRESSION_ZLIB, progress=None):
    collected, skipped = gather(sources, depth, progress=progress)
    if not collected:
        raise ValueError("nothing could be read from " + ", ".join(sources))
    uids = {urldefrag(url)[0]: FIRST_PAGE_UID + index for index, (url, _title, _body, _text) in enumerate(collected)}

    def link_uid(href):
        return uids.get(urldefrag(html.unescape(href))[0])

    pages = []
    for index, (url, page_title, body, text) in enumerate(collected):
        uid = FIRST_PAGE_UID + index
        if text is not None:
            pages.append(text_page(text, uid))
        else:
            heading = f"<h2>{html.escape(page_title)}</h2>"
            pages.append(html_page(heading + body, uid, link_uid)[0])
    document = build_document(title or collected[0][1], pages, compression)
    return document, skipped
