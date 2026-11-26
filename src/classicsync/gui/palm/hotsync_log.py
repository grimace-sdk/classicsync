from datetime import datetime

from ...i18n import _

LOG_NAME = "HotSync.Log"
KEPT_SESSIONS = 10
SESSION_START = "HotSync operation started"


def stamp():
    return datetime.now().strftime("%c")


def log_path(partnership):
    return partnership.directory / LOG_NAME


def conduit_line(name, failed, messages):
    if failed:
        return _("{conduit} synchronization failed").format(conduit=name)
    line = _("OK {conduit}").format(conduit=name)
    if messages:
        line += _(" with {count} message(s)").format(count=messages)
    return line


def session_text(lines, completed):
    end = _("HotSync operation complete") if completed else _("HotSync operation canceled.")
    return "\n".join([f"{SESSION_START} {stamp()}", *lines, f"{end} {stamp()}"]) + "\n"


def append_session(partnership, lines, completed=True):
    path = log_path(partnership)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    sessions = [part for part in existing.split(SESSION_START) if part.strip()]
    sessions = [SESSION_START + part for part in sessions][-(KEPT_SESSIONS - 1):]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(sessions) + session_text(lines, completed), encoding="utf-8")


def read_log(partnership):
    path = log_path(partnership)
    return path.read_text(encoding="utf-8") if path.exists() else ""
