from test_palm_sync import FakePalm, handheld_databases

from classicsync.gui.palm.hotsync_log import KEPT_SESSIONS, append_session, read_log
from classicsync.gui.palm.service import EVENT_FINISHED, EVENT_STATUS, EVENT_USER, PalmService
from classicsync.gui.settings import Settings
from classicsync.palm.sync import palm_partnerships


def service_for(palm, events):
    service = PalmService(Settings(), lambda kind, payload: events.append((kind, payload)))
    service.transport_for = lambda device: palm
    return service


def test_hotsync_session_reports_progress_and_writes_the_log(run, tmp_path, monkeypatch):
    monkeypatch.setenv("CLASSICSYNC_HOME", str(tmp_path))
    events = []
    service = service_for(FakePalm(handheld_databases()), events)
    run(lambda: service._hotsync(None))
    statuses = [payload for kind, payload in events if kind == EVENT_STATUS]
    assert statuses[:2] == ["Connecting with handheld", "Identifying user"]
    assert "Synchronizing Address Book" in statuses and "Backing up handheld databases" in statuses
    assert statuses[-1] == "HotSync operation complete"
    assert (EVENT_USER, "Phil Howard") in events
    succeeded, _summary, problems = events[-1][1]
    assert events[-1][0] == EVENT_FINISHED and succeeded and not problems
    log = read_log(palm_partnerships()[0])
    assert log.startswith("HotSync operation started") and "OK Address Book" in log and "OK Memo Pad" in log


def test_first_hotsync_asks_for_a_user(run, tmp_path, monkeypatch):
    monkeypatch.setenv("CLASSICSYNC_HOME", str(tmp_path))
    events = []
    palm = FakePalm(handheld_databases(), user_name="", user_id=0)
    service = service_for(palm, events)
    service.ask_user_name = lambda reply: reply(("Phil", None))
    run(lambda: service._hotsync(None))
    assert palm.user["name"] == "Phil" and palm.user["id"] >= 0x100
    assert [partnership.name for partnership in palm_partnerships()] == ["Phil"]


def test_declining_the_user_prompt_cancels(run, tmp_path, monkeypatch):
    monkeypatch.setenv("CLASSICSYNC_HOME", str(tmp_path))
    events = []
    service = service_for(FakePalm(handheld_databases(), user_name="", user_id=0), events)
    service.ask_user_name = lambda reply: reply(None)
    run(lambda: service._hotsync(None))
    succeeded, message, problems = events[-1][1]
    assert not succeeded and not problems and palm_partnerships() == []


def test_log_keeps_the_last_sessions(tmp_path):
    from classicsync.palm.sync import create_palm_partnership
    partnership = create_palm_partnership("Phil", 0x1234, base=tmp_path)
    for index in range(KEPT_SESSIONS + 3):
        append_session(partnership, [f"OK session {index}"])
    log = read_log(partnership)
    assert log.count("HotSync operation started") == KEPT_SESSIONS and "OK session 0\n" not in log
