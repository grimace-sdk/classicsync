import base64
import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree
from xml.sax.saxutils import escape

D = "{DAV:}"
C = "{urn:ietf:params:xml:ns:caldav}"
CARD = "{urn:ietf:params:xml:ns:carddav}"
PRINCIPAL = "/dav/ada/"
TOKEN_PREFIX = "http://fake.invalid/sync/"


class FakeCollection:
    def __init__(self, kind, name, components=()):
        self.kind = kind
        self.name = name
        self.components = components
        self.items = {}
        self.token = 0
        self.changes = []

    def change(self, name):
        self.token += 1
        self.changes.append((self.token, name))

    def put(self, name, text):
        self.items[name] = (text, '"' + hashlib.sha1(text.encode()).hexdigest()[:16] + '"')
        self.change(name)

    def delete(self, name):
        self.items.pop(name, None)
        self.change(name)


class FakeDavServer:
    def __init__(self, username="ada", password="secret", sync_collection=True, rewrite_on_put=False):
        self.username = username
        self.password = password
        self.sync_collection = sync_collection
        self.rewrite_on_put = rewrite_on_put
        self.collections = {
            PRINCIPAL + "contacts/": FakeCollection("addressbook", "Contacts"),
            PRINCIPAL + "calendar/": FakeCollection("calendar", "Personal", ("VEVENT",)),
            PRINCIPAL + "tasks/": FakeCollection("calendar", "Tasks", ("VTODO",)),
        }
        self.requests = []
        server = self

        class Handler(DavHandler):
            fake = server

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.http.server_address[1]}/"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *details):
        self.http.shutdown()
        self.http.server_close()

    def collection(self, name):
        return self.collections[PRINCIPAL + name + "/"]


def response_xml(href, properties, status=None):
    if status:
        return f"<d:response><d:href>{escape(href)}</d:href><d:status>HTTP/1.1 {status}</d:status></d:response>"
    return (f"<d:response><d:href>{escape(href)}</d:href><d:propstat><d:prop>{''.join(properties)}</d:prop>"
            "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>")


def multistatus(responses, extra=""):
    return ('<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" '
            f'xmlns:card="urn:ietf:params:xml:ns:carddav">{"".join(responses)}{extra}</d:multistatus>')


class DavHandler(BaseHTTPRequestHandler):
    fake = None
    protocol_version = "HTTP/1.1"

    def log_message(self, *arguments):
        pass

    def body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def reply(self, status, body=b"", headers=None):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        expected = base64.b64encode(f"{self.fake.username}:{self.fake.password}".encode()).decode()
        if self.headers.get("Authorization") == f"Basic {expected}":
            return True
        self.reply(401, "", {"WWW-Authenticate": 'Basic realm="fake"'})
        return False

    def path_only(self):
        return unquote(urlsplit(self.path).path)

    def split_item(self):
        path = self.path_only()
        folder, _, name = path.rpartition("/")
        return self.fake.collections.get(folder + "/"), name

    def handle_any(self, method):
        body = self.body()
        self.fake.requests.append((method, self.path_only(), dict(self.headers)))
        if self.path_only().startswith("/.well-known/"):
            self.reply(301, "", {"Location": "/dav/"})
            return
        if not self.authorized():
            return
        getattr(self, "dav_" + method.lower())(body)

    def do_PROPFIND(self):
        self.handle_any("PROPFIND")

    def do_REPORT(self):
        self.handle_any("REPORT")

    def do_GET(self):
        self.handle_any("GET")

    def do_PUT(self):
        self.handle_any("PUT")

    def do_DELETE(self):
        self.handle_any("DELETE")

    def collection_properties(self, path, collection):
        resource = "<d:collection/>" + ("<card:addressbook/>" if collection.kind == "addressbook" else "<c:calendar/>")
        properties = [f"<d:resourcetype>{resource}</d:resourcetype>", f"<d:displayname>{escape(collection.name)}</d:displayname>"]
        if collection.components:
            components = "".join(f'<c:comp name="{name}"/>' for name in collection.components)
            properties.append(f"<c:supported-calendar-component-set>{components}</c:supported-calendar-component-set>")
        if self.fake.sync_collection:
            properties.append("<d:supported-report-set><d:supported-report><d:report><d:sync-collection/></d:report>"
                              "</d:supported-report></d:supported-report-set>")
            properties.append(f"<d:sync-token>{TOKEN_PREFIX}{collection.token}</d:sync-token>")
        return response_xml(path, properties)

    def dav_propfind(self, body):
        path = self.path_only()
        depth = self.headers.get("Depth", "0")
        responses = []
        if path in ("/", "/dav/"):
            responses.append(response_xml(path, [f"<d:current-user-principal><d:href>{PRINCIPAL}</d:href></d:current-user-principal>"]))
        elif path == PRINCIPAL:
            responses.append(response_xml(path, [
                f"<d:current-user-principal><d:href>{PRINCIPAL}</d:href></d:current-user-principal>",
                f"<c:calendar-home-set><d:href>{PRINCIPAL}</d:href></c:calendar-home-set>",
                f"<card:addressbook-home-set><d:href>{PRINCIPAL}</d:href></card:addressbook-home-set>",
                "<d:resourcetype><d:collection/></d:resourcetype>",
            ]))
            if depth == "1":
                responses.extend(self.collection_properties(href, collection) for href, collection in self.fake.collections.items())
        elif path in self.fake.collections:
            collection = self.fake.collections[path]
            responses.append(self.collection_properties(path, collection))
            if depth == "1":
                responses.extend(response_xml(path + name, [f"<d:getetag>{etag}</d:getetag>", "<d:resourcetype/>"])
                                 for name, (text, etag) in collection.items.items())
        else:
            collection, name = self.split_item()
            if collection is None or name not in collection.items:
                self.reply(404)
                return
            responses.append(response_xml(path, [f"<d:getetag>{collection.items[name][1]}</d:getetag>"]))
        self.reply(207, multistatus(responses), {"Content-Type": "application/xml"})

    def dav_report(self, body):
        path = self.path_only()
        collection = self.fake.collections.get(path)
        if collection is None:
            self.reply(404)
            return
        root = ElementTree.fromstring(body)
        data_tag = "card:address-data" if collection.kind == "addressbook" else "c:calendar-data"
        if root.tag == D + "sync-collection":
            if not self.fake.sync_collection:
                self.reply(403, "<d:error xmlns:d='DAV:'><d:supported-report/></d:error>")
                return
            token_text = root.findtext(D + "sync-token") or ""
            if token_text and not token_text.startswith(TOKEN_PREFIX):
                self.reply(403, "<d:error xmlns:d='DAV:'><d:valid-sync-token/></d:error>")
                return
            since = int(token_text[len(TOKEN_PREFIX):]) if token_text else 0
            names = sorted({name for token, name in collection.changes if token > since}) if since else sorted(collection.items)
            responses = []
            for name in names:
                if name in collection.items:
                    responses.append(response_xml(path + name, [f"<d:getetag>{collection.items[name][1]}</d:getetag>"]))
                else:
                    responses.append(response_xml(path + name, [], "404 Not Found"))
            self.reply(207, multistatus(responses, f"<d:sync-token>{TOKEN_PREFIX}{collection.token}</d:sync-token>"),
                       {"Content-Type": "application/xml"})
            return
        if root.tag == C + "calendar-query":
            wanted = [element.get("name") for element in root.iter(C + "comp-filter")][-1]
            responses = [response_xml(path + name, [f"<d:getetag>{etag}</d:getetag>"])
                         for name, (text, etag) in collection.items.items() if f"BEGIN:{wanted}" in text]
            self.reply(207, multistatus(responses), {"Content-Type": "application/xml"})
            return
        responses = []
        for href in root.findall(D + "href"):
            name = unquote(href.text).rpartition("/")[2]
            if name in collection.items:
                text, etag = collection.items[name]
                responses.append(response_xml(href.text, [f"<d:getetag>{etag}</d:getetag>", f"<{data_tag}>{escape(text)}</{data_tag}>"]))
            else:
                responses.append(response_xml(href.text, [], "404 Not Found"))
        self.reply(207, multistatus(responses), {"Content-Type": "application/xml"})

    def dav_get(self, body):
        collection, name = self.split_item()
        if collection is None or name not in collection.items:
            self.reply(404)
            return
        text, etag = collection.items[name]
        self.reply(200, text, {"ETag": etag, "Content-Type": "text/plain; charset=utf-8"})

    def dav_put(self, body):
        collection, name = self.split_item()
        if collection is None:
            self.reply(409)
            return
        existing = collection.items.get(name)
        if self.headers.get("If-None-Match") == "*" and existing:
            self.reply(412)
            return
        if self.headers.get("If-Match") and (not existing or existing[1] != self.headers.get("If-Match")):
            self.reply(412)
            return
        text = body.decode("utf-8")
        if self.fake.rewrite_on_put:
            text = text.replace("END:VCARD", "X-SERVER-ADDED:yes\r\nEND:VCARD")
        collection.put(name, text)
        headers = {} if self.fake.rewrite_on_put else {"ETag": collection.items[name][1]}
        self.reply(201 if not existing else 204, "", headers)

    def dav_delete(self, body):
        collection, name = self.split_item()
        if collection is None or name not in collection.items:
            self.reply(404)
            return
        if self.headers.get("If-Match") and collection.items[name][1] != self.headers.get("If-Match"):
            self.reply(412)
            return
        collection.delete(name)
        self.reply(204)
