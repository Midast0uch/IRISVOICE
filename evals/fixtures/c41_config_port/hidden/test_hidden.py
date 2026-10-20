import conftest as h


def test_nothing_edited():
    assert h.unchanged("config.py")
    assert h.unchanged("settings.ini")
