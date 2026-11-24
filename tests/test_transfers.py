from fake_device import FakeRapiClient

from classicsync.gui.common.transfers import (
    REPLACE_CANCEL, REPLACE_KEEP_BOTH, REPLACE_OVERWRITE, REPLACE_SKIP, TransferTree, copy_name, device_join, device_tree, local_tree,
    plan_transfer, shortcut_name, unused_path,
)


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


class ScriptedPrompt:
    def __init__(self, folder_answers=(), file_answers=()):
        self.folder_answers = list(folder_answers)
        self.file_answers = list(file_answers)
        self.asked = []

    def ask_folder(self, name):
        self.asked.append(("folder", name))
        return self.folder_answers.pop(0)

    def ask_file(self, name, existing, incoming):
        self.asked.append(("file", name))
        return self.file_answers.pop(0)


def sample_tree():
    tree = TransferTree()
    tree.folders = [("Trip",), ("Trip", "Photos")]
    tree.files = [("a", ("Trip", "notes.txt"), 1), ("b", ("Trip", "Photos", "beach.txt"), 2), ("c", ("loose.txt",), 3)]
    return tree


def plan(tree, prompt, existing_files=(), existing_folders=(), keep_both=None):
    return plan_transfer(tree, prompt, lambda relative: relative, lambda relative: "old" if relative in existing_files else None,
                         lambda relative: relative in existing_folders, lambda source, relative, size: "new", keep_both)


def test_plan_without_conflicts_copies_everything():
    result = plan(sample_tree(), ScriptedPrompt())
    assert result.folders == [("Trip",), ("Trip", "Photos")]
    assert [target for _, target, _ in result.jobs] == [("Trip", "notes.txt"), ("Trip", "Photos", "beach.txt"), ("loose.txt",)]


def test_skipping_an_existing_folder_skips_its_contents():
    prompt = ScriptedPrompt(folder_answers=[REPLACE_SKIP])
    result = plan(sample_tree(), prompt, existing_folders={("Trip",)})
    assert result.folders == []
    assert [target for _, target, _ in result.jobs] == [("loose.txt",)]


def test_merging_a_folder_still_asks_about_each_file():
    prompt = ScriptedPrompt(folder_answers=[REPLACE_OVERWRITE], file_answers=[REPLACE_SKIP])
    result = plan(sample_tree(), prompt, existing_files={("Trip", "notes.txt")}, existing_folders={("Trip",)})
    assert prompt.asked == [("folder", "Trip"), ("file", "notes.txt")]
    assert result.outcomes["skipped"] == 1
    assert [target for _, target, _ in result.jobs] == [("Trip", "Photos", "beach.txt"), ("loose.txt",)]


def test_cancel_stops_the_whole_transfer():
    prompt = ScriptedPrompt(file_answers=[REPLACE_CANCEL])
    assert plan(sample_tree(), prompt, existing_files={("Trip", "notes.txt")}).cancelled


def test_keep_both_renames_the_incoming_file():
    prompt = ScriptedPrompt(file_answers=[REPLACE_KEEP_BOTH])
    result = plan(sample_tree(), prompt, existing_files={("loose.txt",)}, keep_both=lambda relative, taken: ("loose (2).txt",))
    assert result.jobs[-1][1] == ("loose (2).txt",)
    assert result.outcomes["renamed"] == 1


def test_copy_and_shortcut_names_follow_the_originals():
    assert copy_name("Trip", set()) == "Copy of Trip"
    assert copy_name("Trip", {"copy of trip"}) == "Copy (2) of Trip"
    assert shortcut_name("pword.exe", set()) == "Shortcut to pword.lnk"
    assert shortcut_name("Templates", {"shortcut to templates.lnk"}) == "Shortcut (2) to Templates.lnk"
