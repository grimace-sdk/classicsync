import asyncio
import errno
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

import wx

from ...backup import BackupError, BackupFormatError, DeviceIdentity, backup, restore
from ...backup.operations import describe_device, open_backup
from ...paths import data_directory
from ...sync.state import read_json, write_json_atomically
from .sync_runner import EVENT_FAILED, EVENT_FINISHED, EVENT_STOPPED

log = logging.getLogger("classicsync.gui.backup")

BACKUP_FILE_NAME = "Backup.stg"
SETTINGS_FILE_NAME = "backup.json"
GUEST_DIRECTORY_NAME = "guest"

MISMATCH_DEVICE_TYPE = "device type"
MISMATCH_LANGUAGE = "language"
MISMATCH_PROCESSOR = "processor"
MISMATCH_VERSION = "version"
MISMATCH_NEWER_VERSION = "newer version"
MISMATCH_OEM = "oem"
MISMATCH_PARTNERSHIP = "partnership"

FAILURE_CANCELLED = "cancelled"
FAILURE_CONNECTION = "connection"
FAILURE_DISK_FULL = "disk full"
FAILURE_LOCKED = "locked"
FAILURE_INVALID_FILE = "invalid file"
FAILURE_UNRECOVERABLE = "unrecoverable"

OPERATION_BACKUP = "backup"
OPERATION_RESTORE = "restore"
OPERATION_CHECK = "check"

SYNC_DONE_EVENTS = (EVENT_FINISHED, EVENT_FAILED, EVENT_STOPPED)


class BackupCancelled(Exception):
    pass


def settings_directory(partnership):
    return partnership.directory if partnership else data_directory() / GUEST_DIRECTORY_NAME


def default_backup_path(partnership):
    return settings_directory(partnership) / BACKUP_FILE_NAME


@dataclass
class BackupSettings:
    file: str = ""
    incremental: bool = True
    automatic: bool = False
    directory: Path = field(default=None, repr=False, compare=False)

    @classmethod
    def load(cls, partnership):
        directory = settings_directory(partnership)
        stored = read_json(directory / SETTINGS_FILE_NAME, {})
        known = {name: value for name, value in stored.items() if name in ("file", "incremental", "automatic")}
        settings = cls(**known)
        settings.directory = directory
        return settings

    def to_dict(self):
        stored = asdict(self)
        stored.pop("directory")
        return stored

    def save(self):
        write_json_atomically(self.directory / SETTINGS_FILE_NAME, self.to_dict())

    @property
    def path(self):
        return Path(self.file) if self.file else self.directory / BACKUP_FILE_NAME


def backup_settings_for(partnership):
    return BackupSettings.load(partnership)


def partnerships_with_backups(partnerships):
    found = []
    for partnership in partnerships:
        path = BackupSettings.load(partnership).path
        if path.exists():
            found.append((partnership, path))
    return found


@dataclass
class RestoreCheck:
    information: object
    mismatches: list

    def has(self, kind):
        return kind in self.mismatches


def restore_mismatches(information, version, system, language, identity):
    mismatches = []
    if identity.platform and information.not_handheld_pc != identity.not_handheld_pc:
        mismatches.append(MISMATCH_DEVICE_TYPE)
    if information.language != language:
        mismatches.append(MISMATCH_LANGUAGE)
    if information.processor_type != system.processor_type:
        mismatches.append(MISMATCH_PROCESSOR)
    elif ((information.processor_level and information.processor_level != system.processor_level)
          or (information.processor_revision and information.processor_revision != system.processor_revision)):
        mismatches.append(MISMATCH_PROCESSOR)
    if information.os_major is not None:
        if information.os_major != version.major or version.minor < information.os_minor:
            mismatches.append(MISMATCH_VERSION)
        elif version.minor != information.os_minor:
            mismatches.append(MISMATCH_NEWER_VERSION)
    if information.oem_info and identity.oem_info and information.oem_info != identity.oem_info:
        mismatches.append(MISMATCH_OEM)
    if identity.partnership_id and information.partnership_id and information.partnership_id != identity.partnership_id:
        mismatches.append(MISMATCH_PARTNERSHIP)
    return mismatches


def read_backup_information(path):
    try:
        return open_backup(path)[1]
    except (BackupError, BackupFormatError, OSError):
        return None


def failure_kind(error):
    if isinstance(error, BackupCancelled):
        return FAILURE_CANCELLED
    if isinstance(error, (ConnectionError, asyncio.TimeoutError, EOFError)):
        return FAILURE_CONNECTION
    if isinstance(error, PermissionError):
        return FAILURE_LOCKED
    if isinstance(error, OSError) and error.errno in (errno.ENOSPC, errno.EDQUOT):
        return FAILURE_DISK_FULL
    if isinstance(error, OSError) and error.errno in (errno.EBUSY, errno.EACCES, errno.EROFS):
        return FAILURE_LOCKED
    return FAILURE_UNRECOVERABLE


class BackupRunner:
    def __init__(self, application):
        self.application = application
        self.future = None
        self.operation = None
        self.cancel_requested = False
        self.after_sync_callbacks = []
        self.listeners = []

    @property
    def running(self):
        return self.future is not None and not self.future.done()

    @property
    def busy(self):
        return self.running or self.application.sync.running

    def add_listener(self, callback):
        self.listeners.append(callback)

    def remove_listener(self, callback):
        if callback in self.listeners:
            self.listeners.remove(callback)

    def _notify(self):
        for callback in list(self.listeners):
            try:
                callback(self.operation if self.running else None)
            except RuntimeError:
                self.remove_listener(callback)

    def identity(self):
        partnership = self.application.partnership
        partner_id = partnership.partner_id if partnership and partnership.partner_id else 0
        return DeviceIdentity.from_announcement(self.application.service.announcement, partner_id)

    def _start(self, operation, work, on_finished, on_progress=None):
        if self.busy:
            return False
        service = self.application.service
        self.cancel_requested = False
        self.operation = operation

        def progress(update):
            if self.cancel_requested and operation == OPERATION_BACKUP:
                raise BackupCancelled()
            if on_progress:
                wx.CallAfter(on_progress, update)

        async def run(client):
            return await work(client, progress)

        def done(future):
            error = future.exception() if not future.cancelled() else BackupCancelled()
            wx.CallAfter(self._finished, future, on_finished, None if error else future.result(), error)

        self.future = service.submit(service.with_rapi(run))
        self.future.add_done_callback(done)
        self._notify()
        return True

    def _finished(self, future, on_finished, result, error):
        if future is self.future:
            self.operation = None
            self._notify()
        if error and not isinstance(error, BackupCancelled):
            log.info("backup operation failed: %s", error)
        on_finished(result, error)

    def back_up(self, path, full, file_version, on_progress, on_finished):
        identity = self.identity()

        async def work(client, progress):
            return await backup(client, path, full=full, progress=progress, identity=identity, file_version=file_version)

        return self._start(OPERATION_BACKUP, work, on_finished, on_progress)

    def restore(self, path, data_only, allow_mismatch, on_progress, on_finished):
        identity = self.identity()

        async def work(client, progress):
            return await restore(client, path, progress=progress, identity=identity, data_only=data_only,
                                 allow_mismatch=allow_mismatch)

        return self._start(OPERATION_RESTORE, work, on_finished, on_progress)

    def check_restore(self, path, on_finished):
        identity = self.identity()

        async def work(client, progress):
            root, information = open_backup(path)
            version, system, language = await describe_device(client)
            return RestoreCheck(information, restore_mismatches(information, version, system, language, identity))

        return self._start(OPERATION_CHECK, work, on_finished)

    def cancel(self):
        self.cancel_requested = True

    def after_sync(self, callback):
        if not self.application.sync.running:
            wx.CallAfter(callback)
            return
        if not self.after_sync_callbacks:
            self.application.sync.add_listener(self._sync_event)
        self.after_sync_callbacks.append(callback)

    def _sync_event(self, kind, payload):
        if kind not in SYNC_DONE_EVENTS:
            return
        self.application.sync.remove_listener(self._sync_event)
        callbacks, self.after_sync_callbacks = self.after_sync_callbacks, []
        for callback in callbacks:
            wx.CallAfter(callback)

    def schedule_automatic(self):
        partnership = self.application.partnership
        if partnership is None or not BackupSettings.load(partnership).automatic:
            return
        announcement = self.application.service.announcement

        def run():
            if self.application.service.announcement is not announcement or self.application.partnership is not partnership:
                return
            self.application.frontend.run_automatic_backup()

        self.after_sync(run)
