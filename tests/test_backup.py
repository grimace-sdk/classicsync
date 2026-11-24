import os
import random
import struct

import pytest

from classicsync.backup import BackupError, inspect
from classicsync.backup.compound import (
    SECTOR_SIZE, CompoundFileError, CompoundFileReader, Storage, read_compound_file, write_compound_file,
)
from classicsync.backup.format import (
    BACKUP_SET_INFORMATION, DATABASE_INFO, DIRECTORY_ATTRIBUTES, PEGASUS_DATABASES, VERSION_ACTIVESYNC,
    VERSION_HPC_EXPLORER, BackupFormatError, BackupSetInformation, DatabaseInfo, FileHeader, RecordBlock,
    database_element_name, database_name_from_element, element_name_for, pack_file_stream, record_stream_name,
    unpack_file_stream,
)
from classicsync.backup.operations import DeviceIdentity, compatibility_problems, full_name_of, shortcut_target
from classicsync.rapi import cedb
from classicsync.rapi.structures import SystemInfo, VersionInfo


def sample_tree():
    random.seed(7)
    root = Storage()
    expected = {}
    for index, size in enumerate([0, 1, 63, 64, 65, 4095, 4096, 4097, 70000]):
        data = os.urandom(size)
        root.set_stream(f"stream {index}", data)
        expected[("stream " + str(index),)] = data
    folder = root.create_storage("Windows")
    for index in range(150):
        data = os.urandom(random.randint(0, 6000))
        folder.set_stream(f"file{index}.txt", data)
        expected[("Windows", f"file{index}.txt")] = data
    folder.create_storage("Empty")
    return root, expected


def lookup(root, path):
    node = root
    for part in path[:-1]:
        node = node.storage(part)
    return node.stream(path[-1]).data


def test_compound_round_trip():
    root, expected = sample_tree()
    data = write_compound_file(root)
    assert data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    assert len(data) % SECTOR_SIZE == 0
    back = read_compound_file(data)
    for path, contents in expected.items():
        assert lookup(back, path) == contents
    assert back.storage("Windows").storage("Empty") is not None
    assert [entry.name for entry in back][:3] == ["Windows", "stream 0", "stream 1"]


def test_compound_large_file_uses_difat():
    root = Storage()
    root.set_stream("big", b"\x5a" * (7 * 1024 * 1024 + 1000))
    data = write_compound_file(root)
    difat_sectors = struct.unpack_from("<I", data, 0x48)[0]
    assert difat_sectors >= 1
    assert read_compound_file(data).stream("big").data == b"\x5a" * (7 * 1024 * 1024 + 1000)


def test_compound_directory_is_a_valid_red_black_tree():
    root = Storage()
    for index in range(37):
        root.set_stream(f"s{index}", b"x")
    reader = CompoundFileReader(write_compound_file(root))
    child = reader.entry(0)["child"]

    def black_height(index, parent_red=False):
        if index == 0xFFFFFFFF:
            return 1
        entry = reader.entry(index)
        red = reader.directory[index][0x43] == 0
        assert not (red and parent_red)
        left = black_height(entry["left"], red)
        right = black_height(entry["right"], red)
        assert left == right
        return left + (0 if red else 1)

    black_height(child)
    assert len(reader.children(child)) == 37


def test_compound_reader_matches_olefile(tmp_path):
    olefile = pytest.importorskip("olefile")
    root, expected = sample_tree()
    path = tmp_path / "sample.stg"
    write_compound_file(root, path)
    ole = olefile.OleFileIO(str(path), raise_defects=olefile.DEFECT_INCORRECT)
    for parts, contents in expected.items():
        assert ole.openstream("/".join(parts)).read() == contents


def test_compound_rejects_bad_names_and_files():
    with pytest.raises(CompoundFileError):
        Storage().set_stream("a" * 32, b"")
    with pytest.raises(CompoundFileError):
        Storage().set_stream("a!b", b"")
    with pytest.raises(CompoundFileError):
        read_compound_file(b"not a compound file" * 40)


def test_backup_set_information_activesync_layout():
    information = BackupSetInformation(
        partnership_id=0x1234, processor_type=4000, store_pages=0x679, ram_pages=0x94F, page_size=0x1000,
        store_used=123456, backup_time=(2026, 11, 2, 24, 9, 30, 15, 250), os_version=(2 << 16) | 0,
        language=0x409, not_handheld_pc=0, processor_level=4, processor_revision=0x400, oem_info="VELO 1",
    )
    data = information.pack()
    assert len(data) == 0x30 + 8 + 0x148
    assert struct.unpack_from("<6I", data) == (0x1234, 4000, 0x679, 0x94F, 0x1000, 123456)
    assert struct.unpack_from("<II", data, 0x28) == (VERSION_ACTIVESYNC, 0x20000)
    assert struct.unpack_from("<II", data, 0x30) == (0x409, 0)
    assert struct.unpack_from("<HH", data, 0x38) == (4, 0x400)
    assert data[0x3C:0x42] == b"VELO 1"
    back = BackupSetInformation.unpack(data)
    assert back == information
    assert (back.os_major, back.os_minor) == (2, 0)
    assert back.created.year == 2026


def test_backup_set_information_hpc_explorer_layout():
    information = BackupSetInformation(version=VERSION_HPC_EXPLORER, os_version=1096, language=0x407)
    data = information.pack()
    assert len(data) == 0x38
    back = BackupSetInformation.unpack(data)
    assert (back.os_build, back.os_major, back.language) == (1096, None, 0x407)
    version_four = data[:0x28] + struct.pack("<II", 4, 0)
    assert BackupSetInformation.unpack(version_four).language == 0x409
    with pytest.raises(BackupFormatError):
        BackupSetInformation.unpack(data[:0x28] + struct.pack("<II", 7, 0) + bytes(8))


def test_file_stream_header():
    header = FileHeader(0x01BBF81E5E712000, 0x21, "Overview.lnk")
    data = pack_file_stream(header, b"26#\\Windows\\x.exe")
    assert data[:16] == struct.pack("<QIHH", 0x01BBF81E5E712000, 0x21, 12, 0)
    assert data[16:40] == "Overview.lnk".encode("utf-16-le")
    assert unpack_file_stream(data) == (header, b"26#\\Windows\\x.exe")


def test_database_info_and_records():
    info = DatabaseInfo("Contacts Database", 0x18, 7, 2, 2, 380, 0x01BBF81E5E712000, [(0x3A11001F, 2), (0x3A16001F, 2)])
    data = info.pack()
    assert len(data) == 0x78
    assert DatabaseInfo.unpack(data) == info
    properties = [cedb.PropertyValue(0x3A11, cedb.CEVT_LPWSTR, "Smith"), cedb.PropertyValue(0x4001, cedb.CEVT_I4, 5)]
    block = cedb.encode_properties(properties)
    stream = RecordBlock(2, block).pack()
    assert stream[:6] == struct.pack("<IH", len(block), 2)
    record = RecordBlock.unpack(stream)
    assert [prop.value for prop in cedb.decode_properties(record.block, record.property_count)] == ["Smith", 5]
    assert record_stream_name(0x4A6) == "Record_4A6"
    assert database_element_name("\\EventNotifications") == "?EventNotifications"
    assert database_name_from_element("?EventNotifications") == "\\EventNotifications"


def test_long_and_escaped_element_names():
    storage = Storage()
    long_name = "A very long file name that does not fit.txt"
    first = element_name_for(long_name, storage, False, full_name_of)
    assert first == long_name[:29] + "~A" and len(first) == 31
    storage.set_stream(first, pack_file_stream(FileHeader(0, 0, long_name), b""))
    assert element_name_for(long_name, storage, False, full_name_of) == first
    other = long_name[:29] + " but differs.txt"
    assert element_name_for(other, storage, False, full_name_of) == long_name[:29] + "~B"
    assert element_name_for("Hello!.txt", storage, False, full_name_of) == "Hello?.txt"
    assert element_name_for("x" * 31, storage, False, full_name_of) == "x" * 31


def build_backup(path):
    root = Storage()
    root.set_stream(BACKUP_SET_INFORMATION, BackupSetInformation(os_version=2 << 16, processor_type=4000).pack())
    documents = root.create_storage("My Documents")
    documents.set_stream(DIRECTORY_ATTRIBUTES, FileHeader(0, 0x10, "My Documents").pack())
    documents.set_stream("notes.txt", pack_file_stream(FileHeader(0x01BBF81E5E712000, 0x20, "notes.txt"), b"hello"))
    windows = root.create_storage("Windows")
    windows.set_stream(DIRECTORY_ATTRIBUTES, FileHeader(0, 0x10, "Windows").pack())
    windows.set_stream("Restore.fdf", pack_file_stream(FileHeader(0, 0x20, "Restore.fdf"), b"R" * 100))
    databases = root.create_storage(PEGASUS_DATABASES)
    contacts = databases.create_storage("Contacts Database")
    contacts.set_stream(DATABASE_INFO, DatabaseInfo("Contacts Database", 0x18, record_count=1).pack())
    block = cedb.encode_properties([cedb.PropertyValue(0x3A11, cedb.CEVT_LPWSTR, "Smith")])
    contacts.set_stream("Record_4A7", RecordBlock(1, block).pack())
    write_compound_file(root, path)


def test_inspect(tmp_path):
    path = tmp_path / "Backup.stg"
    build_backup(path)
    contents = inspect(path)
    assert contents.information.os_major == 2
    assert sorted((entry.path, entry.size) for entry in contents.files) == [
        ("\\My Documents\\notes.txt", 5), ("\\Windows\\Restore.fdf", 100)]
    assert [entry.path for entry in contents.folders] == ["\\Windows", "\\My Documents"]
    assert contents.registry_size == 100
    assert [(database.name, database.records) for database in contents.databases] == [("Contacts Database", 1)]


def test_inspect_rejects_other_files(tmp_path):
    path = tmp_path / "other.stg"
    root = Storage()
    root.set_stream("Contents", b"x")
    write_compound_file(root, path)
    with pytest.raises(BackupError):
        inspect(path)
    (tmp_path / "plain.stg").write_bytes(b"plain")
    with pytest.raises(BackupError):
        inspect(tmp_path / "plain.stg")


def device_state(major=2, minor=0, processor=4000):
    version = VersionInfo(major, minor, 0, 3, "")
    system = SystemInfo(0, 4096, 0, 0, 1, 1, processor, 0, 4, 0x400)
    return version, system


def test_compatibility_checks():
    information = BackupSetInformation(processor_type=4000, os_version=(2 << 16) | 0, language=0x409,
                                       processor_level=4, processor_revision=0x400, oem_info="VELO 1")
    identity = DeviceIdentity("HPC", "VELO 1")
    assert compatibility_problems(information, *device_state(), 0x409, identity) == ([], False)
    assert compatibility_problems(information, *device_state(minor=1), 0x409, identity) == ([], True)
    problems, _ = compatibility_problems(information, *device_state(major=3), 0x409, identity)
    assert problems
    problems, _ = compatibility_problems(information, *device_state(processor=10003), 0x407, DeviceIdentity("Palm PC", "Other"))
    assert len(problems) == 4


def test_shortcut_target():
    assert shortcut_target("26#\\Windows\\LoadTest\\tool.exe") == "\\Windows\\LoadTest\\tool.exe"
    assert shortcut_target('59#"\\Windows\\ctlpnl.exe" \\Windows\\sounds.cpl,Volume') == "\\Windows\\ctlpnl.exe"
