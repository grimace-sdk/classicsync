import errno
from types import SimpleNamespace

import pytest

pytest.importorskip("wx")

from classicsync.backup import BackupSetInformation, DeviceIdentity  # noqa: E402
from classicsync.gui.common.backup import (  # noqa: E402
    BACKUP_FILE_NAME, FAILURE_CANCELLED, FAILURE_CONNECTION, FAILURE_DISK_FULL, FAILURE_LOCKED, FAILURE_UNRECOVERABLE,
    MISMATCH_DEVICE_TYPE, MISMATCH_LANGUAGE, MISMATCH_NEWER_VERSION, MISMATCH_OEM, MISMATCH_PARTNERSHIP, MISMATCH_PROCESSOR,
    MISMATCH_VERSION, BackupCancelled, BackupSettings, failure_kind, read_backup_information, restore_mismatches,
)
from classicsync.sync import Partnership  # noqa: E402


def test_settings_default_to_backup_stg_in_the_partnership_folder(tmp_path):
    partnership = Partnership("Velo", tmp_path / "Velo", 0x1234)
    settings = BackupSettings.load(partnership)
    assert settings.path == tmp_path / "Velo" / BACKUP_FILE_NAME
    assert settings.incremental and not settings.automatic
    settings.automatic = True
    settings.file = str(tmp_path / "elsewhere.stg")
    settings.save()
    reloaded = BackupSettings.load(partnership)
    assert reloaded.automatic and reloaded.path == tmp_path / "elsewhere.stg"


def test_guest_settings_live_in_the_data_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("CLASSICSYNC_HOME", str(tmp_path))
    assert BackupSettings.load(None).path == tmp_path / "guest" / BACKUP_FILE_NAME


def device(major=2, minor=11, processor=2577, level=4, revision=0):
    return SimpleNamespace(major=major, minor=minor), SimpleNamespace(processor_type=processor, processor_level=level,
                                                                      processor_revision=revision)


def test_matching_backup_has_no_mismatches():
    information = BackupSetInformation(partnership_id=7, processor_type=2577, os_version=(2 << 16) | 11, language=0x409)
    version, system = device()
    assert restore_mismatches(information, version, system, 0x409, DeviceIdentity("HPC", "", 7)) == []


def test_mismatches_are_classified():
    information = BackupSetInformation(partnership_id=7, processor_type=4000, os_version=(2 << 16) | 0, language=0x407,
                                       not_handheld_pc=1, oem_info="Other")
    version, system = device()
    found = restore_mismatches(information, version, system, 0x409, DeviceIdentity("HPC", "Velo", 8))
    assert found == [MISMATCH_DEVICE_TYPE, MISMATCH_LANGUAGE, MISMATCH_PROCESSOR, MISMATCH_NEWER_VERSION, MISMATCH_OEM,
                     MISMATCH_PARTNERSHIP]
    older_device = restore_mismatches(BackupSetInformation(processor_type=2577, os_version=(2 << 16) | 12), *device(), 0x409,
                                      DeviceIdentity())
    assert older_device == [MISMATCH_VERSION]


def test_hpc_explorer_backups_skip_the_version_check():
    information = BackupSetInformation(processor_type=2577, version=5, os_version=0x448)
    assert restore_mismatches(information, *device(major=1, minor=0), 0x409, DeviceIdentity()) == []


def test_failures_are_classified():
    assert failure_kind(BackupCancelled()) == FAILURE_CANCELLED
    assert failure_kind(ConnectionResetError()) == FAILURE_CONNECTION
    assert failure_kind(OSError(errno.ENOSPC, "full")) == FAILURE_DISK_FULL
    assert failure_kind(PermissionError(errno.EACCES, "locked")) == FAILURE_LOCKED
    assert failure_kind(ValueError("bad")) == FAILURE_UNRECOVERABLE


def test_invalid_backup_file_reads_as_none(tmp_path):
    path = tmp_path / "Backup.stg"
    path.write_bytes(b"not a compound file")
    assert read_backup_information(path) is None
    assert read_backup_information(tmp_path / "missing.stg") is None
