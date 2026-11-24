import email
import email.policy
import html
import re
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime, formataddr, getaddresses

from ...rapi.structures import datetime_to_filetime, filetime_to_datetime
from .records import FROM, MailMessage

ADDRESS_HEADERS = {"from", "to", "cc", "bcc", "reply-to", "sender"}
MIME_HEADERS = {"mime-version", "content-type", "content-transfer-encoding", "content-disposition", "content-id"}
DATE_HEADER = "date"
SERVICE_ADDRESS = re.compile(r"^(?P<name>.*?)\s*\[(?P<type>[A-Za-z0-9-]+):(?P<address>[^\]]+)\]\s*$")
HTML_TAG = re.compile(r"<[^>]+>")
HTML_BREAK = re.compile(r"<\s*(br|/p|/div|/tr|/li)\b[^>]*>", re.IGNORECASE)
HTML_INVISIBLE = re.compile(r"<\s*(script|style)\b.*?<\s*/\s*\1\s*>", re.IGNORECASE | re.DOTALL)
WRITE_POLICY = email.policy.default.clone(linesep="\n", max_line_length=998)
READ_POLICY = email.policy.default


def local_datetime_from_filetime(filetime):
    if not filetime:
        return None
    wall_clock = filetime_to_datetime(filetime).replace(tzinfo=None)
    return wall_clock.astimezone()


def local_filetime_from_datetime(moment):
    if moment.tzinfo is not None:
        moment = moment.astimezone().replace(tzinfo=None)
    return datetime_to_filetime(moment.replace(tzinfo=timezone.utc))


def desktop_address(value):
    match = SERVICE_ADDRESS.match(value)
    if match and "@" in match["address"]:
        return formataddr((match["name"].strip(), match["address"].strip()))
    return value


def desktop_address_list(value):
    parts = [part.strip() for part in value.split(";") if part.strip()]
    return ", ".join(desktop_address(part) for part in parts)


def device_address_list(value):
    addresses = getaddresses([value])
    return "; ".join(formataddr((name, address)) if name else address for name, address in addresses if address or name)


def one_line(value):
    return " ".join(str(value).split())


def desktop_header(name, value):
    if name.lower() in ADDRESS_HEADERS:
        return desktop_address_list(value)
    return one_line(value)


def message_to_rfc5322(message):
    mime = EmailMessage(policy=WRITE_POLICY)
    for name, value in message.headers:
        if not name or name.lower() in MIME_HEADERS:
            continue
        text = desktop_header(name, value)
        try:
            mime[name] = text
        except (ValueError, TypeError, IndexError):
            mime[name] = text.encode("ascii", "replace").decode("ascii")
    if "Date" not in mime:
        moment = local_datetime_from_filetime(message.date)
        if moment is not None:
            mime["Date"] = format_datetime(moment)
    mime.set_content(message.body.replace("\r\n", "\n").replace("\r", "\n"), charset="utf-8")
    return mime.as_bytes()


def text_from_html(markup):
    text = HTML_INVISIBLE.sub("", markup)
    text = HTML_BREAK.sub("\n", text)
    return html.unescape(HTML_TAG.sub("", text))


def message_body(parsed):
    part = parsed.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except (LookupError, ValueError):
        payload = part.get_payload(decode=True) or b""
        content = payload.decode("utf-8", errors="replace")
    if not isinstance(content, str):
        return ""
    if part.get_content_subtype() == "html":
        content = text_from_html(content)
    return content


def device_header(name, value):
    if name.lower() in ADDRESS_HEADERS:
        return device_address_list(str(value))
    return one_line(value)


def message_date(parsed):
    header = parsed.get(DATE_HEADER)
    moment = getattr(header, "datetime", None) if header is not None else None
    return moment or datetime.now().astimezone()


def message_from_rfc5322(data):
    parsed = email.message_from_bytes(data, policy=READ_POLICY)
    headers = []
    for name, value in parsed.items():
        if name.lower() in MIME_HEADERS or name.lower() == DATE_HEADER:
            continue
        headers.append((name, device_header(name, value)))
    return MailMessage(headers=headers, body=message_body(parsed),
                       date=local_filetime_from_datetime(message_date(parsed)))


def address_key(value):
    text = desktop_address_list(value)
    return tuple(sorted(address.lower() for _, address in getaddresses([text]) if address))


def content_key(message):
    headers = []
    for name, value in message.headers:
        lower = name.lower()
        if lower in MIME_HEADERS or lower == DATE_HEADER:
            continue
        headers.append((lower, address_key(value) if lower in ADDRESS_HEADERS else one_line(value)))
    body = message.body.replace("\r\n", "\n").replace("\r", "\n").rstrip()
    return tuple(sorted(headers)), body


def sender(message):
    return desktop_address_list(message.header(FROM))
