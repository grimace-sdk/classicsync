import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin

DROPPED_TAGS = {
    "script", "style", "noscript", "iframe", "frame", "frameset", "form", "nav", "aside", "footer", "button", "select",
    "textarea", "svg", "canvas", "template", "object", "embed", "video", "audio", "map", "head", "dialog", "menu",
}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCK_TAGS = {"p", "div", "section", "article", "main", "header", "figure", "figcaption", "address", "center", "details",
              "summary", "tr", "caption"}
KEPT_BLOCK_TAGS = HEADING_TAGS | {"ul", "ol", "li", "dl", "dt", "dd", "pre", "blockquote"}
INLINE_NAMES = {"b": "b", "strong": "b", "i": "i", "em": "i", "cite": "i", "u": "u", "code": "tt", "tt": "tt", "kbd": "tt",
                "samp": "tt", "var": "i", "small": "small", "sub": "sub", "sup": "sup"}
CELL_TAGS = {"td", "th"}
LIST_TAGS = {"ul", "ol", "dl"}
LIST_ITEM_TAGS = {"li", "dt", "dd"}
CONTENT_TAGS = {"main", "article"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
WHITESPACE = re.compile(r"\s+")
SMALLEST_MAIN_TEXT = 200
MOST_IMAGES = 20


@dataclass
class SimplePage:
    title: str
    body: str
    text_length: int
    images: list = field(default_factory=list)


def hidden(attributes):
    values = dict(attributes)
    style = (values.get("style") or "").replace(" ", "").lower()
    return "hidden" in values or values.get("aria-hidden") == "true" or "display:none" in style


class PageSimplifier(HTMLParser):
    def __init__(self, base_url, link_target=None, image_source=None):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.link_target = link_target or (lambda url: url)
        self.image_source = image_source
        self.title_parts = []
        self.in_title = False
        self.dropped_stack = []
        self.open_tags = []
        self.outputs = {"all": [], "main": []}
        self.text_lengths = {"all": 0, "main": 0}
        self.content_depth = 0
        self.preformatted = 0
        self.pending_space = False
        self.at_block_start = True
        self.image_count = 0
        self.images = []

    def emit(self, markup, text_length=0):
        targets = ("all", "main") if self.content_depth else ("all",)
        for target in targets:
            self.outputs[target].append(markup)
            self.text_lengths[target] += text_length

    def block_break(self):
        if not self.at_block_start:
            self.emit("\n<p>")
        self.at_block_start = True
        self.pending_space = False

    def handle_starttag(self, tag, attributes):
        if tag == "title":
            self.in_title = True
        if self.dropped_stack:
            if tag not in VOID_TAGS:
                self.dropped_stack.append(tag)
            return
        if (tag in DROPPED_TAGS or hidden(attributes)) and tag not in VOID_TAGS:
            self.dropped_stack.append(tag)
            return
        if tag in CONTENT_TAGS:
            self.content_depth += 1
        values = dict(attributes)
        if tag in KEPT_BLOCK_TAGS:
            if tag in LIST_ITEM_TAGS:
                self.close_list_item()
            self.block_break()
            self.emit(f"<{tag}>")
            self.open_tags.append(tag)
            if tag == "pre":
                self.preformatted += 1
        elif tag in BLOCK_TAGS:
            self.block_break()
        elif tag in CELL_TAGS:
            self.pending_space = True
        elif tag == "br":
            self.emit("<br>\n")
            self.at_block_start = True
            self.pending_space = False
        elif tag == "hr":
            self.block_break()
            self.emit("<hr>")
        elif tag == "a":
            self.open_link(values)
        elif tag in INLINE_NAMES:
            self.flush_space()
            self.emit(f"<{INLINE_NAMES[tag]}>")
            self.open_tags.append(INLINE_NAMES[tag])
        elif tag == "img":
            self.image(values)

    def close_list_item(self):
        for index in range(len(self.open_tags) - 1, -1, -1):
            tag = self.open_tags[index]
            if tag in LIST_TAGS:
                return
            if tag in LIST_ITEM_TAGS:
                while len(self.open_tags) > index:
                    closing = self.open_tags.pop()
                    if closing:
                        self.emit(f"</{closing}>")
                self.at_block_start = True
                return

    def open_link(self, values):
        href = (values.get("href") or "").strip()
        if not href or href.lower().startswith(("javascript:", "mailto:", "data:")) or href.startswith("#"):
            self.open_tags.append(None)
            return
        target = self.link_target(urldefrag(urljoin(self.base_url, href))[0])
        self.flush_space()
        self.emit(f'<a href="{html.escape(target, quote=True)}">')
        self.open_tags.append("a")

    def image(self, values):
        alt = (values.get("alt") or "").strip()
        source = (values.get("src") or "").strip()
        local_name = None
        if self.image_source and source and not source.startswith("data:") and self.image_count < MOST_IMAGES:
            local_name = self.image_source(urljoin(self.base_url, source))
        self.flush_space()
        if local_name:
            self.image_count += 1
            self.images.append(local_name)
            self.emit(f'<img src="{html.escape(local_name, quote=True)}" alt="{html.escape(alt, quote=True)}">')
            self.at_block_start = False
        elif alt:
            self.emit(f"[{html.escape(alt)}]", len(alt))
            self.at_block_start = False

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if self.dropped_stack:
            if tag in self.dropped_stack:
                while self.dropped_stack and self.dropped_stack.pop() != tag:
                    pass
            return
        if tag in CONTENT_TAGS and self.content_depth:
            self.content_depth -= 1
        if tag in KEPT_BLOCK_TAGS or tag in INLINE_NAMES or tag == "a":
            wanted = INLINE_NAMES.get(tag, tag)
            if wanted in self.open_tags or (tag == "a" and None in self.open_tags):
                while self.open_tags:
                    closing = self.open_tags.pop()
                    if closing:
                        self.emit(f"</{closing}>")
                    if closing == wanted or (tag == "a" and closing is None):
                        break
            if tag == "pre" and self.preformatted:
                self.preformatted -= 1
            if tag in KEPT_BLOCK_TAGS:
                self.block_break()
        elif tag in BLOCK_TAGS:
            self.block_break()

    def flush_space(self):
        if self.pending_space and not self.at_block_start:
            self.emit(" ")
        self.pending_space = False

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)
            return
        if self.dropped_stack:
            return
        if self.preformatted:
            self.emit(html.escape(data, quote=False), len(data))
            self.at_block_start = False
            return
        if data[:1].isspace():
            self.pending_space = True
        words = WHITESPACE.sub(" ", data).strip()
        if not words:
            return
        self.flush_space()
        self.emit(html.escape(words, quote=False), len(words))
        self.at_block_start = False
        self.pending_space = data[-1:].isspace()

    def result(self):
        while self.open_tags:
            closing = self.open_tags.pop()
            if closing:
                self.emit(f"</{closing}>")
        chosen = "main" if self.text_lengths["main"] >= SMALLEST_MAIN_TEXT else "all"
        body = "".join(self.outputs[chosen])
        body = re.sub(r"<(li|dd|dt|h\d|blockquote)>\s*</\1>", "", body)
        body = re.sub(r"(\n<p>)+(?=\s*(<(ul|ol|dl|h\d|pre|blockquote|hr)\b|$))", "\n", body)
        body = re.sub(r"(\n<p>)+", "\n<p>", body)
        body = re.sub(r"\n{2,}", "\n", body).strip()
        title = WHITESPACE.sub(" ", "".join(self.title_parts)).strip()
        return SimplePage(title, body, self.text_lengths[chosen], self.images)


def simplify_html(text, base_url, link_target=None, image_source=None):
    simplifier = PageSimplifier(base_url, link_target, image_source)
    simplifier.feed(text)
    simplifier.close()
    return simplifier.result()


def shorten(body, limit):
    if len(body) <= limit:
        return body, False
    cut = body.rfind("\n", 0, limit)
    return body[:cut if cut > 0 else limit], True


def page_document(title, body, source_url, fetched, shortened_note=""):
    escaped_title = html.escape(title or source_url)
    parts = [
        "<html><head>",
        f"<title>{escaped_title}</title>",
        "</head><body>",
        f"<h3>{escaped_title}</h3>",
        body,
        "<hr>",
    ]
    if shortened_note:
        parts.append(f"<p><i>{html.escape(shortened_note)}</i></p>")
    parts.append(f'<p><small><a HREF="{html.escape(source_url, quote=True)}">{html.escape(source_url)}</a> {html.escape(fetched)}</small></p>')
    parts.append("</body></html>")
    return ("\r\n".join(parts) + "\r\n").encode("ascii", "xmlcharrefreplace")
