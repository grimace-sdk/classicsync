import base64
import http.client
import socket
import ssl
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urljoin, urlsplit
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from .... import __version__

DAV_NAMESPACE = "DAV:"
CALDAV_NAMESPACE = "urn:ietf:params:xml:ns:caldav"
CARDDAV_NAMESPACE = "urn:ietf:params:xml:ns:carddav"
CALENDARSERVER_NAMESPACE = "http://calendarserver.org/ns/"
D = "{%s}" % DAV_NAMESPACE
C = "{%s}" % CALDAV_NAMESPACE
CARD = "{%s}" % CARDDAV_NAMESPACE
CS = "{%s}" % CALENDARSERVER_NAMESPACE
NAMESPACES = f'xmlns:d="{DAV_NAMESPACE}" xmlns:c="{CALDAV_NAMESPACE}" xmlns:card="{CARDDAV_NAMESPACE}" xmlns:cs="{CALENDARSERVER_NAMESPACE}"'
XML_HEADER = '<?xml version="1.0" encoding="utf-8"?>\n'
REDIRECT_STATUSES = (301, 302, 303, 307, 308)
MOST_REDIRECTS = 5
MULTIGET_BATCH = 50

KIND_CALENDAR = "calendar"
KIND_ADDRESS_BOOK = "addressbook"
WELL_KNOWN = {KIND_CALENDAR: "/.well-known/caldav", KIND_ADDRESS_BOOK: "/.well-known/carddav"}
HOME_SET = {KIND_CALENDAR: C + "calendar-home-set", KIND_ADDRESS_BOOK: CARD + "addressbook-home-set"}
HOME_SET_XML = {KIND_CALENDAR: "<c:calendar-home-set/>", KIND_ADDRESS_BOOK: "<card:addressbook-home-set/>"}
RESOURCE_TYPE = {KIND_CALENDAR: C + "calendar", KIND_ADDRESS_BOOK: CARD + "addressbook"}


class DavError(Exception):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


class AuthenticationError(DavError):
    pass


class PreconditionFailed(DavError):
    pass


@dataclass
class DavResponse:
    status: int
    reason: str
    headers: dict
    body: bytes
    url: str

    def header(self, name):
        return self.headers.get(name.lower())

    def text(self):
        charset = "utf-8"
        content_type = self.header("content-type") or ""
        for part in content_type.split(";")[1:]:
            key, _, value = part.strip().partition("=")
            if key.lower() == "charset" and value:
                charset = value.strip('"')
        try:
            return self.body.decode(charset)
        except (LookupError, UnicodeDecodeError):
            return self.body.decode("utf-8", errors="replace")


@dataclass
class MultistatusEntry:
    href: str
    status: int = 200
    properties: dict = field(default_factory=dict)
    missing: set = field(default_factory=set)

    def text(self, tag):
        element = self.properties.get(tag)
        return (element.text or "").strip() if element is not None else ""

    def href_in(self, tag):
        element = self.properties.get(tag)
        if element is None:
            return ""
        href = element.find(D + "href")
        return (href.text or "").strip() if href is not None else ""

    def hrefs_in(self, tag):
        element = self.properties.get(tag)
        if element is None:
            return []
        return [(href.text or "").strip() for href in element.findall(D + "href") if (href.text or "").strip()]

    def resource_types(self):
        element = self.properties.get(D + "resourcetype")
        return {child.tag for child in element} if element is not None else set()

    def components(self):
        element = self.properties.get(C + "supported-calendar-component-set")
        if element is None:
            return set()
        return {child.get("name", "").upper() for child in element if child.tag == C + "comp"}

    def reports(self):
        element = self.properties.get(D + "supported-report-set")
        if element is None:
            return set()
        return {report.tag for supported in element for wrapper in supported for report in wrapper}


@dataclass
class Collection:
    url: str
    kind: str
    name: str = ""
    components: frozenset = frozenset()
    sync_supported: bool = False

    def holds(self, component):
        return self.kind == KIND_ADDRESS_BOOK or not self.components or component in self.components

    def label(self):
        return self.name or self.url


def status_code(text):
    parts = (text or "").split()
    if len(parts) >= 2 and parts[1].isdigit():
        return int(parts[1])
    return 0


def parse_multistatus(body):
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as error:
        raise DavError(f"the server sent a reply that is not valid XML: {error}") from None
    entries = []
    for response in root.findall(D + "response"):
        href_element = response.find(D + "href")
        if href_element is None or not (href_element.text or "").strip():
            continue
        entry = MultistatusEntry(href_element.text.strip())
        response_status = response.find(D + "status")
        if response_status is not None:
            entry.status = status_code(response_status.text)
        for propstat in response.findall(D + "propstat"):
            code = status_code(propstat.findtext(D + "status"))
            properties = propstat.find(D + "prop")
            if properties is None:
                continue
            for prop in properties:
                if 200 <= code < 300:
                    entry.properties[prop.tag] = prop
                else:
                    entry.missing.add(prop.tag)
        entries.append(entry)
    sync_token = root.findtext(D + "sync-token")
    return entries, (sync_token or "").strip()


def same_resource(first, second):
    return unquote(urlsplit(first).path).rstrip("/") == unquote(urlsplit(second).path).rstrip("/")


def propfind_body(properties_xml):
    return f"{XML_HEADER}<d:propfind {NAMESPACES}><d:prop>{properties_xml}</d:prop></d:propfind>"


def sync_collection_body(sync_token):
    return (f"{XML_HEADER}<d:sync-collection {NAMESPACES}><d:sync-token>{escape(sync_token)}</d:sync-token>"
            "<d:sync-level>1</d:sync-level><d:prop><d:getetag/></d:prop></d:sync-collection>")


def calendar_query_body(component, start=None):
    time_range = f'<c:time-range start="{start}"/>' if start else ""
    return (f"{XML_HEADER}<c:calendar-query {NAMESPACES}><d:prop><d:getetag/></d:prop>"
            f'<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="{component}">{time_range}'
            "</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>")


def multiget_body(kind, hrefs):
    links = "".join(f"<d:href>{escape(href)}</d:href>" for href in hrefs)
    if kind == KIND_ADDRESS_BOOK:
        return (f"{XML_HEADER}<card:addressbook-multiget {NAMESPACES}><d:prop><d:getetag/><card:address-data/></d:prop>"
                f"{links}</card:addressbook-multiget>")
    return (f"{XML_HEADER}<c:calendar-multiget {NAMESPACES}><d:prop><d:getetag/><c:calendar-data/></d:prop>"
            f"{links}</c:calendar-multiget>")


def user_agent():
    return f"classicsync/{__version__}"


def normalized_href(href):
    return unquote(urlsplit(href).path)


class DavClient:
    def __init__(self, base_url, username="", password="", timeout=30):
        if not base_url:
            raise DavError("no server address")
        if "://" not in base_url:
            base_url = "https://" + base_url
        self.base_url = base_url if base_url.endswith("/") or urlsplit(base_url).path not in ("", "/") else base_url.rstrip("/") + "/"
        self.username = username
        self.password = password
        self.timeout = timeout
        self.connections = {}

    def absolute(self, href, base=None):
        return urljoin(base or self.base_url, href)

    def connection(self, scheme, host):
        key = (scheme, host)
        if key not in self.connections:
            if scheme == "https":
                self.connections[key] = http.client.HTTPSConnection(host, timeout=self.timeout, context=ssl.create_default_context())
            elif scheme == "http":
                self.connections[key] = http.client.HTTPConnection(host, timeout=self.timeout)
            else:
                raise DavError(f"unsupported address {scheme}://{host}")
        return self.connections[key]

    def drop_connection(self, scheme, host):
        connection = self.connections.pop((scheme, host), None)
        if connection is not None:
            connection.close()

    def close(self):
        for connection in self.connections.values():
            connection.close()
        self.connections = {}

    def authorization(self):
        if not self.username and not self.password:
            return None
        token = base64.b64encode(f"{self.username}:{self.password}".encode("utf-8")).decode("ascii")
        return f"Basic {token}"

    def send_once(self, method, url, body, headers):
        parts = urlsplit(url)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        all_headers = {"User-Agent": user_agent(), **headers}
        if body is not None:
            all_headers.setdefault("Content-Type", 'application/xml; charset="utf-8"')
        authorization = self.authorization()
        if authorization:
            all_headers["Authorization"] = authorization
        encoded = body.encode("utf-8") if isinstance(body, str) else body
        for attempt in range(2):
            connection = self.connection(parts.scheme, parts.netloc)
            try:
                connection.request(method, quote(path, safe="/%:@!$&'()*+,;=-._~?"), body=encoded, headers=all_headers)
                reply = connection.getresponse()
                data = reply.read()
            except (http.client.HTTPException, ConnectionError, socket.timeout, OSError) as error:
                self.drop_connection(parts.scheme, parts.netloc)
                if attempt:
                    raise DavError(f"could not reach {parts.netloc}: {error}") from None
                continue
            headers = {name.lower(): value for name, value in reply.getheaders()}
            if headers.get("connection", "").lower() == "close":
                self.drop_connection(parts.scheme, parts.netloc)
            return DavResponse(reply.status, reply.reason, headers, data, url)
        raise DavError(f"could not reach {parts.netloc}")

    def request(self, method, url, body=None, headers=None, expected=(200, 201, 204, 207)):
        url = self.absolute(url)
        for _ in range(MOST_REDIRECTS):
            response = self.send_once(method, url, body, headers or {})
            if response.status in REDIRECT_STATUSES and response.header("location"):
                url = self.absolute(response.header("location"), url)
                continue
            break
        if response.status == 401:
            raise AuthenticationError(f"{urlsplit(url).netloc} refused the user name or password", 401)
        if response.status == 412:
            raise PreconditionFailed(f"{url} was changed on the server", 412)
        if expected and response.status not in expected:
            raise DavError(f"{method} {url}: {response.status} {response.reason}", response.status)
        return response

    def propfind(self, url, properties_xml, depth=0):
        response = self.request("PROPFIND", url, propfind_body(properties_xml), {"Depth": str(depth)})
        return parse_multistatus(response.body)[0], response.url

    def report(self, url, body, depth=1):
        response = self.request("REPORT", url, body, {"Depth": str(depth)})
        return parse_multistatus(response.body)

    def get(self, url):
        response = self.request("GET", url, expected=(200,))
        return response.text(), (response.header("etag") or "")

    def etag(self, url):
        entries, _ = self.propfind(url, "<d:getetag/>", 0)
        return next((entry.text(D + "getetag") for entry in entries if entry.text(D + "getetag")), "")

    def put(self, url, text, content_type, etag=None):
        headers = {"Content-Type": f"{content_type}; charset=utf-8"}
        if etag:
            headers["If-Match"] = etag
        else:
            headers["If-None-Match"] = "*"
        response = self.request("PUT", url, text, headers, expected=(200, 201, 204))
        return response.header("etag") or self.etag(url)

    def delete(self, url, etag=None):
        headers = {"If-Match": etag} if etag else {}
        self.request("DELETE", url, None, headers, expected=(200, 204, 404))

    def principal(self):
        candidates = [self.base_url]
        for kind in (KIND_CALENDAR, KIND_ADDRESS_BOOK):
            candidates.append(self.absolute(WELL_KNOWN[kind]))
        for candidate in candidates:
            try:
                entries, final_url = self.propfind(candidate, "<d:current-user-principal/>", 0)
            except AuthenticationError:
                raise
            except DavError:
                continue
            for entry in entries:
                href = entry.href_in(D + "current-user-principal")
                if href:
                    return self.absolute(href, final_url)
        return None

    def home_sets(self, kind):
        principal = self.principal()
        if principal is None:
            return [self.base_url]
        entries, final_url = self.propfind(principal, HOME_SET_XML[kind], 0)
        homes = [self.absolute(href, final_url) for entry in entries for href in entry.hrefs_in(HOME_SET[kind])]
        return homes or [principal]

    def collections(self, kind):
        properties = ("<d:resourcetype/><d:displayname/><c:supported-calendar-component-set/><d:supported-report-set/>"
                      "<cs:getctag/><d:sync-token/>")
        found = []
        seen = set()
        for home in [self.base_url, *self.home_sets(kind)]:
            try:
                entries, final_url = self.propfind(home, properties, 1)
            except AuthenticationError:
                raise
            except DavError:
                continue
            for entry in entries:
                if RESOURCE_TYPE[kind] not in entry.resource_types():
                    continue
                url = self.absolute(entry.href, final_url)
                if not url.endswith("/"):
                    url += "/"
                if url in seen:
                    continue
                seen.add(url)
                sync_supported = D + "sync-collection" in entry.reports() or bool(entry.text(D + "sync-token"))
                found.append(Collection(url, kind, entry.text(D + "displayname"), frozenset(entry.components()),
                                        sync_supported))
            if found:
                break
        return found

    def sync_collection(self, url, sync_token):
        return self.report(url, sync_collection_body(sync_token), 1)

    def multiget(self, url, kind, hrefs):
        data_tag = CARD + "address-data" if kind == KIND_ADDRESS_BOOK else C + "calendar-data"
        found = {}
        hrefs = list(hrefs)
        for start in range(0, len(hrefs), MULTIGET_BATCH):
            entries, _ = self.report(url, multiget_body(kind, hrefs[start:start + MULTIGET_BATCH]), 1)
            for entry in entries:
                if entry.status != 200 or data_tag not in entry.properties:
                    continue
                found[normalized_href(entry.href)] = (entry.text(data_tag), entry.text(D + "getetag"))
        return found
