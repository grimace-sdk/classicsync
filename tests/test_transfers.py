from fake_device import FakeRapiClient

from classicsync.gui.common.transfers import device_join, device_tree, local_tree, unused_path


def test_device_join_handles_the_root_and_nested_names():
    assert device_join("\\", "My Documents") == "\\My Documents"
    assert device_join("\\My Documents", "Trip", "notes.txt") == "\\My Documents\\Trip\\notes.txt"


def test_device_tree_lists_nested_folders_and_files(run):
    client = FakeRapiClient()
    client.directories["\\my documents\\trip"] = "\\My Documents\\Trip"
    client.directories["\\my documents\\trip\\photos"] = "\\My Documents\\Trip\\Photos"
    client.directories["\\my documents\\trip\\empty"] = "\\My Documents\\Trip\\Empty"
    client.put_file("\\My Documents\\Trip\\plan.pwd", b"plan")
    client.put_file("\\My Documents\\Trip\\Photos\\beach.2bp", b"beach!")

    async def scenario():
        return await device_tree(client, "\\My Documents\\Trip", ("Trip",))
    tree = run(scenario)
    assert tree.folders == [("Trip", "Empty"), ("Trip", "Photos")]
    assert tree.files == [("\\My Documents\\Trip\\Photos\\beach.2bp", ("Trip", "Photos", "beach.2bp"), 6),
                          ("\\My Documents\\Trip\\plan.pwd", ("Trip", "plan.pwd"), 4)]


def test_local_tree_walks_folders_and_skips_hidden_files(tmp_path):
    trip = tmp_path / "Trip"
    (trip / "Photos").mkdir(parents=True)
    (trip / "Empty").mkdir()
    (trip / ".git").mkdir()
    (trip / ".git" / "config").write_text("x")
    (trip / ".DS_Store").write_bytes(b"x")
    (trip / "plan.docx").write_bytes(b"plan")
    (trip / "Photos" / "beach.png").write_bytes(b"beach!")
    (tmp_path / "loose.txt").write_bytes(b"loose")
    tree = local_tree([tmp_path / "loose.txt", trip])
    assert tree.folders == [("Trip",), ("Trip", "Empty"), ("Trip", "Photos")]
    assert [(relative, size) for _, relative, size in tree.files] == [
        (("loose.txt",), 5), (("Trip", "plan.docx"), 4), (("Trip", "Photos", "beach.png"), 6)]


def test_unused_path_numbers_existing_and_taken_names(tmp_path):
    (tmp_path / "romdump.txt").write_text("old")
    (tmp_path / "romdump (2).txt").write_text("old")
    assert unused_path(tmp_path / "romdump.txt") == tmp_path / "romdump (3).txt"
    assert unused_path(tmp_path / "romdump.txt", {tmp_path / "romdump (3).txt"}) == tmp_path / "romdump (4).txt"
    assert unused_path(tmp_path / "new.txt") == tmp_path / "new.txt"
