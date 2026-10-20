import conftest as h


def test_nothing_edited():
    assert h.unchanged("report.py")
    assert h.unchanged("sales.csv")
