import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fake_device import FakeRapiClient

from classicsync.convert.bitmap import Bitmap, write_png
from classicsync.sync import Partnership, SyncOptions, synchronize
from classicsync.sync.folder import FolderProvider
from classicsync.sync.providers.favorites.fetch import Fetched, decode_page, device_image
from classicsync.sync.providers.favorites.provider import FavoritesProvider
from classicsync.sync.providers.favorites.simplify import simplify_html

PROVIDERS = {"folder": FolderProvider, "favorites": FavoritesProvider}
SMALL_GIF = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
ARTICLE = """<!doctype html><html><head><meta charset="windows-1252"><title>News \u2013 Today</title>
<script>track()</script><style>body{color:red}</style></head><body>
<nav><a href="/">Home</a> <a href="/about">About</a></nav>
<article><h1>Big story</h1><p>First   paragraph with <a href="second.html">a link</a> and <em>emphasis</em>.</p>
<p><img src="/dot.gif" alt="dot"> <img src="/wide.png" alt="wide"> <img src="/huge.gif" alt="huge picture"></p>
<ul><li>one<li>two</ul><form><input name=q></form><p>Caf\xe9 society.</p></article>
<footer>Copyright</footer></body></html>"""
SECOND = "<html><head><title>Second</title></head><body><p>Second page</p></body></html>"


def png_bytes(width, height):
    return write_png(Bitmap(width, height, [[(255, 0, 0)] * width for _ in range(height)]))


class PageServer:
    def __init__(self):
        self.pages = {
            "/article.html": ("text/html", ARTICLE.encode("cp1252")),
            "/second.html": ("text/html; charset=utf-8", SECOND.encode("utf-8")),
            "/dot.gif": ("image/gif", SMALL_GIF),
            "/wide.png": ("image/png", png_bytes(400, 20)),
            "/huge.gif": ("image/gif", b"GIF89a" + bytes(40000)),
        }
        self.requests = []
        pages = self.pages
        requests = self.requests

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                if self.path not in pages:
                    self.send_error(404)
                    return
                content_type, body = pages[self.path]
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *arguments):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def url(self, path):
        return f"http://127.0.0.1:{self.server.server_address[1]}{path}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def server():
    running = PageServer()
    yield running
    running.close()


def test_simplify_keeps_structure_and_drops_cruft():
    page = simplify_html(ARTICLE, "http://example.com/news/article.html")
    assert page.title == "News \u2013 Today"
    assert "<h1>Big story</h1>" in page.body
    assert '<a href="http://example.com/news/second.html">a link</a>' in page.body
    assert "<i>emphasis</i>" in page.body
    assert "<ul><li>one</li><li>two</li></ul>" in page.body
    for dropped in ("track()", "color:red", "Home", "Copyright", "<form", "<input"):
        assert dropped not in page.body
    assert "First paragraph" in page.body


def test_charset_detection():
    data = ARTICLE.encode("cp1252")
    assert "Café" in decode_page(Fetched("http://x/", data))
    assert "Café" in decode_page(Fetched("http://x/", "<p>Café</p>".encode("utf-8"), "text/html", "utf-8"))


def test_device_images():
    assert device_image(SMALL_GIF, 1024) == (".gif", SMALL_GIF)
    extension, data = device_image(png_bytes(400, 20), 64 * 1024)
    assert extension == ".bmp" and data.startswith(b"BM")
    assert int.from_bytes(data[18:22], "little") == 240
    assert device_image(b"GIF89a" + bytes(5000), 1024) is None
    assert device_image(b"not an image", 1024) is None


def sync(client, partnership, settings):
    options = SyncOptions(object_types=["favorites"], type_providers={"favorites": "favorites"}, provider_settings=settings)
    report = asyncio.run(synchronize(client, partnership, options, providers=PROVIDERS))
    assert not [action for action in report.actions if action.error], report.actions
    assert not report.errors
    return report


def device_files(client):
    return {entry.path: entry.data for entry in client.files.values()}


def test_pages_are_synchronized_one_way(server, tmp_path):
    client = FakeRapiClient()
    partnership = Partnership.for_device("HPC", tmp_path / "partnerships")
    settings = {"favorites_urls": [server.url("/article.html"), server.url("/second.html")], "favorites_shortcuts": True}
    sync(client, partnership, settings)
    files = device_files(client)
    folder = "\\My Documents\\Offline Pages\\"
    article = files[folder + "News Today.htm"]
    assert b"<h1>Big story</h1>" in article
    assert b'<a href="Second.htm">a link</a>' in article
    assert b"Caf&#233; society" in article
    assert b'<img src="News Today 1.gif" alt="dot">' in article
    assert b'<img src="News Today 2.bmp" alt="wide">' in article
    assert b"[huge picture]" in article
    assert files[folder + "News Today 1.gif"] == SMALL_GIF
    index = files[folder + "index.htm"]
    assert b'<a href="News Today.htm">' in index and b'<a href="Second.htm">Second</a>' in index
    shortcut = files["\\Windows\\Favorites\\Mobile Favorites\\Second.url"]
    assert shortcut == b"[InternetShortcut]\r\nURL=file://\\My Documents\\Offline Pages\\Second.htm\r\n"

    fetched = len(server.requests)
    assert sync(client, partnership, settings).counts() == {}
    assert len(server.requests) == fetched

    client.put_file(folder + "Second.htm", b"edited on the device")
    del client.files[(folder + "index.htm").lower()]
    client.put_file(folder + "mine.htm", b"the user's own page")
    sync(client, partnership, settings)
    report = sync(client, partnership, settings)
    files = device_files(client)
    assert b"Second page" in files[folder + "Second.htm"]
    assert b"Offline Pages" in files[folder + "index.htm"]
    assert files[folder + "mine.htm"] == b"the user's own page"
    assert sync(client, partnership, settings).counts() == {}, report

    settings["favorites_urls"] = [server.url("/second.html")]
    settings["favorites_shortcuts"] = False
    sync(client, partnership, settings)
    files = device_files(client)
    assert folder + "News Today.htm" not in files
    assert folder + "News Today 1.gif" not in files
    assert files[folder + "mine.htm"] == b"the user's own page"


def test_failed_fetch_keeps_previous_page(server, tmp_path):
    client = FakeRapiClient()
    partnership = Partnership.for_device("HPC", tmp_path / "partnerships")
    settings = {"favorites_urls": [server.url("/second.html")], "favorites_refresh_hours": 0}
    sync(client, partnership, settings)
    del server.pages["/second.html"]
    assert sync(client, partnership, settings).counts() == {}
    assert b"Second page" in client.file("\\My Documents\\Offline Pages\\Second.htm")
