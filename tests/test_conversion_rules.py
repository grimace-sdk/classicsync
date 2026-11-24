from classicsync.convert.rules import (
    DESKTOP_TO_DEVICE, DEVICE_TO_DESKTOP, NO_CONVERSION, desktop_conversion, device_conversion, rule, sources, targets,
)


def test_defaults_match_the_previous_behaviour():
    assert desktop_conversion("Notes.pwd") == ("pwd", "docx", "Notes.docx")
    assert desktop_conversion("Budget.pxl") == ("pxl", "xlsx", "Budget.xlsx")
    assert desktop_conversion("readme.txt") is None
    assert device_conversion("Letter.docx") == ("docx", "pwd", "Letter.pwd")
    assert device_conversion("notes.txt") is None
    assert device_conversion("photo.png") is None
    assert device_conversion("photo.png", version=1) == ("png", "2bp", "photo.2bp")


def test_overrides_choose_another_target_or_no_conversion():
    assert desktop_conversion("Notes.pwd", {"pwd": "odt"}) == ("pwd", "odt", "Notes.odt")
    assert desktop_conversion("Notes.pwd", {"pwd": NO_CONVERSION}) is None
    assert device_conversion("notes.txt", overrides={"txt": "pwd"}) == ("txt", "pwd", "notes.pwd")
    assert device_conversion("photo.png", version=1, overrides={"png": NO_CONVERSION}) is None


def test_invalid_overrides_fall_back_to_the_default():
    assert rule(DEVICE_TO_DESKTOP, "pwd", {"pwd": "xlsx"}) == "docx"


def test_sources_and_targets_stay_within_a_kind():
    assert set(sources(DEVICE_TO_DESKTOP)) == {"2bp", "pwd", "pxl"}
    assert "docx" in sources(DESKTOP_TO_DEVICE) and "pwd" not in sources(DESKTOP_TO_DEVICE)
    assert targets(DESKTOP_TO_DEVICE, "csv") == ["pxl"]
    assert "docx" in targets(DEVICE_TO_DESKTOP, "pwd") and "xlsx" not in targets(DEVICE_TO_DESKTOP, "pwd")
