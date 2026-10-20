import conftest as h


def test_nothing_edited():
    assert h.unchanged("main.py")
    assert h.unchanged("textstats.py")
    assert h.unchanged("test_textstats.py")
